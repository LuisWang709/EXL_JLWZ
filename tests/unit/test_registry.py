"""Deployed environments must not silently substitute test agents."""

from __future__ import annotations

import pytest

from mrf.config import get_settings
from mrf.core import MRFError
from mrf.orchestrator import registry


@pytest.mark.parametrize("env", ["dev", "demo"])
def test_deployment_rejects_forced_stubs(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("MRF_ENV", env)
    monkeypatch.setenv("MRF_STUBS", "all")
    get_settings.cache_clear()
    with pytest.raises(MRFError, match="MRF_STUBS"):
        registry.Registry.discover()


def test_missing_agent_only_falls_back_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry.IMPLEMENTATIONS, "classifier", "mrf.missing_agent:Missing")
    assert registry.Registry.discover().describe()["classifier"] == "StubClassifier"
    monkeypatch.setenv("MRF_ENV", "dev")
    get_settings.cache_clear()
    with pytest.raises(MRFError, match="required agent"):
        registry.Registry.discover()


def test_missing_class_rejected_in_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRF_ENV", "demo")
    monkeypatch.setitem(registry.IMPLEMENTATIONS, "classifier", "mrf.agents.classify.agent:Missing")
    get_settings.cache_clear()
    with pytest.raises(MRFError, match="required agent"):
        registry.Registry.discover()
