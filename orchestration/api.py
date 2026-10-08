"""Optional HTTP front door for the orchestrator (useful for a deployed demo).

  uvicorn orchestration.api:app --port 8100
  POST /workflows                 {"org_id": "org_demo_alpha", "unit_id": "UNIT-0002"}   -> Workflow State (runs it)
  GET  /workflows/{id}            -> Workflow State
  GET  /workflows/{id}/evidence   -> the workflow plus all its evidence records
  POST /workflows/{id}/resume     -> continue after a halt / decision / failure
  POST /workflows/{id}/overrides  {"record_id": "...", "new_verdict": "PASS", "actor": "...", "reason": "..."}
  GET  /health                    -> orchestrator and every agent in the flow
  GET  /                          -> same-origin operations console
Resource routes require a Principal in ASGI scope from trusted authentication middleware.
No client header or body value establishes that identity. Unconfigured access fails closed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from shared.utils import sample_data

from .clients import HttpClient, client_for, load_manifest
from .orchestrator import apply_override, bundle, default_flow_path, flow_stages, load_flow, resume, run_workflow
from .store import EvidenceConflict, FileStore, StoreIntegrityError, identifier

app = FastAPI(title="CUBE Round 3 orchestrator")
FLOW = os.environ.get("ORCH_FLOW") or default_flow_path()
STORE = FileStore()
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


@app.get("/health")
def health() -> dict:
    agents = {}
    for stage in flow_stages(load_flow(FLOW)):
        client = client_for(stage)
        try:
            agents[stage] = client.health() if isinstance(client, HttpClient) else {"status": "ok", "mode": "inproc"}
        except Exception as exc:
            agents[stage] = {"status": "down", "error": str(exc)[:200], "owner": load_manifest(stage)["owner"]}
    ok = all(a["status"] == "ok" for a in agents.values())
    return {"status": "ok" if ok else "degraded", "flow": load_flow(FLOW)["flow_id"], "agents": agents}


@dataclass(frozen=True)
class Principal:
    org_id: str
    actor: str

    def __post_init__(self):
        identifier(self.org_id)
        if not isinstance(self.actor, str) or not self.actor.strip() or any(ord(c) < 32 for c in self.actor):
            raise ValueError("invalid authenticated actor")


def require_principal(request: Request) -> Principal:
    # Set ONLY by trusted server-side middleware after authenticating the caller.
    principal = request.scope.get("orchestration.principal")
    if not isinstance(principal, Principal):
        raise HTTPException(401, "authenticated tenant context required")
    return principal


@app.exception_handler(StoreIntegrityError)
async def corrupt_store(request, exc):
    return JSONResponse({"detail": "stored data failed integrity validation"}, status_code=503)


@app.exception_handler(EvidenceConflict)
async def conflicting_store(request, exc):
    return JSONResponse({"detail": "stored evidence conflicts with this operation"}, status_code=409)


@app.post("/workflows")
def create(body: dict, principal: Principal = Depends(require_principal)) -> dict:
    org, subject = body.get("org_id"), body.get("subject_id") or body.get("unit_id")
    if org != principal.org_id:
        raise HTTPException(403, "org does not match authenticated scope")
    try:
        identifier(subject)
    except ValueError:
        raise HTTPException(422, "valid unit_id or subject_id required") from None
    case = {"org_id": org, "unit_id": subject, "route": body.get("route") or sample_data.route(subject, org),
            "returned": body.get("returned", sample_data.has("returns", subject, org))}
    return run_workflow(case, load_flow(FLOW), STORE.for_org(org, actor=principal.actor))


def _get(workflow_id: str, store) -> dict:
    try:
        wf = store.load_workflow(workflow_id)
    except ValueError:
        wf = None
    if wf is None:
        raise HTTPException(404, "workflow not found")
    return wf


@app.get("/workflows/{workflow_id}")
def get(workflow_id: str, principal: Principal = Depends(require_principal)) -> dict:
    return _get(workflow_id, STORE.for_org(principal.org_id, actor=principal.actor))


@app.get("/workflows/{workflow_id}/evidence")
def evidence(workflow_id: str, principal: Principal = Depends(require_principal)) -> dict:
    store = STORE.for_org(principal.org_id, actor=principal.actor)
    return bundle(_get(workflow_id, store), store)


@app.post("/workflows/{workflow_id}/resume")
def resume_workflow(workflow_id: str, principal: Principal = Depends(require_principal)) -> dict:
    store = STORE.for_org(principal.org_id, actor=principal.actor)
    _get(workflow_id, store)
    return resume(workflow_id, load_flow(FLOW), store)


@app.post("/workflows/{workflow_id}/overrides")
def override(workflow_id: str, body: dict, principal: Principal = Depends(require_principal)) -> dict:
    store = STORE.for_org(principal.org_id, actor=principal.actor)
    _get(workflow_id, store)
    if body.get("actor", principal.actor) != principal.actor:
        raise HTTPException(403, "actor does not match authenticated principal")
    try:
        return apply_override(workflow_id, store, record_id=body.get("record_id", ""),
                              new_verdict=body.get("new_verdict", ""), actor=principal.actor,
                              reason=body.get("reason", ""), new_outcome=body.get("new_outcome"))
    except ValueError:
        raise HTTPException(422, "invalid override") from None


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
