import os
from shared.utils import sample_data
from shared.utils.records import build_output, build_record, check
from shared.utils.server import make_app
from shared.utils.stubs import photos
from agents.pack.vision import analyze_package_image

STAGE = "pack"
AGENT_ID = "pack-manager@1"
MODEL_NAME = "gemini-flash-lite-latest"
MODEL_METADATA = {"name": MODEL_NAME, "version": "1.0", "provider": "google", "calls": 1, "cost_usd": 0.001}

def handle(request: dict) -> dict:
    s = request["subject"]
    
    # Enforce cross-tenant security
    if s["org_id"] not in ["org_demo_alpha", "org_demo_bravo"]:
        raise ValueError("Invalid organization ID.")
        
    r = sample_data.row("pack", s["subject_id"], s["org_id"])
    
    expected_order_lines = r["order_lines"]
    refs = [p["ref"] for p in photos(r)]
    photo_inputs = photos(r)
    
    image_bytes = None
    if refs:
        # Determine actual file path
        image_path = refs[0]
        if os.path.exists(image_path):
            with open(image_path, "rb") as f:
                image_bytes = f.read()
    
    if not image_bytes:
        # Fallback to a placeholder if test images are missing, or return UNCERTAIN
        checks = [
            check("items_present", "UNCERTAIN", None, expected=expected_order_lines, observed="None", detail="Image file missing", evidence_refs=refs),
            check("quantities_correct", "UNCERTAIN", None, expected="Match", observed="None", detail="Image file missing", evidence_refs=refs),
            check("no_extra_items", "UNCERTAIN", None, expected="Match", observed="None", detail="Image file missing", evidence_refs=refs)
        ]
        record = build_record(
            request, agent_id=AGENT_ID, record_id=r["record_id"], captured_at=r["captured_at"], operator_id=r.get("operator_id"),
            unit_scope="order", refs={"order_id": r["order_id"]}, checks=checks, outcome="UNCERTAIN", model=MODEL_METADATA,
            inputs=photo_inputs, reason="Missing image data, unable to verify pack.",
            payload={"channel": r["channel"]}
        )
        return build_output(record)

    try:
        # Run Vision API
        ai_result = analyze_package_image(image_bytes, expected_order_lines)
        
        c_items = "PASS" if ai_result.checks_performed.all_items_present else "FAIL"
        c_qty = "PASS" if ai_result.checks_performed.quantities_correct else "FAIL"
        c_extra = "PASS" if ai_result.checks_performed.no_extra_items else "FAIL"
        
        checks = [
            check("items_present", c_items, None, expected=expected_order_lines, observed=ai_result.observed_items, evidence_refs=refs),
            check("quantities_correct", c_qty, None, expected="Correct quantities", observed="Check output", evidence_refs=refs),
            check("no_extra_items", c_extra, None, expected="No extra items", observed="Check output", evidence_refs=refs)
        ]
        
        outcome_map = {
            "SEAL": "seal",
            "STOP_AND_FIX": "stop_and_fix",
            "UNCERTAIN": "UNCERTAIN"
        }
        pack_out = outcome_map.get(ai_result.verdict, "UNCERTAIN")
        
        record = build_record(
            request, agent_id=AGENT_ID, record_id=r["record_id"], captured_at=r["captured_at"], operator_id=r.get("operator_id"),
            unit_scope="order", refs={"order_id": r["order_id"]}, checks=checks, outcome=pack_out, model=MODEL_METADATA,
            inputs=photo_inputs, reason=ai_result.reasoning,
            payload={"channel": r["channel"], "ai_verdict": ai_result.verdict}
        )
        return build_output(record)
        
    except Exception as e:
        checks = [
            check("items_present", "UNCERTAIN", None, expected=expected_order_lines, observed="Error", detail=str(e), evidence_refs=refs),
            check("quantities_correct", "UNCERTAIN", None, expected="Match", observed="Error", detail=str(e), evidence_refs=refs),
            check("no_extra_items", "UNCERTAIN", None, expected="Match", observed="Error", detail=str(e), evidence_refs=refs)
        ]
        record = build_record(
            request, agent_id=AGENT_ID, record_id=r["record_id"], captured_at=r["captured_at"], operator_id=r.get("operator_id"),
            unit_scope="order", refs={"order_id": r["order_id"]}, checks=checks, outcome="UNCERTAIN", model=MODEL_METADATA,
            inputs=photo_inputs, reason=f"API or processing failure: {str(e)}",
            payload={"channel": r["channel"]}
        )
        return build_output(record)

app = make_app(STAGE, handle)
