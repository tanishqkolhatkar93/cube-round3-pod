"""The opt-in router preserves real authorization and durable conflicts."""
import copy
import sqlite3

from fastapi.testclient import TestClient
import pytest

from agents.prep import app
from agents.prep.common import Rejected
from agents.prep.tests.integration_support import prep_synthetic


def sample_request(org="org_demo_alpha", unit="UNIT-0014"):
    workflow = f"WF-{org}-{unit}"
    return {"schema_version": "1.0", "request_id": workflow + ":prep",
            "workflow_id": workflow, "stage": "prep",
            "subject": {"org_id": org, "subject_id": unit, "route": "fba"},
            "inputs": [], "previous_evidence": [], "context": {}}


def test_fixture_routes_both_orgs_and_preserves_real_decisions(prep_synthetic):
    for org, unit, verdict in [("org_demo_alpha", "UNIT-0014", "PASS"),
                               ("org_demo_bravo", "UNIT-0012", "UNCERTAIN")]:
        out = app.handle(sample_request(org, unit))
        assert out["status"] == "completed" and out["verdict"] == verdict
        assert out["evidence"]["subject"]["org_id"] == org
        assert out["evidence"]["inputs"] and out["evidence"]["checks"]
    assert sum(prep_synthetic.calls.values()) == 2


def test_fixture_does_not_authorize_foreign_subject(prep_synthetic):
    with pytest.raises(Rejected, match="source_not_found") as failure:
        app.handle(sample_request("org_demo_bravo", "UNIT-0014"))
    assert failure.value.status == 404
    assert not prep_synthetic.calls


def test_fixture_replays_and_rejects_changed_content_before_inference(prep_synthetic):
    request = sample_request()
    first = app.handle(request)
    assert app.handle(request) == first
    changed = copy.deepcopy(request)
    changed["context"]["changed"] = True
    with pytest.raises(Rejected, match="request_content_conflict"):
        app.handle(changed)
    assert sum(prep_synthetic.calls.values()) == 1
    ledgers = list(prep_synthetic.root.rglob("prep-requests.sqlite3"))
    assert len(ledgers) == 1
    with sqlite3.connect(ledgers[0]) as db:
        assert db.execute("SELECT state FROM requests").fetchall() == [("complete",)]
    prep_synthetic.fresh_state("independent_execution")
    assert app.handle(changed)["verdict"] == "PASS"
    assert sum(prep_synthetic.calls.values()) == 2
    assert len(list(prep_synthetic.root.rglob("prep-requests.sqlite3"))) == 2


def test_fixture_uses_real_config_health_and_http_authorization(prep_synthetic, monkeypatch):
    with TestClient(app.app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert not prep_synthetic.calls
        response = client.post("/run", json=sample_request())
        assert response.status_code == 200 and response.json()["verdict"] == "PASS"
        assert client.post("/run", json=sample_request("org_demo_bravo")).status_code == 404
        monkeypatch.delenv("PREP_CONFIG")
        assert client.get("/health").json()["status"] == "degraded"
        assert client.post("/run", json=sample_request()).status_code == 503
