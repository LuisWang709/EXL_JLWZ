"""Runtime settings (env / .env) + pipeline policy (config/pipeline.yaml)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "pipeline.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MRF_", extra="ignore")

    env: Literal["local", "dev", "demo"] = "local"
    api_key: str = "change-me"
    log_level: str = "INFO"
    data_dir: Path = Path("./var")

    storage_backend: Literal["sqlite", "cosmos"] = "sqlite"
    sqlite_path: Path = Path("./var/mrf.sqlite")
    checkpoint_path: Path = Path("./var/checkpoints.sqlite")
    cosmos_endpoint: str = ""
    cosmos_database: str = "mrf"
    blob_account_url: str = ""

    worker_concurrency: int = 2

    llm_provider: Literal["mock", "azure_openai", "openai", "github_models"] = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_reviewer_model: str = ""

    mcp_url: str = "http://localhost:8000/mcp/"
    tool_transport: Literal["inprocess", "http"] = "inprocess"

    max_upload_mb: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    """Thresholds shared across modules. Read-only; never hard-code these numbers elsewhere."""
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data
