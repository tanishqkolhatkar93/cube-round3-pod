"""Existing /health and /run API, with explicit trusted Returns configuration."""
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .adapter import Adapter
from .request_store import Rejected
from agents.readiness import configuration_code, checks_not_run


def configured_adapter():
    filename = os.environ.get("RETURNS_CONFIG")
    state = os.environ.get("RETURNS_STATE_DIR")
    if not filename or not state:
        raise RuntimeError("returns_configuration_required")
    try:
        path = Path(filename).resolve()
        config = json.loads(path.read_text(encoding="utf-8"))
        return Adapter(config, path.parent, Path(state).resolve())
    except Rejected:
        raise
    except Exception:
        raise RuntimeError('returns_configuration_invalid') from None


def handle(request):
    return configured_adapter().handle(request)


app = FastAPI(title="Returns Manager")


@app.get("/health")
def health():
    diagnostics = checks_not_run()
    try:
        adapter = configured_adapter()
        status = "ok"
        live = adapter.config['mode'] == 'existing' and any(
            b['inspection'] == 'live' for b in adapter.config['bindings'])
        diagnostics['provider_status'] = 'not_verified' if live else 'not_required'
    except Exception as exc:
        status = "degraded"
        diagnostics['error'] = configuration_code(exc, 'returns_configuration_invalid')
    return {"status": status, "stage": "returns", "version": "1", "contract_version": "1.0", **diagnostics}


@app.post("/run")
async def run(request: Request):
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=422)
    try:
        return await run_in_threadpool(handle, body)
    except Rejected as exc:
        return JSONResponse({"error": exc.code}, status_code=exc.status)
    except Exception:
        return JSONResponse({"error": "returns_unavailable"}, status_code=503)
