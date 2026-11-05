"""MRF return codes (plan section "返回码"). Frozen with API contract v1.

Every error that leaves the API, the orchestrator or an agent must carry one of these codes.
"""

from __future__ import annotations

from enum import Enum


class MRFCode(str, Enum):
    """Return code -> (HTTP status, default message) via :attr:`http_status` / :attr:`default_message`."""

    OK = "MRF-0000"
    ACCEPTED = "MRF-0202"

    # 1xxx - invalid input
    INPUT_FILE_TYPE = "MRF-1001"
    INPUT_FILE_SIZE = "MRF-1002"
    INPUT_DATA_SCHEMA = "MRF-1003"
    INPUT_PERSONAL_DATA = "MRF-1004"
    INPUT_PROMPT_INJECTION = "MRF-1005"
    INPUT_BODY = "MRF-1006"
    NOT_FOUND = "MRF-1404"

    # 2xxx - identification / documentation
    CODE_UNPARSEABLE = "MRF-2001"
    MODEL_UNIDENTIFIED = "MRF-2002"
    DOC_RATING_EXHAUSTED = "MRF-2101"

    # 3xxx - rebuild / run / state
    PARITY_FAILED = "MRF-3001"
    PARITY_EXHAUSTED = "MRF-3002"
    SANDBOX_POLICY = "MRF-3003"
    DATA_QUALITY_FAILED = "MRF-3101"
    INVALID_STATE = "MRF-3201"

    # 4xxx - LLM (after 3 exponential backoffs)
    LLM_TIMEOUT = "MRF-4001"
    LLM_RATE_LIMIT = "MRF-4002"
    LLM_BAD_OUTPUT = "MRF-4003"

    # 5xxx
    INTERNAL = "MRF-5000"

    @property
    def http_status(self) -> int:
        return _HTTP[self]

    @property
    def default_message(self) -> str:
        return _MESSAGES[self]


_HTTP: dict[MRFCode, int] = {
    MRFCode.OK: 200,
    MRFCode.ACCEPTED: 202,
    MRFCode.INPUT_FILE_TYPE: 415,
    MRFCode.INPUT_FILE_SIZE: 413,
    MRFCode.INPUT_DATA_SCHEMA: 422,
    MRFCode.INPUT_PERSONAL_DATA: 422,
    MRFCode.INPUT_PROMPT_INJECTION: 422,
    MRFCode.INPUT_BODY: 422,
    MRFCode.NOT_FOUND: 404,
    MRFCode.CODE_UNPARSEABLE: 422,
    MRFCode.MODEL_UNIDENTIFIED: 422,
    MRFCode.DOC_RATING_EXHAUSTED: 409,
    MRFCode.PARITY_FAILED: 409,
    MRFCode.PARITY_EXHAUSTED: 409,
    MRFCode.SANDBOX_POLICY: 422,
    MRFCode.DATA_QUALITY_FAILED: 422,
    MRFCode.INVALID_STATE: 409,
    MRFCode.LLM_TIMEOUT: 504,
    MRFCode.LLM_RATE_LIMIT: 429,
    MRFCode.LLM_BAD_OUTPUT: 502,
    MRFCode.INTERNAL: 500,
}

_MESSAGES: dict[MRFCode, str] = {
    MRFCode.OK: "Success",
    MRFCode.ACCEPTED: "Job accepted",
    MRFCode.INPUT_FILE_TYPE: "Unsupported file type",
    MRFCode.INPUT_FILE_SIZE: "File too large",
    MRFCode.INPUT_DATA_SCHEMA: "Data does not match the expected schema",
    MRFCode.INPUT_PERSONAL_DATA: "Personal data detected in input",
    MRFCode.INPUT_PROMPT_INJECTION: "Possible prompt injection detected in input",
    MRFCode.INPUT_BODY: "Invalid request body",
    MRFCode.NOT_FOUND: "Resource not found",
    MRFCode.CODE_UNPARSEABLE: "Source code could not be parsed",
    MRFCode.MODEL_UNIDENTIFIED: "Model type could not be identified (confidence < threshold); sent to manual review",
    MRFCode.DOC_RATING_EXHAUSTED: "Documentation failed rating 3 times; sent to manual review",
    MRFCode.PARITY_FAILED: "Parity test failed",
    MRFCode.PARITY_EXHAUSTED: "Rebuild did not reach parity in 5 attempts; sent to manual review",
    MRFCode.SANDBOX_POLICY: "Generated code violates sandbox policy",
    MRFCode.DATA_QUALITY_FAILED: "Cleaned data failed quality checks; run refused",
    MRFCode.INVALID_STATE: "Operation not allowed in the current state",
    MRFCode.LLM_TIMEOUT: "LLM timed out after retries",
    MRFCode.LLM_RATE_LIMIT: "LLM rate limited after retries",
    MRFCode.LLM_BAD_OUTPUT: "LLM output still invalid after retries",
    MRFCode.INTERNAL: "Unexpected error",
}
