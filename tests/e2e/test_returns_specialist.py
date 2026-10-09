from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import MemoryStore
from shared.utils.schema import errors
from tests.conftest import ROOT


def test_specialist_returns_without_prep(cases):
    case = next(c for c in cases if c["returned"] and c["route"] == "fba")
    store = MemoryStore()
    workflow = run_workflow(case, load_flow(ROOT / "orchestration/flow.specialist.json"), store=store)
    assert not errors("workflow-state", workflow)
    assert "prep" not in [s["stage"] for s in workflow["stage_results"]]
    stage = next(s for s in workflow["stage_results"] if s["stage"] == "returns")
    evidence = store.get_evidence(stage["record_id"])
    assert evidence["agent_id"] == "returns-manager@1"
    assert evidence["status"] == "pending" and evidence["error"]["code"] == "missing_image"
    assert evidence["payload"]["assessment"]["disposition"]["decision"] == "pending_review"
