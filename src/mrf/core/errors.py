"""The single exception type that crosses module boundaries."""

from __future__ import annotations

from typing import Any

from mrf.core.codes import MRFCode


class MRFError(Exception):
    """Raise this (not bare exceptions) from agents, tools and services.

    The API layer converts it into an error envelope; the orchestrator uses ``code`` to decide
    between retry, manual review and failure.
    """

    def __init__(
        self,
        code: MRFCode,
        message: str | None = None,
        *,
        field: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or code.default_message
        self.field = field
        self.detail = detail or {}
        super().__init__(f"{code.value}: {self.message}")

    @property
    def http_status(self) -> int:
        return self.code.http_status
