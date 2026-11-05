"""Deterministic offline LLM for tests, CI and local runs (MRF_LLM_PROVIDER=mock).

from mrf.llm import get_mock
mock = get_mock()
mock.register("doc_writer", {"sections": {...}})            # static (dict / BaseModel / str)
mock.register("rater", [resp_attempt1, resp_attempt2])         # sequence: one per call, last repeats
mock.register("classifier", lambda messages, schema: {...})    # function of the prompt
mock.fail_next("doc_writer", "rate_limit", times=2)            # inject transient faults
mock.calls                                                     # everything that was sent
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from mrf.llm.base import BaseLLM, ChatMessage, RawCompletion, TransientLLMError

Responder = str | dict[str, Any] | BaseModel | Callable[[list[ChatMessage], type[BaseModel] | None], Any] | list[Any]


@dataclass
class MockCall:
    role: str
    model: str
    messages: list[ChatMessage]
    json_schema: str | None
    tools: list[dict[str, Any]] | None


def _to_text(value: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(value, BaseModel):
        return value.model_dump_json(), []
    if isinstance(value, dict) and "__tool_calls__" in value:
        return "", list(value["__tool_calls__"])
    if isinstance(value, dict | list):
        return json.dumps(value, default=str), []
    return str(value), []


class MockLLM(BaseLLM):
    provider = "mock"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("default_model", "mock-model")
        super().__init__(**kwargs)
        self._responders: dict[str, Responder] = {}
        self._counters: dict[str, int] = defaultdict(int)
        self._faults: dict[str, list[str]] = defaultdict(list)
        self.calls: list[MockCall] = []

    # ------------------------------------------------------------------ configuration
    def register(self, role: str, responder: Responder) -> MockLLM:
        self._responders[role] = responder
        self._counters[role] = 0
        return self

    def fail_next(self, role: str, kind: Literal["rate_limit", "timeout"] = "rate_limit", times: int = 1) -> MockLLM:
        self._faults[role].extend([kind] * times)
        return self

    def reset(self) -> None:
        self._responders.clear()
        self._counters.clear()
        self._faults.clear()
        self.calls.clear()

    # ------------------------------------------------------------------ provider hook
    async def _complete(
        self,
        *,
        role: str,
        model: str,
        messages: list[ChatMessage],
        json_schema: type[BaseModel] | None,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> RawCompletion:
        self.calls.append(MockCall(role, model, list(messages), json_schema.__name__ if json_schema else None, tools))
        if self._faults[role]:
            kind = self._faults[role].pop(0)
            raise TransientLLMError(kind, f"mock {kind}")  # type: ignore[arg-type]

        value = self._resolve(role, messages, json_schema)
        text, tool_calls = _to_text(value)
        prompt_chars = sum(len(m.content) for m in messages)
        return RawCompletion(
            text=text,
            prompt_tokens=max(1, prompt_chars // 4),
            completion_tokens=max(1, len(text) // 4),
            model=model,
            tool_calls=tool_calls,
        )

    def _resolve(self, role: str, messages: list[ChatMessage], schema: type[BaseModel] | None) -> Any:
        responder = self._responders.get(role)
        idx = self._counters[role]
        self._counters[role] += 1
        if responder is None:
            return self._default(role, schema)
        if isinstance(responder, list):
            responder = responder[min(idx, len(responder) - 1)]
        if callable(responder) and not isinstance(responder, BaseModel):
            return responder(messages, schema)
        return responder

    @staticmethod
    def _default(role: str, schema: type[BaseModel] | None) -> Any:
        if schema is None:
            return f"[mock:{role}] ok"
        try:
            return schema()  # works when every field has a default
        except ValidationError:
            # invalid on purpose -> MRF-4003 tells the developer to register a responder
            return f"[mock:{role}] no responder registered for schema {schema.__name__}; use get_mock().register()"
