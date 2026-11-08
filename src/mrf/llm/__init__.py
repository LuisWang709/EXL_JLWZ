"""LLM wrapper. Owner: A1. Used by every agent (classify, doc, rating reviewer, rebuild).

    from mrf.llm import ChatMessage, get_llm
    res = await get_llm().chat(
        [ChatMessage(role="system", content=SYS), ChatMessage(role="user", content=prompt)],
        role="doc_writer",              # selects the model (config llm.role_models) and the mock responder
        json_schema=MyPydanticModel,    # optional -> res.parsed is a validated MyPydanticModel
    )
    res.text, res.parsed, res.tool_calls, res.usage

* transient errors (429 / timeout / 5xx) -> backoff 1s, 2s, 4s + jitter, max 3 retries
  -> MRFError(MRF-4002 rate limit | MRF-4001 timeout). Invalid JSON after 1 repair -> MRF-4003.
* every call adds tokens / cost / latency to ``res.usage`` and to any open ``track_usage()`` scope.
* ``MRF_LLM_PROVIDER=mock`` (default, CI) -> :class:`MockLLM`, no network. Configure with ``get_mock()``.
* do NOT add your own retry loop around ``chat`` - quality retries are counted by the orchestrator.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from mrf.config import get_settings
from mrf.llm.base import BackoffPolicy, BaseLLM, ChatMessage, LLMResult
from mrf.llm.mock import MockLLM
from mrf.llm.usage import track_usage

__all__ = [
    "BackoffPolicy",
    "BaseLLM",
    "ChatMessage",
    "LLMClient",
    "LLMResult",
    "MockLLM",
    "get_llm",
    "get_mock",
    "set_llm",
    "track_usage",
]


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        role: str,
        json_schema: type[BaseModel] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> LLMResult: ...


_client: BaseLLM | None = None


def get_llm() -> BaseLLM:
    """Process-wide client chosen by MRF_LLM_PROVIDER (mock | azure_openai | openai | github_models)."""
    global _client
    if _client is None:
        provider = get_settings().llm_provider
        if provider == "mock":
            _client = MockLLM()
        else:
            from mrf.llm.openai_client import OpenAICompatLLM

            _client = OpenAICompatLLM(provider)
    return _client


def set_llm(client: BaseLLM | None) -> None:
    """Swap the process-wide client (tests). ``None`` resets to the configured provider."""
    global _client
    _client = client


def get_mock() -> MockLLM:
    """The active MockLLM (raises if a real provider is configured)."""
    client = get_llm()
    if not isinstance(client, MockLLM):
        raise RuntimeError("get_mock() needs MRF_LLM_PROVIDER=mock")
    return client
