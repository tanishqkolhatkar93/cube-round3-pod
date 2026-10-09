"""P0 boundary regressions: real stores/API/orchestrator, offline scripted judgments."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from orchestration.clients import AgentTimeout, AgentUnavailable, HttpClient
from orchestration.orchestrator import (_validate, apply_override, bundle, new_workflow,
                                       resume, run_workflow)
from orchestration.store import EvidenceConflict, FileStore, MemoryStore, StoreIntegrityError
from shared.utils.hashing import seal, verify
from shared.utils.records import build_output, build_record, check, error_obj
from shared.utils.schema import errors
from shared.utils.stubs import effective_verdict

CASE = {"org_id": "org_b", "unit_id": "UNIT-audit", "route": "mfn", "returned": False}
FLOW = {"flow_id": "audit", "steps": [{"stage": "receiving"}]}


class Judgment:
    def __init__(self, verdict="PASS", needs_human=None, mutate=None):
        self.verdict, self.needs_human, self.mutate = verdict, needs_human, mutate
        self.calls, self.outputs = 0, []

    def run(self, request, timeout_s):
        self.calls += 1
        prefix = {"receiving": "RCV", "prep": "PRP", "pack": "PCK", "returns": "RTN", "recovery": "RCY"}[request["stage"]]
        record = build_record(request, agent_id=request["stage"] + "-audit@1",
            record_id=prefix + "-" + hashlib.sha256(request["request_id"].encode()).hexdigest(),
            captured_at="2026-01-01T00:00:00Z", checks=[check("identity", self.verdict, None)],
            outcome="review" if self.verdict == "UNCERTAIN" else "ok", reason="offline judgment",
            model={"name": "rules", "version": "audit"}, needs_human=self.needs_human)
        if self.mutate:
            self.mutate(record, request)
        out = build_output(seal(record))
        self.outputs.append(copy.deepcopy(out))
        return out


@pytest.fixture(params=["memory", "file"])
def backend(request, tmp_path):
    return MemoryStore() if request.param == "memory" else FileStore(tmp_path / "store")


def seeded(store):
    wf = run_workflow(CASE, FLOW, store, {"receiving": Judgment()})
    return wf, wf["stage_results"][0]["record_id"]


def test_scoped_store_cannot_read_mutate_resume_or_override_another_org(backend):
    wf, rid = seeded(backend)
    a = backend.for_org("org_a", actor="alice")
    assert a.load_workflow(wf["workflow_id"]) is None
    assert a.get_evidence(rid) is None
    before = backend.load_workflow(wf["workflow_id"])
    with pytest.raises(KeyError):
        resume(wf["workflow_id"], FLOW, a, {"receiving": Judgment()})
    with pytest.raises(KeyError):
        apply_override(wf["workflow_id"], a, record_id=rid, new_verdict="FAIL", actor="alice", reason="x")
    with pytest.raises(PermissionError):
        a.save_workflow(wf)
    with pytest.raises(PermissionError):
        a.put_evidence(backend.get_evidence(rid))
    with pytest.raises(PermissionError):
        a.for_org("org_b")
    assert backend.load_workflow(wf["workflow_id"]) == before


@pytest.fixture
def api_setup(monkeypatch, tmp_path):
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "api-state"))
    api = importlib.import_module("orchestration.api")
    store = MemoryStore()
    monkeypatch.setattr(api, "STORE", store)
    wf, rid = seeded(store)
    return api, store, wf, rid


def client_for_identity(api, org=None, actor="alice"):
    async def authenticated(scope, receive, send):
        if org:
            scope = {**scope, "orchestration.principal": api.Principal(org, actor)}
        await api.app(scope, receive, send)
    return TestClient(authenticated)


@pytest.mark.parametrize("method,suffix", [("get", ""), ("get", "/evidence"), ("post", "/resume"), ("post", "/overrides")])
def test_api_denies_foreign_workflow_before_access_or_mutation(api_setup, method, suffix):
    api, store, wf, rid = api_setup
    before = copy.deepcopy(store.workflows)
    client = client_for_identity(api, "org_a")
    response = client.request(method, "/workflows/" + wf["workflow_id"] + suffix,
                              json={"record_id": rid, "new_verdict": "FAIL", "actor": "alice", "reason": "x"})
    assert response.status_code == 404
    assert "org_b" not in response.text and rid not in response.text
    assert store.workflows == before


def test_api_fails_closed_and_does_not_trust_tenant_headers(api_setup):
    api, store, wf, rid = api_setup
    client = client_for_identity(api)
    assert client.get("/workflows/" + wf["workflow_id"], headers={"X-Org-ID": "org_b", "X-Actor": "alice"}).status_code == 401
    assert client.post("/workflows", json=CASE).status_code == 401
    assert client_for_identity(api, "org_a").post("/workflows", json=CASE).status_code == 403


def test_api_authorized_reads_and_actor_bound_override(api_setup):
    api, store, wf, rid = api_setup
    client = client_for_identity(api, "org_b")
    url = "/workflows/" + wf["workflow_id"]
    assert client.get(url).status_code == 200
    assert client.get(url + "/evidence").json()["evidence"][rid]["subject"]["org_id"] == "org_b"
    assert client.post(url + "/overrides", json={"record_id": rid, "new_verdict": "FAIL", "actor": "mallory", "reason": "x"}).status_code == 403
    assert client.post(url + "/overrides", json={"record_id": rid, "new_verdict": "BANANA", "reason": "x"}).status_code == 422
    assert store.load_workflow(wf["workflow_id"])["overrides"] == []
    response = client.post(url + "/overrides", json={"record_id": rid, "new_verdict": "FAIL", "reason": "reviewed"})
    assert response.status_code == 200
    assert response.json()["overrides"][0]["actor"] == "alice"


@pytest.mark.parametrize("kind", ["nonexistent_check", "nonexistent_upstream", "foreign_existing", "hidden_upstream", "wrong_hash", "unsafe_input"])
def test_invalid_reference_membership_is_rejected_without_rewriting_agent_output(kind):
    store = MemoryStore()
    other, other_id = seeded(store)
    case = {**CASE, "org_id": "org_a"}
    def mutate(rec, req):
        if kind == "nonexistent_check":
            rec["checks"][0]["evidence_refs"] = ["does-not-exist.jpg"]
        elif kind in ("nonexistent_upstream", "foreign_existing"):
            rec["upstream_refs"] = [other_id if kind == "foreign_existing" else "RCV-missing"]
        elif kind == "hidden_upstream":
            rec["checks"][0]["evidence_refs"] = [other_id]
        elif kind == "wrong_hash":
            rec["inputs"] = [{"ref": "image.jpg", "kind": "image", "sha256": "b" * 64}]
        else:
            rec["inputs"] = [{"ref": "../escape.jpg", "kind": "image"}]
    agent = Judgment(mutate=mutate)
    if kind == "wrong_hash":
        wf = new_workflow(case, FLOW)
        req = {"schema_version": "1.0", "request_id": "x", "workflow_id": wf["workflow_id"], "stage": "receiving",
               "subject": {"org_id": "org_a", "subject_id": case["unit_id"]}, "previous_evidence": [],
               "inputs": [{"ref": "image.jpg", "sha256": "a" * 64}]}
        out = agent.run(req, 1)
        assert _validate(out, wf, "receiving", req)
        return
    wf = run_workflow(case, FLOW, store, {"receiving": agent})
    assert wf["status"] == "FAILED" and wf["errors"][-1]["code"] == "invalid_output"
    assert verify(agent.outputs[0]["evidence"])
    assert store.get_evidence(agent.outputs[0]["evidence"]["record_id"]) is None
    degraded = store.get_evidence(wf["stage_results"][0]["record_id"])
    assert degraded["decision"]["verdict"] == "UNCERTAIN" and verify(degraded)


@pytest.mark.parametrize("field,value", [("org_id", "foreign"), ("subject_id", "OTHER"), ("workflow_id", "OTHER")])
def test_even_resealed_upstream_context_must_have_current_scope(field, value):
    store = MemoryStore(); wf, rid = seeded(store)
    prior = store.get_evidence(rid)
    if field == "workflow_id":
        prior[field] = value
    else:
        prior["subject"][field] = value
    req = {"schema_version": "1.0", "request_id": "x", "workflow_id": wf["workflow_id"], "stage": "recovery",
           "subject": {"org_id": wf["org_id"], "subject_id": wf["subject_id"]}, "previous_evidence": [seal(prior)]}
    out = Judgment().run(req, 1)
    assert _validate(out, wf, "recovery", req)[0].startswith("TENANCY")


def test_agent_cannot_mutate_validation_context():
    def mutate(rec, req):
        rec["upstream_refs"] = ["RCV-forged"]
        req["previous_evidence"].append({**rec, "record_id": "RCV-forged"})
    wf = run_workflow(CASE, FLOW, MemoryStore(), {"receiving": Judgment(mutate=mutate)})
    assert wf["status"] == "FAILED"


@pytest.mark.parametrize("code", ["provider_failure", "agent_exception", "agent_timeout", "agent_unavailable"])
def test_completed_pass_with_failure_is_not_success_and_preserves_code(code):
    def mutate(rec, req):
        rec["error"] = error_obj(code, "controlled offline failure", retryable=False)
    store = MemoryStore()
    wf = run_workflow(CASE, FLOW, store, {"receiving": Judgment(mutate=mutate)})
    assert (wf["status"], wf["final_outcome"]["outcome"]) == ("FAILED", "INCOMPLETE")
    rec = store.get_evidence(wf["stage_results"][0]["record_id"])
    assert rec["error"]["detail"] == "reported_error_codes=" + code
    assert not errors("evidence", rec) and not errors("workflow-state", wf)
    assert rec["status"] == "error" and verify(rec)


@pytest.mark.parametrize("policy", ["continue", "block"])
def test_nonrecovery_uncertainty_cannot_suppress_review(policy):
    wf = run_workflow(CASE, {**FLOW, "defaults": {"on_uncertain": policy}}, MemoryStore(),
                      {"receiving": Judgment("UNCERTAIN", needs_human=False)})
    assert (wf["status"], wf["final_outcome"]["outcome"]) == ("BLOCKED", "NEEDS_REVIEW")
    assert wf["stage_results"][0]["needs_human"] is True
    assert bool(wf["halted"]) == (policy == "block")


def test_recovery_silent_exception_is_preserved():
    wf = run_workflow(CASE, {"flow_id": "silent", "steps": [{"stage": "recovery"}]}, MemoryStore(),
                      {"recovery": Judgment("UNCERTAIN", needs_human=False)})
    assert wf["status"] == "COMPLETED" and wf["final_outcome"]["outcome"] == "CLEAN"
    assert wf["final_outcome"]["effective_verdicts"]["recovery"] == "UNCERTAIN"


@pytest.mark.parametrize("changes", [{"new_verdict": "BANANA"}, {"new_verdict": []}, {"actor": None},
                                     {"actor": " "}, {"actor": "bad\nactor"}, {"reason": 1},
                                     {"reason": " "}, {"new_outcome": {}}, {"record_id": []}])
def test_invalid_override_never_mutates_store(backend, changes):
    wf, rid = seeded(backend)
    args = {"record_id": rid, "new_verdict": "PASS", "actor": "alice", "reason": "review"}
    args.update(changes)
    with pytest.raises(ValueError):
        apply_override(wf["workflow_id"], backend, **args)
    assert backend.load_workflow(wf["workflow_id"]) == wf


def test_scoped_override_cannot_impersonate_another_actor(backend):
    wf, rid = seeded(backend)
    with pytest.raises(PermissionError):
        apply_override(wf["workflow_id"], backend.for_org("org_b", actor="alice"), record_id=rid,
                       new_verdict="FAIL", actor="mallory", reason="x")
    assert backend.load_workflow(wf["workflow_id"]) == wf


def test_upstream_override_reassesses_claim_and_preserves_unrelated_stage_and_history(backend):
    # Same Prep PASS -> claim -> override FAIL counterexample, using the actual Recovery position rule.
    from agents.recovery.rules import _deterministic_position
    from shared.utils.stubs import effective_verdict
    def independent(rec, req):
        rec["upstream_refs"] = []
    def recover(rec, req):
        evidence = [{**r, "effective_verdict": effective_verdict(req, r)}
                    for r in req["previous_evidence"] if r["status"] == "completed"]
        pos, why, ids = _deterministic_position({"charge_type": "inbound_defect_fee", "amount_usd": 2}, evidence)
        verdict = "FAIL" if pos == "CONTRADICTS" else "PASS"
        rec["checks"] = [check("charge", verdict, None, evidence_refs=ids)]
        rec["decision"].update(verdict=verdict, reason=why)
        rec["payload"] = {"claimable_usd": 2 if verdict == "FAIL" else 0}
        rec["upstream_refs"] = ids
    agents = {"prep": Judgment(), "pack": Judgment(mutate=independent), "recovery": Judgment(mutate=recover)}
    flow = {"flow_id": "dependency-audit", "steps": [{"stage": s} for s in agents]}
    wf = run_workflow(CASE, flow, backend, agents)
    prep, pack, recovery = [s["record_id"] for s in wf["stage_results"]]
    original = bundle(wf, backend)["evidence"]
    assert wf["final_outcome"]["claimable_usd"] == 2
    wf = apply_override(wf["workflow_id"], backend, record_id=prep, new_verdict="FAIL", actor="alice", reason="reviewed")
    assert wf["final_outcome"]["outcome"] != "CLAIM_RECOMMENDED"
    assert wf["final_outcome"]["claimable_usd"] is None
    assert recovery not in wf["final_outcome"]["contributing_records"]
    assert wf["stage_results"][1]["record_id"] == pack and wf["stage_results"][1]["state"] == "completed"
    assert wf["stage_results"][2]["state"] == "pending"
    assert wf["overrides"][0]["supersedes"]["record_id"] == prep
    wf = resume(wf["workflow_id"], flow, backend, agents)
    assert agents["pack"].calls == agents["prep"].calls == 1 and agents["recovery"].calls == 2
    assert wf["final_outcome"]["outcome"] == "EXCEPTION" and not errors("workflow-state", wf)
    assert wf["stage_results"][2]["record_id"] != recovery
    for rid, record in original.items():
        assert backend.get_evidence(rid) == record and rid in wf["evidence_references"]


def test_transitive_dependents_are_requeued_but_noop_override_is_not():
    store = MemoryStore(); agents = {s: Judgment() for s in ("receiving", "pack", "recovery")}
    flow = {"flow_id": "transitive", "steps": [{"stage": s} for s in agents]}
    wf = run_workflow(CASE, flow, store, agents); rid = wf["stage_results"][0]["record_id"]
    same = apply_override(wf["workflow_id"], store, record_id=rid, new_verdict="PASS", actor="alice", reason="confirmed")
    assert all(s["state"] == "completed" for s in same["stage_results"])
    changed = apply_override(wf["workflow_id"], store, record_id=rid, new_verdict="FAIL", actor="alice", reason="corrected")
    assert [s["state"] for s in changed["stage_results"]] == ["completed", "pending", "pending"]
    assert all(store.get_evidence(r) for r in wf["evidence_references"])


def test_store_defensive_copies_and_integrity(backend):
    wf, rid = seeded(backend)
    rec = backend.get_evidence(rid); rec["decision"]["verdict"] = "FAIL"
    assert backend.get_evidence(rid)["decision"]["verdict"] == "PASS"
    with pytest.raises(StoreIntegrityError):
        backend.put_evidence(rec)
    if isinstance(backend, FileStore):
        (backend.root / "evidence" / (rid + ".json")).write_text(json.dumps(rec))
    else:
        backend.evidence[rid] = rec
    with pytest.raises(StoreIntegrityError):
        backend.get_evidence(rid)
    with pytest.raises(StoreIntegrityError):
        bundle(wf, backend)


@pytest.mark.parametrize("key", ["../outside", "C:/outside", "a/b", "a\\b", "", ".."])
def test_store_rejects_unsafe_ids(backend, key):
    with pytest.raises(ValueError):
        backend.load_workflow(key)
    with pytest.raises(ValueError):
        backend.get_evidence(key)


def test_file_store_concurrent_writers_never_overwrite_evidence(tmp_path):
    root = tmp_path / "shared"; store = FileStore(root); wf, rid = seeded(store)
    original = store.get_evidence(rid)
    changed = copy.deepcopy(original); changed["decision"]["reason"] = "changed"; changed = seal(changed)
    def attempt(record):
        try:
            FileStore(root).put_evidence(record)
            return "ok"
        except EvidenceConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, [original, changed] * 4))
    assert results.count("ok") == results.count("conflict") == 4
    assert store.get_evidence(rid) == original
    assert not list(root.rglob("*.tmp"))


def test_file_store_process_race_has_one_winner(tmp_path):
    root = tmp_path / "race"; root.mkdir()
    request = {"request_id": "race", "workflow_id": "WF-race", "stage": "receiving",
               "subject": {"org_id": "org_b", "subject_id": "unit"}, "previous_evidence": []}
    a = Judgment().run(request, 1)["evidence"]
    b = copy.deepcopy(a); b["decision"]["reason"] = "different"; b = seal(b)
    script = "from orchestration.store import FileStore,EvidenceConflict; import sys,json; s=FileStore(sys.argv[1]); r=json.load(sys.stdin)\ntry: s.put_evidence(r); print('ok')\nexcept EvidenceConflict: print('conflict')"
    processes = [subprocess.Popen([sys.executable, "-B", "-c", script, str(root)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    for process, record in zip(processes, (a, b)):
        process.stdin.write(json.dumps(record))
        process.stdin.close()
        process.stdin = None
    results = [process.communicate(timeout=20) for process in processes]
    assert sorted(out.strip() for out, err in results) == ["conflict", "ok"], results
    assert all(p.returncode == 0 for p in processes)
    assert FileStore(root).get_evidence(a["record_id"]) in (a, b)


@pytest.mark.parametrize("error,expected", [("ConnectTimeout", AgentUnavailable), ("ConnectError", AgentUnavailable),
                                            ("ReadTimeout", AgentTimeout), ("WriteTimeout", AgentTimeout), ("PoolTimeout", AgentTimeout)])
def test_windows_timeout_classification_is_unchanged(monkeypatch, error, expected):
    import httpx
    def fail(*a, **k):
        raise getattr(httpx, error)("offline")
    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(expected) as exc:
        HttpClient({"stage": "receiving", "url": "http://127.0.0.1:1"}).run({}, 1)
    assert type(exc.value) is expected
