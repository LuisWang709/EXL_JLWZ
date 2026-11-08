"""Usage aggregation across nested scopes.

    with track_usage() as u:          # orchestrator wraps each step
        await agent.draft(ctx)        # every LLM call inside adds to u
    pipeline.usage += u

Scopes nest: an inner scope's usage is also added to every outer scope.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from mrf.contracts.models import Usage

_scopes: ContextVar[tuple[Usage, ...]] = ContextVar("mrf_usage_scopes", default=())


def add_usage(target: Usage, delta: Usage) -> None:
    target.prompt_tokens += delta.prompt_tokens
    target.completion_tokens += delta.completion_tokens
    target.cost_eur = round(target.cost_eur + delta.cost_eur, 6)
    target.latency_ms += delta.latency_ms
    target.llm_calls += delta.llm_calls
    target.backoff_retries += delta.backoff_retries


def record_usage(delta: Usage) -> None:
    for scope in _scopes.get():
        add_usage(scope, delta)


@contextmanager
def track_usage() -> Iterator[Usage]:
    usage = Usage()
    token = _scopes.set((*_scopes.get(), usage))
    try:
        yield usage
    finally:
        _scopes.reset(token)
