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


def test_real_implementations_are_explicit() -> None:
    assert not any(name.startswith("Stub") for name in registry.Registry.discover().describe().values())


def test_unknown_stub_slot_is_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRF_STUBS", "runer")
    with pytest.raises(MRFError, match="unknown stub slots"):
        registry.Registry.discover()
