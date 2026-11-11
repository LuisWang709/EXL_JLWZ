from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from mrf.core import MRFCode, MRFError
from mrf.llm import ChatMessage, MockLLM, track_usage
from mrf.llm.base import BackoffPolicy


class Out(BaseModel):
    algorithm: str
    confidence: float


def _mock() -> tuple[MockLLM, list[float]]:
    delays: list[float] = []

    async def fake_sleep(d: float) -> None:
        delays.append(d)

    return MockLLM(policy=BackoffPolicy(max_jitter_s=0.0), sleep=fake_sleep), delays


MSG = [ChatMessage(role="user", content="hello world")]


async def test_json_schema_parsed() -> None:
    llm, _ = _mock()
    llm.register("classifier", {"algorithm": "logistic_regression", "confidence": 0.9})
    res = await llm.chat(MSG, role="classifier", json_schema=Out)
    assert isinstance(res.parsed, Out) and res.parsed.confidence == 0.9
    assert res.usage.llm_calls == 1 and res.usage.prompt_tokens > 0 and res.usage.cost_eur > 0


async def test_backoff_1_2_4_then_success() -> None:
    llm, delays = _mock()
    llm.register("doc_writer", "ok").fail_next("doc_writer", "rate_limit", times=3)
    res = await llm.chat(MSG, role="doc_writer")
    assert res.text == "ok" and delays == [1.0, 2.0, 4.0] and res.usage.backoff_retries == 3


async def test_backoff_exhausted_maps_to_codes() -> None:
    llm, delays = _mock()
    llm.fail_next("r", "rate_limit", times=4)
    with pytest.raises(MRFError) as e:
        await llm.chat(MSG, role="r")
    assert e.value.code is MRFCode.LLM_RATE_LIMIT and len(delays) == 3
    llm.fail_next("t", "timeout", times=4)
    with pytest.raises(MRFError) as e:
        await llm.chat(MSG, role="t")
    assert e.value.code is MRFCode.LLM_TIMEOUT


def test_retry_after_is_honoured_and_capped() -> None:
    p = BackoffPolicy(max_jitter_s=0.0, max_retry_after_s=8)
    assert p.delay(0, retry_after=5) == 5 and p.delay(0, retry_after=60) == 8 and p.delay(2) == 4


async def test_invalid_json_repaired_once_then_4003() -> None:
    llm, _ = _mock()
    llm.register("x", ["not json", {"algorithm": "tree", "confidence": 0.5}])
    res = await llm.chat(MSG, role="x", json_schema=Out)
    assert res.parsed.algorithm == "tree" and res.usage.llm_calls == 2
    llm.register("y", "still not json")
    with pytest.raises(MRFError) as e:
        await llm.chat(MSG, role="y", json_schema=Out)
    assert e.value.code is MRFCode.LLM_BAD_OUTPUT


async def test_fenced_json_and_callable_responder() -> None:
    llm, _ = _mock()

    def responder(msgs: list[ChatMessage], schema: object) -> str:
        return "```json\n" + json.dumps({"algorithm": msgs[-1].content, "confidence": 1}) + "\n```"

    llm.register("z", responder)
    res = await llm.chat(MSG, role="z", json_schema=Out)
    assert res.parsed.algorithm == "hello world"


async def test_track_usage_scopes_nest() -> None:
    llm, _ = _mock()
    with track_usage() as outer:
        await llm.chat(MSG, role="a")
        with track_usage() as inner:
            await llm.chat(MSG, role="b")
    assert outer.llm_calls == 2 and inner.llm_calls == 1


def test_role_models_from_config_and_reviewer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from mrf.config import get_settings

    monkeypatch.setenv("MRF_LLM_REVIEWER_MODEL", "gpt-4o")
    get_settings.cache_clear()
    llm = MockLLM(default_model="gpt-4o-mini")
    assert llm.model_for("rater") == "gpt-4o" and llm.model_for("doc_writer") == "gpt-4o-mini"


# ---------------------------------------------------------------- OpenAI-compatible providers (DeepSeek etc.)
class _FakeCompletions:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def create(self, **kwargs: object) -> object:
        from types import SimpleNamespace as NS

        self.sent.append(kwargs)
        msg = NS(content='{"algorithm": "tree", "confidence": 0.5}', tool_calls=None)
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=10, completion_tokens=5), model=kwargs["model"])


def _fake_sdk(base_url: str) -> object:
    from types import SimpleNamespace as NS

    return NS(base_url=base_url, chat=NS(completions=_FakeCompletions()))


def test_json_mode_resolution() -> None:
    from mrf.llm.openai_client import resolve_json_mode

    assert resolve_json_mode("azure_openai", None, "auto") == "json_schema"
    assert resolve_json_mode("openai", "https://api.openai.com/v1/", "auto") == "json_schema"
    assert resolve_json_mode("openai", "https://api.deepseek.com", "auto") == "json_object"
    assert resolve_json_mode("github_models", "https://models.inference.ai.azure.com", "auto") == "json_object"
    assert resolve_json_mode("openai", "https://api.deepseek.com", "json_schema") == "json_schema"


async def test_deepseek_gets_json_object_and_schema_in_prompt() -> None:
    from mrf.llm.openai_client import OpenAICompatLLM

    sdk = _fake_sdk("https://api.deepseek.com")
    llm = OpenAICompatLLM("openai", sdk=sdk, default_model="deepseek-chat")  # type: ignore[arg-type]
    res = await llm.chat(MSG, role="classifier", json_schema=Out)
    sent = sdk.chat.completions.sent[0]  # type: ignore[attr-defined]
    assert sent["response_format"] == {"type": "json_object"} and sent["model"] == "deepseek-chat"
    assert "json" in sent["messages"][-1]["content"] and '"algorithm"' in sent["messages"][-1]["content"]
    assert res.parsed.algorithm == "tree" and res.usage.prompt_tokens == 10


async def test_openai_gets_strict_json_schema() -> None:
    from mrf.llm.openai_client import OpenAICompatLLM

    sdk = _fake_sdk("https://api.openai.com/v1/")
    llm = OpenAICompatLLM("openai", sdk=sdk)  # type: ignore[arg-type]
    await llm.chat(MSG, role="classifier", json_schema=Out)
    sent = sdk.chat.completions.sent[0]  # type: ignore[attr-defined]
    assert sent["response_format"]["type"] == "json_schema" and len(sent["messages"]) == 1


async def test_reasoning_models_get_no_temperature_and_max_completion_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from mrf.llm.openai_client import OpenAICompatLLM, is_reasoning_model

    monkeypatch.delenv("MRF_LLM_REASONING", raising=False)
    assert is_reasoning_model("gpt-5-mini") and is_reasoning_model("o4-mini")
    assert not is_reasoning_model("gpt-4o-mini") and not is_reasoning_model("deepseek-chat")
    assert not is_reasoning_model("gpt-5-chat")

    sdk = _fake_sdk("")
    llm = OpenAICompatLLM("azure_openai", sdk=sdk, default_model="gpt-5-mini")  # type: ignore[arg-type]
    await llm.chat(MSG, role="classifier", max_tokens=300)
    sent = sdk.chat.completions.sent[0]  # type: ignore[attr-defined]
    assert "temperature" not in sent and "max_tokens" not in sent and sent["max_completion_tokens"] == 300

    sdk = _fake_sdk("https://api.deepseek.com")
    llm = OpenAICompatLLM("openai", sdk=sdk, default_model="deepseek-chat")  # type: ignore[arg-type]
    await llm.chat(MSG, role="classifier", max_tokens=300)
    sent = sdk.chat.completions.sent[0]  # type: ignore[attr-defined]
    assert sent["temperature"] == 0.0 and sent["max_tokens"] == 300


def test_reasoning_detection_can_be_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    from mrf.llm.openai_client import is_reasoning_model

    monkeypatch.setenv("MRF_LLM_REASONING", "true")
    assert is_reasoning_model("my-deployment")
    monkeypatch.setenv("MRF_LLM_REASONING", "false")
    assert not is_reasoning_model("gpt-5-mini")


def test_price_matches_dated_snapshot_names() -> None:
    from mrf.llm.base import _rate

    table = {
        "default": {"prompt": 0.1, "completion": 0.2},
        "gpt-4o": {"prompt": 1.0, "completion": 2.0},
        "gpt-4o-mini": {"prompt": 3.0, "completion": 4.0},
        "gpt-5-mini": {"prompt": 5.0, "completion": 6.0},
    }
    assert _rate("gpt-5-mini-2025-08-07", table)["prompt"] == 5.0  # Azure returns the snapshot name
    assert _rate("gpt-4o-mini-2024-07-18", table)["prompt"] == 3.0  # longest prefix wins over gpt-4o
    assert _rate("gpt-4o", table)["prompt"] == 1.0
    assert _rate("deepseek-chat", table)["prompt"] == 0.1
