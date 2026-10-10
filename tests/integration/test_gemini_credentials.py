"""Offline credential routing; sentinel values are not actual credentials."""
import importlib.util
from pathlib import Path

import pytest

from agents.gemini_credentials import configured_api_key
from agents.returns.providers import select_provider
from agents.returns.request_store import Rejected


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for name in ("GEMINI_API_KEY_ENV", "GEMINI_API_KEY", "GEMINI_API_KEY_2",
                 "GEMINI_API_KEY_3", "GEMINI_MODEL", "GEMINI_FREE_TIER_CONFIRMED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "10")


@pytest.mark.parametrize("selector", [None, "GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"])
def test_explicit_key_reaches_receiving_and_returns(monkeypatch, selector):
    for index, name in enumerate(("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")):
        monkeypatch.setenv(name, f"offline-sentinel-{index}")
    if selector:
        monkeypatch.setenv("GEMINI_API_KEY_ENV", selector)
    expected = {None: "offline-sentinel-0", "GEMINI_API_KEY": "offline-sentinel-0",
                "GEMINI_API_KEY_2": "offline-sentinel-1", "GEMINI_API_KEY_3": "offline-sentinel-2"}[selector]
    assert configured_api_key() == expected
    # Execute the actual import-time Receiving config without mutating its singleton.
    path = Path(__file__).resolve().parents[2] / "agents/receiving/core/config.py"
    spec = importlib.util.spec_from_file_location("isolated_receiving_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CFG.gemini_api_key == expected
    with pytest.raises(Rejected, match="gemini_free_tier_confirmation_required"):
        select_provider({"name": "gemini"})
    monkeypatch.setenv("GEMINI_FREE_TIER_CONFIRMED", "1")
    provider, public = select_provider({"name": "gemini"})
    assert provider.provider.config.api_key == expected
    assert "offline-sentinel" not in str(public) + repr(provider.provider.config)


def test_missing_selected_key_never_falls_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-primary")
    monkeypatch.setenv("GEMINI_API_KEY_ENV", "GEMINI_API_KEY_2")
    assert configured_api_key() == ""
    with pytest.raises(Rejected, match="gemini_key_missing"):
        select_provider({"name": "gemini"})


def test_unknown_selector_rejected_without_echoing_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY_ENV", "SECRET-invalid-selector")
    with pytest.raises(ValueError, match="^invalid_gemini_key_selector$"):
        configured_api_key()
    with pytest.raises(Rejected, match="^gemini_invalid_configuration$"):
        select_provider({"name": "gemini"})
