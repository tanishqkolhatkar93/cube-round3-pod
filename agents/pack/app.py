import os
import hashlib
from shared.utils import sample_data
from shared.utils.records import build_output, build_record, check, pending_output
from shared.utils.server import make_app
from agents.pack.vision import analyze_package_image

STAGE = "pack"
AGENT_ID = "pack-manager@1"
MODEL_NAME = "gemini-flash-lite-latest"

def handle(request: dict) -> dict:
    s = request["subject"]
    
    # Enforce cross-tenant security
    if s["org_id"] not in ["org_demo_alpha", "org_demo_bravo"]:
        raise LookupError(f"Unknown organization {s['org_id']}")
        
    r = sample_data.row("pack", s["subject_id"], s["org_id"])
    expected_order_lines = r["order_lines"]
    
    # Extract inputs and hashes
    inputs = request.get("inputs", [])
    image_bytes = None
    photo_inputs = []
    
    input_dir = os.environ.get("INPUT_DIR", "data/input")
    
    for inp in inputs:
        if inp.get("kind") == "image":
            path = os.path.join(input_dir, inp["ref"].replace("/", os.sep))
            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                    if not image_bytes:
                        image_bytes = data
                    sha = hashlib.sha256(data).hexdigest()
                    photo_inputs.append({"ref": inp["ref"], "kind": "image", "sha256": sha})
            else:
                photo_inputs.append({"ref": inp["ref"], "kind": "image", "sha256": None})
    
    if not image_bytes:
        model_meta = {"name": MODEL_NAME, "version": "1.0", "provider": "google", "calls": 0, "cost_usd": 0.0}
        checks = [
            check("items_present", "UNCERTAIN", None, expected=expected_order_lines, observed="No image", detail="Image file missing", evidence_refs=[p["ref"] for p in photo_inputs]),
            check("quantities_correct", "UNCERTAIN", None, expected="Match", observed="No image", detail="Image file missing", evidence_refs=[p["ref"] for p in photo_inputs]),
            check("no_extra_items", "UNCERTAIN", None, expected="Match", observed="No image", detail="Image file missing", evidence_refs=[p["ref"] for p in photo_inputs])
        ]
        record = build_record(
            request, agent_id=AGENT_ID, record_id=r["record_id"], captured_at=r["captured_at"], operator_id=r.get("operator_id"),
            unit_scope="order", refs={"order_id": r["order_id"]}, checks=checks, outcome="pending_review", model=model_meta,
            inputs=photo_inputs, reason="Missing image data, unable to verify pack.",
            payload={"channel": r["channel"]}
        )
        return build_output(record)

    try:
        # Run Vision API
        ai_result = analyze_package_image(image_bytes, expected_order_lines)
    except Exception as e:
        return pending_output(request, code="model_failure", message=str(e), retryable=False, agent_id=AGENT_ID)

    # Calculate model costs assuming Gemini Flash Lite (very cheap, stubbing cost_usd)
    # The actual call is 1, cost can be hardcoded for simplicity.
    model_meta = {"name": MODEL_NAME, "version": "1.0", "provider": "google", "calls": 1, "cost_usd": 0.0001}

    # Extract actual observed items
    obs_items = ai_result.observed_items

    if ai_result.verdict == "UNCERTAIN":
        c_items = c_qty = c_extra = "UNCERTAIN"
        pack_out = "pending_review"
    else:
        c_items = "PASS" if ai_result.checks_performed.all_items_present else "FAIL"
        c_qty = "PASS" if ai_result.checks_performed.quantities_correct else "FAIL"
        c_extra = "PASS" if ai_result.checks_performed.no_extra_items else "FAIL"
        
        outcome_map = {
            "SEAL": "seal",
            "STOP_AND_FIX": "stop_and_fix"
        }
        pack_out = outcome_map.get(ai_result.verdict, "pending_review")
        
    checks = [
        check("items_present", c_items, None, expected=expected_order_lines, observed=obs_items, evidence_refs=[p["ref"] for p in photo_inputs]),
        check("quantities_correct", c_qty, None, expected="Expected matching quantities", observed=obs_items, evidence_refs=[p["ref"] for p in photo_inputs]),
        check("no_extra_items", c_extra, None, expected="No extra items", observed=obs_items, evidence_refs=[p["ref"] for p in photo_inputs])
    ]
    
    record = build_record(
        request, agent_id=AGENT_ID, record_id=r["record_id"], captured_at=r["captured_at"], operator_id=r.get("operator_id"),
        unit_scope="order", refs={"order_id": r["order_id"]}, checks=checks, outcome=pack_out, model=model_meta,
        inputs=photo_inputs, reason=ai_result.reasoning,
        payload={"channel": r["channel"], "ai_verdict": ai_result.verdict}
    )
    return build_output(record)

app = make_app(STAGE, handle)
