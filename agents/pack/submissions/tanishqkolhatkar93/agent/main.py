import os
import json
import hashlib
import time
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, Form, Header
from vision import analyze_package_image

app = FastAPI()

@app.post("/verify")
async def verify_package(
    image: UploadFile = File(...),
    unit_id: str = Form(...),
    operator_id: str = Form(...),
    order_id: str = Form(...),
    expected_order_lines: str = Form(...),
    x_org_id: str = Header(...)
):
    start_time = time.time()
    image_bytes = await image.read()
    image_hash = hashlib.sha256(bytes(image_bytes)).hexdigest()
    
    try:
        result = analyze_package_image(image_bytes, expected_order_lines)
        verdict = result.verdict
        reasoning = result.reasoning
        observed_items = result.observed_items
        checks_performed = result.checks_performed.dict()
    except Exception as e:
        verdict = "PENDING"
        reasoning = "Fail Open / Network Error"
        observed_items = "UNKNOWN"
        checks_performed = {}

    latency_ms = int((time.time() - start_time) * 1000)
    
    # Fixed Evidence Contract
    contract = {
        "record_id": f"rcd_{int(time.time())}",
        "schema_version": "1.0",
        "organization_id": x_org_id,
        "client_id": "streamlit_post",
        "agent": "main_vision_bot",
        "subject": unit_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "operator_label": operator_id,
        "images": [image_hash],
        "metadata_traceability": {
            "what_should_be_in_box": expected_order_lines,
            "what_was_actually_found": observed_items,
            "what_checks_were_performed": checks_performed
        },
        "checks": [
            {
                "check_key": "all_items_match",
                "verdict": verdict,
                "confidence": 1.0 if verdict != "UNCERTAIN" else 0.3,
                "detail": reasoning,
                "model_version": "gemini-flash-lite",
                "latency_ms": latency_ms
            }
        ],
        "outcome": {
            "decision": verdict,
            "decided_by": "automated_agent",
            "decided_at": datetime.now(timezone.utc).isoformat()
        },
        "overrides": [],
        "status": "processed",
        "content_hash": ""
    }
    contract["content_hash"] = hashlib.sha256(json.dumps(contract).encode()).hexdigest()
    
    os.makedirs("../contract", exist_ok=True)
    with open(f"../contract/{contract['record_id']}.json", "w") as f:
        json.dump(contract, f, indent=2)
    
    return {"verdict": verdict, "reasoning": reasoning}
