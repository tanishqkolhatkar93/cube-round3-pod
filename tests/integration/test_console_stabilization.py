"""Regression checks for console configuration and malformed workflow requests."""
import pytest
from fastapi.testclient import TestClient
from orchestration import api


def test_invalid_orchestration_mode_does_not_select_http(monkeypatch):
    from orchestration.clients import client_for
    monkeypatch.setenv("ORCH_MODE", "inprocc")
    with pytest.raises(ValueError, match="invalid orchestration mode"):
        client_for("receiving")


@pytest.fixture
def console(monkeypatch):
    monkeypatch.setenv("ORG_ALPHA_TOKEN", "local-test-only")
    monkeypatch.setattr(api, "_DEMO_PRINCIPAL", None)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        assert client.post("/auth/session", json={"org_id": "org_demo_alpha", "token": "local-test-only"}).status_code == 200
        yield client


@pytest.mark.parametrize("fields", [{"route": []}, {"route": "invalid"}, {"returned": "false"}, {"returned": 1}])
def test_bad_routing_facts_rejected_before_execution(console, monkeypatch, fields):
    calls = []
    monkeypatch.setattr(api, "run_workflow", lambda *args: calls.append(args) or {})
    result = console.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", **fields})
    assert result.status_code == 422
    assert calls == []


def test_health_reports_actual_missing_configuration(console, monkeypatch):
    monkeypatch.setenv("ORCH_MODE", "inproc")
    monkeypatch.delenv("PREP_CONFIG", raising=False)
    result = console.get("/health")
    assert result.status_code == 200
    assert result.json()["status"] == "degraded"
    assert result.json()["agents"]["prep"]["status"] == "degraded"


def test_health_isolates_load_failure_and_sanitizes_diagnostics(console, monkeypatch):
    original = api.client_for
    def broken(stage):
        if stage == "pack":
            raise RuntimeError("secret must not be returned")
        return original(stage)
    monkeypatch.setattr(api, "client_for", broken)
    result = console.get("/health")
    assert result.status_code == 200
    assert result.json()["agents"]["pack"]["status"] == "down"
    assert len(result.json()["agents"]) == 5
    assert "secret" not in result.text
