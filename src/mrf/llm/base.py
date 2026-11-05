"""Provider-independent LLM logic: backoff, JSON-schema validation + repair, usage accounting.

Concrete providers (OpenAI-compatible SDK, Mock) only implement :meth:`BaseLLM._complete`
and translate their errors into :class:`TransientLLMError` / :class:`FatalLLMError`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from mrf.config import get_policy, get_settings
from mrf.contracts.models import Usage
from mrf.core import MRFCode, MRFError
from mrf.llm.usage import record_usage

log = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class ChatMessage(BaseModel):
    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    def to_openai(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            msg["name"] = self.name
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


class LLMResult(BaseModel):
    text: str
    parsed: Any | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    provider: str = ""
    model: str = ""


@dataclass
class RawCompletion:
    """What a provider returns for one HTTP call."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class TransientLLMError(Exception):
    """Retry with backoff: rate limit, timeout, connection, 5xx."""

    def __init__(self, kind: Literal["rate_limit", "timeout"], message: str = "", retry_after: float | None = None):
        super().__init__(message or kind)
        self.kind = kind
        self.retry_after = retry_after


class FatalLLMError(Exception):
    """Do not retry: bad request, content filter, auth."""


@dataclass
class BackoffPolicy:
    max_retries: int = 3
    base_delay_s: float = 1.0
    max_jitter_s: float = 0.5
    max_retry_after_s: float = 8.0

    @classmethod
    def from_config(cls) -> BackoffPolicy:
        p = get_policy()
        t = p["retries"]["llm_transient"]
        return cls(
            max_retries=int(t["max_retries"]),
            base_delay_s=float(t["base_delay_s"]),
            max_jitter_s=float(t["max_jitter_s"]),
            max_retry_after_s=float(p.get("llm", {}).get("max_retry_after_s", 8)),
        )

    def delay(self, retry_index: int, retry_after: float | None = None) -> float:
        """retry_index 0,1,2 -> 1s, 2s, 4s (+ jitter); honours Retry-After up to the cap."""
        planned = self.base_delay_s * (2**retry_index) + random.uniform(0, self.max_jitter_s)  # noqa: S311
        if retry_after is not None:
            planned = max(planned, min(retry_after, self.max_retry_after_s))
        return planned


def _price(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    table = get_policy().get("llm", {}).get("pricing_eur_per_1k", {})
    rate = table.get(model) or table.get("default") or {"prompt": 0.0, "completion": 0.0}
    return round(prompt_tokens / 1000 * rate["prompt"] + completion_tokens / 1000 * rate["completion"], 6)


class BaseLLM(ABC):
    provider: str = "base"

    def __init__(
        self,
        *,
        default_model: str | None = None,
        role_models: dict[str, str] | None = None,
        policy: BackoffPolicy | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        settings = get_settings()
        self.default_model = default_model or settings.llm_model
        cfg_roles = dict(get_policy().get("llm", {}).get("role_models") or {})
        if settings.llm_reviewer_model:
            cfg_roles.setdefault("rater", settings.llm_reviewer_model)
        cfg_roles.update(role_models or {})
        self.role_models = cfg_roles
        self.policy = policy or BackoffPolicy.from_config()
        self._sleep: Sleep = sleep or asyncio.sleep
        self.repair_attempts = int(get_policy().get("llm", {}).get("json_repair_attempts", 1))

    # ------------------------------------------------------------------ provider hook
    @abstractmethod
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
    ) -> RawCompletion: ...

    # ------------------------------------------------------------------ public API
    def model_for(self, role: str) -> str:
        return self.role_models.get(role, self.default_model)

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
    ) -> LLMResult:
        """One logical LLM call. Transient errors are retried here (1s/2s/4s + jitter, max 3);
        invalid JSON gets ``json_repair_attempts`` repair round(s). Raises MRFError 4001/4002/4003."""
        model = self.model_for(role)
        usage = Usage()
        convo = list(messages)
        raw = await self._with_backoff(role, model, convo, json_schema, tools, temperature, max_tokens, usage)
        parsed: Any = None
        if json_schema is not None and not raw.tool_calls:
            for repair in range(self.repair_attempts + 1):
                try:
                    parsed = json_schema.model_validate_json(_strip_fences(raw.text))
                    break
                except ValidationError as exc:
                    if repair == self.repair_attempts:
                        self._finish(usage, role, metadata)
                        raise MRFError(
                            MRFCode.LLM_BAD_OUTPUT,
                            f"LLM output for role '{role}' does not match {json_schema.__name__}",
                            detail={"errors": exc.errors(include_url=False)[:5], "text": raw.text[:500]},
                        ) from exc
                    convo = [
                        *convo,
                        ChatMessage(role="assistant", content=raw.text),
                        ChatMessage(
                            role="user",
                            content="Your previous answer was not valid JSON for the required schema. "
                            f"Validation errors: {json.dumps(exc.errors(include_url=False)[:5], default=str)}. "
                            "Reply again with ONLY the corrected JSON object.",
                        ),
                    ]
                    raw = await self._with_backoff(
                        role, model, convo, json_schema, tools, temperature, max_tokens, usage
                    )
        self._finish(usage, role, metadata)
        return LLMResult(
            text=raw.text,
            parsed=parsed,
            tool_calls=raw.tool_calls,
            usage=usage,
            provider=self.provider,
            model=raw.model or model,
        )

    # ------------------------------------------------------------------ internals
    async def _with_backoff(
        self,
        role: str,
        model: str,
        messages: list[ChatMessage],
        json_schema: type[BaseModel] | None,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
        usage: Usage,
    ) -> RawCompletion:
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                raw = await self._complete(
                    role=role,
                    model=model,
                    messages=messages,
                    json_schema=json_schema,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except TransientLLMError as exc:
                usage.latency_ms += int((time.perf_counter() - started) * 1000)
                if attempt >= self.policy.max_retries:
                    code = MRFCode.LLM_RATE_LIMIT if exc.kind == "rate_limit" else MRFCode.LLM_TIMEOUT
                    raise MRFError(code, f"{code.default_message} (role={role}, model={model}): {exc}") from exc
                wait = self.policy.delay(attempt, exc.retry_after)
                log.warning("llm %s transient %s, retry %d in %.2fs", role, exc.kind, attempt + 1, wait)
                usage.backoff_retries += 1
                attempt += 1
                await self._sleep(wait)
                continue
            except FatalLLMError as exc:
                raise MRFError(MRFCode.LLM_BAD_OUTPUT, f"LLM request rejected (role={role}): {exc}") from exc
            usage.latency_ms += int((time.perf_counter() - started) * 1000)
            usage.llm_calls += 1
            usage.prompt_tokens += raw.prompt_tokens
            usage.completion_tokens += raw.completion_tokens
            usage.cost_eur = round(
                usage.cost_eur + _price(raw.model or model, raw.prompt_tokens, raw.completion_tokens), 6
            )
            return raw

    @staticmethod
    def _finish(usage: Usage, role: str, metadata: dict[str, str] | None) -> None:
        record_usage(usage)
        log.info(
            "llm role=%s calls=%d tokens=%d/%d cost=%.5f meta=%s",
            role,
            usage.llm_calls,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.cost_eur,
            metadata or {},
        )


def _strip_fences(text: str) -> str:
    """Accept ```json ... ``` wrapped answers."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()
