"""LLM wrapper. Owner: A1. Used by every agent (classify, doc, rating reviewer, rebuild).

Contract (implementation lands 11/3, see docs/design/A1 design doc):

    client = get_llm()                       # provider chosen by MRF_LLM_PROVIDER
    res = await client.chat(messages, role="doc_writer", json_schema=MySchema)
    res.text / res.parsed / res.usage

* transient errors (429/timeout/5xx) -> exponential backoff 1s, 2s, 4s + jitter, max 3;
  then MRFError(MRF-4001/4002). Invalid JSON after retries -> MRF-4003.
* every call records tokens, cost and latency in ``res.usage``.
* ``provider=mock`` returns deterministic fixtures for CI - no network.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from mrf.contracts.models import Usage


class ChatMessage(BaseModel):
    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class LLMResult(BaseModel):
    text: str
    parsed: Any | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    provider: str = ""
    model: str = ""


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


def get_llm() -> LLMClient:
    """Factory - implemented in mrf.llm.client (A1, 11/3)."""
    raise NotImplementedError("mrf.llm.get_llm is implemented by A1 on 11/3")
