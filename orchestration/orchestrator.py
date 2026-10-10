"""Starter orchestrator: a small workflow engine that owns workflow state.

Model:  Agent Output -> Evidence Record (stored, immutable) -> state transition -> next stage -> ... -> Final Outcome.
The orchestrator is the authoritative owner of workflow state. Agents return evidence; they never write state.

What it does for you (keep or replace, but keep the behaviour; it is tested):
  * start_workflow / advance / resume / apply_override
  * routes stages from a JSON flow (`when`), passes ALL previous evidence and overrides to each agent
  * validates every agent output (schema, stage, workflow, tenant, hash, consistency) before accepting it
  * retries transient failures, never retries refusals; every failure is RECORDED, never hidden or turned into success
  * fails open: a broken agent becomes a pending/error evidence record and the workflow continues (or blocks, by policy)
  * keeps an audit trail (`transitions`) and derives status + final outcome from the evidence (rollup.py)
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
import time
from pathlib import Path

from shared.utils.hashing import seal, verify
from shared.utils.log import get_logger
from shared.utils.records import build_output, error_obj, pending_output, utcnow
from shared.utils.schema import errors as schema_errors

from .clients import AgentRejected, AgentTimeout, AgentUnavailable, client_for, load_manifest
from .rollup import derive_final_outcome, derive_status, effective
from .store import EvidenceConflict, MemoryStore, StoreIntegrityError, identifier

ROOT = Path(__file__).resolve().parents[1]
logger = get_logger("orchestrator")
KINDS = {".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".heic": "image",
         ".mp4": "video", ".mov": "video", ".pdf": "document", ".csv": "document", ".json": "document", ".txt": "document"}


# ---------------------------------------------------------------- flow
def default_flow_path() -> Path:
    """The flow named in pod.json (Specialist Pods run flow.specialist.json), else flow.json."""
    pod = ROOT / "pod.json"
    rel = json.loads(pod.read_text()).get("flow") if pod.exists() else None
    return ROOT / (rel or "orchestration/flow.json")


def load_flow(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or default_flow_path()).read_text())


def flow_stages(flow: dict | None = None) -> list[str]:
    return list(dict.fromkeys(s["stage"] for s in (flow or load_flow())["steps"]))


def applies(step: dict, case: dict) -> tuple[bool, str]:
    for key, allowed in step.get("when", {}).items():
        if case.get(key) not in allowed:
            return False, f"{key}={case.get(key)!r} not in {allowed}"
    return True, ""


def discover_inputs(subject_id: str, stage: str) -> list[dict]:
    """Captures for one stage live in data/input/<subject_id>/<stage>/ (override the root with INPUT_DIR).

    Each file becomes a content-addressed input {ref, kind, sha256}. Refs are relative to the input root:
    never absolute (no local paths in evidence). Refs are contract identifiers, not filesystem paths:
    always forward slashes so evidence records are byte-identical across platforms.
    """
    root = Path(os.environ.get("INPUT_DIR", ROOT / "data" / "input"))
    folder = root / subject_id / stage
    if not folder.is_dir():
        return []
    return [{"ref": str(p.relative_to(root)).replace(os.sep, "/"), "kind": KINDS.get(p.suffix.lower(), "other"),
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(folder.iterdir()) if p.is_file() and not p.name.startswith(".")]


# ---------------------------------------------------------------- workflow state
def workflow_id_for(case: dict) -> str:
    return f"WF-{case['org_id']}-{case.get('subject_id') or case['unit_id']}"


def _log(wf: dict, event: str, stage: str | None = None, detail: str | None = None, **extra) -> None:
    wf["transitions"].append({"at": utcnow(), "event": event, "stage": stage, "detail": detail, **extra})
    logger.info(event, extra={"ctx": {"workflow_id": wf["workflow_id"], "org_id": wf["org_id"],
                                     "subject_id": wf["subject_id"], "stage": stage, "detail": detail}})


def _set_status(wf: dict, status: str, reason: str) -> None:
    if wf["status"] != status:
        _log(wf, "status_changed", detail=reason, from_status=wf["status"], to_status=status)
    wf["status"], wf["status_reason"] = status, reason
    wf["timestamps"]["updated_at"] = utcnow()


def new_workflow(case: dict, flow: dict) -> dict:
    """A PENDING workflow with every stage listed and routing already decided."""
    now = utcnow()
    subject_id = identifier(case.get("subject_id") or case["unit_id"])
    identifier(case["org_id"])
    stage_results = []
    for step in flow["steps"]:
        ok, why = applies(step, case)
        try:
            agent_id = load_manifest(step["stage"])["agent_id"]
        except FileNotFoundError:
            agent_id = None
        stage_results.append({
            "stage": step["stage"], "agent_id": agent_id, "state": "pending" if ok else "skipped",
            "skipped_reason": None if ok else why, "record_id": None, "evidence_status": None, "verdict": None,
            "outcome": None, "needs_human": None, "next_step_recommendation": None, "runs": 0, "attempts": 0,
            "started_at": None, "finished_at": None, "duration_ms": None, "error": None})
    wf = {"schema_version": "1.0", "workflow_id": workflow_id_for(case), "flow_id": flow["flow_id"],
          "org_id": case["org_id"], "subject_id": subject_id,
          "context": {k: v for k, v in case.items() if k not in ("org_id", "unit_id", "subject_id")},
          "status": "PENDING", "status_reason": "created", "current_stage": None, "previous_stage": None,
          "stage_results": stage_results, "evidence_references": [],
          "timestamps": {"created_at": now, "updated_at": now, "completed_at": None},
          "errors": [], "overrides": [], "halted": None, "final_outcome": None, "transitions": []}
    _log(wf, "workflow_created", detail=f"flow={flow['flow_id']}")
    for sr in stage_results:
        if sr["state"] == "skipped":
            _log(wf, "stage_skipped", sr["stage"], sr["skipped_reason"])
    return wf


def _record(wf, store, record_id):
    record = store.get_evidence(record_id)
    if record is None or not _same_scope(record, wf) or not verify(record):
        raise StoreIntegrityError("workflow evidence is missing, corrupt or out of scope")
    return record


def _same_scope(record, wf):
    return (record.get("workflow_id") == wf["workflow_id"]
            and record.get("subject", {}).get("org_id") == wf["org_id"]
            and record.get("subject", {}).get("subject_id") == wf["subject_id"])


def _previous_evidence(wf: dict, upto: int, store) -> list[dict]:
    out = []
    for sr in wf["stage_results"][:upto]:
        if sr["record_id"]:
            out.append(_record(wf, store, sr["record_id"]))
    return out


def _validate(out: dict, wf: dict, stage: str, request: dict) -> list[str]:
    """Why an agent output is not acceptable (empty list = accept)."""
    bad = schema_errors("agent-output", out)
    if bad:
        return bad[:3]
    ev = out["evidence"]
    if out["stage"] != stage or ev["stage"] != stage:
        return [f"stage mismatch: expected {stage!r}, got {out['stage']!r}/{ev['stage']!r}"]
    if out["workflow_id"] != wf["workflow_id"] or ev["workflow_id"] != wf["workflow_id"]:
        return ["workflow_id mismatch"]
    if (ev["subject"]["org_id"], ev["subject"]["subject_id"]) != (wf["org_id"], wf["subject_id"]):
        return ["TENANCY/SUBJECT MISMATCH: evidence is about a different org or subject than this workflow"]
    if not verify(ev):
        return ["content_hash does not match the evidence body"]
    if (out["verdict"], out["status"], out["agent_id"]) != (ev["decision"]["verdict"], ev["status"], ev["agent_id"]):
        return ["output and evidence disagree (verdict/status/agent_id)"]
    if out.get("error") != ev.get("error"):
        return ["output and evidence disagree about error"]
    if ev["status"] == "completed" and (ev.get("error") or out.get("error")):
        return ["completed output contains an unresolved error"]
    if ev["status"] != "completed" and (ev["decision"]["verdict"] != "UNCERTAIN" or not ev.get("error")):
        return ["failed output must preserve uncertainty and an error"]
    if ev["decision"]["verdict"] == "PASS" and any(c["verdict"] != "PASS" for c in ev["checks"]):
        return ["PASS contradicts check verdicts"]
    previous = {}
    for record in request["previous_evidence"]:
        if not _same_scope(record, wf) or not verify(record):
            return ["TENANCY/SUBJECT MISMATCH: invalid upstream context"]
        previous[record["record_id"]] = record
    refs = ev["upstream_refs"]
    if len(refs) != len(set(refs)) or any(r not in previous for r in refs):
        return ["upstream reference is not supplied current workflow evidence"]
    for rid in refs:
        if ev.get("client_id") and previous[rid].get("client_id") not in (None, ev["client_id"]):
            return ["TENANCY/SUBJECT MISMATCH: upstream client differs"]
    # Agents may resolve their own trusted registered inputs (Returns, CSV stubs).
    # Check references must still be declared in this record, or name supplied upstream records.
    inputs = {i["ref"]: i for i in ev.get("inputs", [])}
    if len(inputs) != len(ev.get("inputs", [])):
        return ["duplicate input reference"]
    supplied = {i["ref"]: i for i in request.get("inputs", [])}
    for ref, item in inputs.items():
        if (not ref or ref.startswith("/") or any(c in ref for c in ("\\", ":", "%"))
                or any(p in ("", ".", "..") for p in ref.split("/")) or any(ord(c) < 32 for c in ref)):
            return ["unsafe input reference"]
        if ref in supplied and supplied[ref].get("sha256") and item.get("sha256") != supplied[ref]["sha256"]:
            return ["input hash differs from supplied capture"]
    allowed = set(inputs) | set(refs)
    if any(ref not in allowed for check in ev["checks"] for ref in check.get("evidence_refs", [])):
        return ["check citation is not a declared input or supplied upstream record"]
    return []


def _run_stage(wf: dict, sr: dict, idx: int, opts: dict, store, client) -> dict | None:
    """Run one stage. Returns a halt reason, or None. Always leaves a stored evidence record behind."""
    stage = sr["stage"]
    previous_record_id = sr["record_id"]
    sr["runs"] += 1
    sr["attempts"], sr["started_at"], sr["error"] = 0, utcnow(), None
    wf["previous_stage"], wf["current_stage"] = wf["current_stage"], stage
    base = f"{wf['workflow_id']}:{stage}"
    request = {
        "schema_version": "1.0", "request_id": base if sr["runs"] == 1 else f"{base}:r{sr['runs']}",
        "workflow_id": wf["workflow_id"], "stage": stage,
        "subject": {"org_id": wf["org_id"], "subject_id": wf["subject_id"], "route": wf["context"].get("route", "unknown")},
        "inputs": (wf["context"]["upload_inputs"].get(stage, []) if "upload_inputs" in wf["context"]
                   else discover_inputs(wf["subject_id"], stage)),
        "previous_evidence": _previous_evidence(wf, idx, store),
        "context": {"overrides": wf["overrides"], "case": wf["context"]},
    }
    t0, out, err = time.monotonic(), None, None
    while sr["attempts"] <= int(opts["retries"]):
        sr["attempts"] += 1
        try:
            out = client.run(copy.deepcopy(request), float(opts["timeout_s"]))
            err = None
            break
        except AgentTimeout as exc:
            err = error_obj("agent_timeout", str(exc), retryable=True, stage=stage)
        except AgentUnavailable as exc:
            err = error_obj("agent_unavailable", str(exc), retryable=True, stage=stage)
        except AgentRejected as exc:
            err = error_obj("agent_rejected", str(exc), retryable=False, stage=stage)
            break
        except Exception as exc:  # an agent bug must not take the orchestrator down
            err = error_obj("agent_exception", f"{type(exc).__name__}: {exc}", retryable=False, stage=stage)
            break
        if sr["attempts"] <= int(opts["retries"]):
            _log(wf, "retry", stage, err["message"])
    if out is not None:
        bad = _validate(out, wf, stage, request)
        if bad:
            code = "tenant_mismatch" if bad[0].startswith("TENANCY") else "invalid_output"
            err = error_obj(code, "; ".join(bad), retryable=False, stage=stage)
            # Retain failure codes without persisting an invalid agent object or its raw diagnostics.
            if isinstance(out, dict):
                reported = [out.get("error")]
                if isinstance(out.get("evidence"), dict):
                    reported.append(out["evidence"].get("error"))
                codes = sorted({e["code"] for e in reported
                    if isinstance(e, dict) and isinstance(e.get("code"), str)
                    and len(e["code"]) <= 128 and all(c.isalnum() or c == "_" for c in e["code"])})
                if codes:
                    err["detail"] = "reported_error_codes=" + ",".join(codes)
            out = None
            _log(wf, "invalid_output", stage, err["message"])
    if out is None:
        if err is None:
            err = error_obj("invalid_output", "agent returned no output", retryable=False, stage=stage)
        out = pending_output(request, code=err["code"], message=err["message"], retryable=err["retryable"],
                             agent_id=sr["agent_id"])
        if err.get("detail"):
            out["evidence"]["error"]["detail"] = err["detail"]
            out = build_output(seal(out["evidence"]), next_step="review")
        _log(wf, "stage_degraded", stage, f"{err['code']}: recorded as {out['evidence']['status']}; flow policy decides what next")

    ev = out["evidence"]
    try:
        store.put_evidence(ev)
    except StoreIntegrityError:
        raise
    except EvidenceConflict:
        out = pending_output(request, code="invalid_output", message="agent reused an immutable evidence ID",
                             retryable=False, agent_id=sr["agent_id"])
        ev = out["evidence"]
        store.put_evidence(ev)
    if previous_record_id and previous_record_id != ev["record_id"]:
        _invalidate_dependents(wf, store, previous_record_id)
    if ev["record_id"] not in wf["evidence_references"]:
        wf["evidence_references"].append(ev["record_id"])
    agent_err = ev.get("error") or err
    if agent_err:
        wf["errors"].append({**agent_err, "stage": stage, "agent_id": ev["agent_id"], "at": agent_err.get("at") or utcnow()})
    sr.update({
        "agent_id": ev["agent_id"], "record_id": ev["record_id"], "evidence_status": ev["status"],
        "verdict": ev["decision"]["verdict"], "outcome": ev["decision"]["outcome"],
        "needs_human": effective(wf, ev)[1], "next_step_recommendation": out.get("next_step_recommendation"),
        "state": "completed" if ev["status"] == "completed" else "error", "error": agent_err,
        "finished_at": utcnow(), "duration_ms": int((time.monotonic() - t0) * 1000)})
    _log(wf, "stage_completed" if sr["state"] == "completed" else "stage_error", stage,
         f"{ev['decision']['outcome']} / {ev['decision']['verdict']}")
    if sr["state"] == "error" and opts["on_error"] == "block":
        return f"stage {stage} failed and on_error=block"
    # Block only when an UNCERTAIN result actually asks for a person. Recovery's SILENT ("no evidence, so no claim")
    # is UNCERTAIN with needs_human=false: there is nothing for a human to decide, so it must not halt the workflow.
    if ev["decision"]["verdict"] == "UNCERTAIN" and effective(wf, ev)[1] and opts["on_uncertain"] == "block":
        return f"stage {stage} is UNCERTAIN, needs a person, and on_uncertain=block"
    return None


def _finalize(wf: dict, store) -> dict:
    evidence = {rid: _record(wf, store, rid) for rid in wf["evidence_references"]}
    status, reason = derive_status(wf, evidence)
    _set_status(wf, status, reason)
    wf["final_outcome"] = derive_final_outcome(wf, evidence, status)
    wf["timestamps"]["completed_at"] = utcnow() if status == "COMPLETED" else None
    store.save_workflow(wf)
    return wf


# ---------------------------------------------------------------- public API
def advance(wf: dict, flow: dict, store, clients: dict | None = None) -> dict:
    store = store.for_org(wf["org_id"])
    with store.transaction():
        return _advance(wf, flow, store, clients)


def _advance(wf: dict, flow: dict, store, clients: dict | None = None) -> dict:
    """Run every stage that has not completed (errored stages are retried), in order, until done or halted."""
    defaults = {"timeout_s": 30, "retries": 1, "on_uncertain": "continue", "on_error": "continue", **flow.get("defaults", {})}
    steps = {s["stage"]: s for s in flow["steps"]}
    wf["halted"] = None
    _set_status(wf, "IN_PROGRESS", "advancing")
    store.save_workflow(wf)
    for idx, sr in enumerate(wf["stage_results"]):
        if sr["state"] in ("completed", "skipped"):
            continue
        step = steps[sr["stage"]]
        opts = {**defaults, **{k: v for k, v in step.items() if k not in ("stage", "when")}}
        client = (clients or {}).get(sr["stage"]) or client_for(sr["stage"])
        halt = _run_stage(wf, sr, idx, opts, store, client)
        store.save_workflow(wf)
        if halt:
            wf["halted"] = {"stage": sr["stage"], "reason": halt, "at": utcnow()}
            _log(wf, "halted", sr["stage"], halt)
            break
    return _finalize(wf, store)


def run_workflow(case: dict, flow: dict | None = None, store=None, clients: dict | None = None) -> dict:
    """Start (or continue) the workflow for a case. Idempotent: an existing workflow is advanced, not duplicated."""
    flow, store = flow or load_flow(), store or MemoryStore()
    store = store.for_org(case["org_id"])
    with store.transaction():
        wf = store.load_workflow(workflow_id_for(case)) or new_workflow(case, flow)
        if wf["subject_id"] != (case.get("subject_id") or case["unit_id"]):
            raise ValueError("workflow identity collision")
        return advance(wf, flow, store, clients)


def resume(workflow_id: str, flow: dict | None = None, store=None, clients: dict | None = None) -> dict:
    """Continue after a halt, a person's decision, or a failure (errored stages are retried)."""
    flow = flow or load_flow()
    with store.transaction():
        wf = store.load_workflow(workflow_id)
        if wf is None:
            raise KeyError(workflow_id)
        _log(wf, "resumed", detail=f"from status {wf['status']}")
        return advance(wf, flow, store, clients)


def apply_override(workflow_id: str, store, *, record_id: str, new_verdict: str, actor: str, reason: str,
                   new_outcome: str | None = None) -> dict:
    """A person (or rule) changes the effective decision of a record. Nothing is deleted or rewritten:
    the new entry references the evidence and the previous effective decision, and the state is re-derived."""
    with store.transaction():
        return _apply_override(workflow_id, store, record_id=record_id, new_verdict=new_verdict,
                               actor=actor, reason=reason, new_outcome=new_outcome)


def _apply_override(workflow_id, store, *, record_id, new_verdict, actor, reason, new_outcome):
    identifier(record_id)
    if not isinstance(new_verdict, str) or new_verdict not in ("PASS", "FAIL", "UNCERTAIN"):
        raise ValueError("invalid override verdict")
    if new_outcome is not None and (not isinstance(new_outcome, str) or not new_outcome.strip()):
        raise ValueError("invalid override outcome")
    if getattr(store, "actor", None) is not None and actor != store.actor:
        raise PermissionError("override actor differs from authorized actor")
    if (not isinstance(actor, str) or not isinstance(reason, str) or not actor.strip() or not reason.strip()
            or any(ord(c) < 32 for c in actor)):
        raise ValueError("an override needs an actor and a reason")
    wf = store.load_workflow(workflow_id)
    if wf is None:
        raise KeyError(workflow_id)
    if record_id not in {sr["record_id"] for sr in wf["stage_results"] if sr["record_id"]}:
        raise ValueError(f"{record_id} is not evidence in {workflow_id}")
    store = store.for_org(wf["org_id"])
    record = _record(wf, store, record_id)
    previous_verdict, _ = effective(wf, record)
    earlier = [o for o in wf["overrides"] if o["supersedes"]["record_id"] == record_id]
    entry = {"override_id": f"OVR-{len(wf['overrides']) + 1:03d}",
             "supersedes": {"record_id": record_id, "override_id": earlier[-1]["override_id"] if earlier else None},
             "target": "decision", "actor": actor, "at": utcnow(), "reason": reason,
             "original_verdict": record["decision"]["verdict"], "previous_verdict": previous_verdict,
             "new_verdict": new_verdict, "new_outcome": new_outcome}
    wf["overrides"].append(entry)
    _log(wf, "override", record["stage"], f"{entry['override_id']} by {actor}: {previous_verdict} -> {new_verdict}")
    if new_verdict != previous_verdict or new_outcome is not None:
        _invalidate_dependents(wf, store, record_id)
    return _finalize(wf, store)


def _invalidate_dependents(wf, store, record_id):
    changed = {record_id}
    for sr in wf["stage_results"]:
        rid = sr["record_id"]
        if not rid or rid == record_id or sr["state"] != "completed":
            continue
        record = _record(wf, store, rid)
        if not changed.intersection(record["upstream_refs"]):
            continue
        changed.add(rid)
        sr.update(state="pending", record_id=None, evidence_status=None, verdict=None, outcome=None,
                  needs_human=True, error=None, next_step_recommendation=None, finished_at=None)
        _log(wf, "stage_invalidated", sr["stage"], "upstream evidence changed; reassessment required",
             record_id=rid, upstream_record_id=record_id)


def bundle(wf: dict, store) -> dict:
    """The workflow plus every evidence record it references: a self-contained, reviewable export."""
    store = store.for_org(wf["org_id"])
    return {"workflow": wf, "evidence": {rid: _record(wf, store, rid) for rid in wf["evidence_references"]}}