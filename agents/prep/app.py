"""Internal Prep capability: protect /run behind authenticated orchestration."""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .adapter import Adapter
from .common import Rejected, strict_json


def configured_adapter():
    filename, state = os.environ.get("PREP_CONFIG"), os.environ.get("PREP_STATE_DIR")
    if not filename or not state:
        raise RuntimeError("prep_configuration_required")
    try:
        path = Path(filename).resolve()
        config = strict_json(path.read_text(encoding="utf-8"))
        return Adapter(config, path.parent, state)
    except Rejected:
        raise
    except Exception:
        raise RuntimeError("prep_configuration_invalid") from None


def handle(request):
    return configured_adapter().handle(request)


app = FastAPI(title="Pod 14 Prep Manager", version="1")


@app.get("/health")
def health():
    try:
        configured_adapter()
        status = "ok"
    except Exception:
        status = "degraded"
    return {"status": status, "stage": "prep", "version": "1", "contract_version": "1.0"}


@app.post("/run")
async def run(request: Request):
    try:
        body = strict_json((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=422)
    try:
        return await run_in_threadpool(handle, body)
    except Rejected as exc:
        return JSONResponse({"error": exc.code}, status_code=exc.status)
    except Exception:
        return JSONResponse({"error": "prep_unavailable"}, status_code=503)
