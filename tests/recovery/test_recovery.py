
import csv
import hashlib
import json
import tempfile
from pathlib import Path

import httpx
import pytest

from agents.recovery import app
from agents.recovery import gemini_client
from shared.utils.records import build_record
from shared.utils.schema import errors
from tests.conftest import make_input


def _recovery_input(case, inputs, previous=None, overrides=None):
    request = make_input(
        "recovery",
        case,
        previous=previous,
        overrides=overrides,
    )
    request["inputs"] = inputs
    return request


def _upstream_record(
    case,
    *,
    stage,
    record_id,
    verdict="PASS",
    payload=None,
):
    checks = [
        {
            "check_key": f"{stage}_check",
            "verdict": verdict,
            "confidence": 1.0,
            "expected": "valid evidence",
            "observed": "valid evidence",
            "detail": "test evidence",
            "evidence_refs": [],
        }
    ]

    request = make_input(stage, case)

    return build_record(
        request,
        agent_id=f"{stage}-test@1.0.0",
        record_id=record_id,
        captured_at="2026-10-08T00:00:00Z",
        checks=checks,
        outcome="ok",
        reason="test evidence",
        model={
            "name": "test",
            "version": "1",
            "provider": "test",
            "prompt_version": "test",
            "calls": 0,
        },
        verdict=verdict,
        needs_human=False,
        payload=payload or {},
    )


def _patch_fee_lines(monkeypatch, case, lines):
    """Create a real temporary CSV and register its content-addressed input."""
    root = Path(tempfile.mkdtemp(prefix="recovery-test-"))
    monkeypatch.setenv("INPUT_DIR", str(root))

    subject_id = case.get("subject_id", case.get("unit_id"))
    org_id = case["org_id"]

    if not subject_id:
        raise ValueError(
            "The test case must contain subject_id or unit_id."
        )

    folder = root / subject_id / "recovery"
    folder.mkdir(parents=True)

    path = folder / "fees.csv"

    fieldnames = [
        "line_id",
        "report_type",
        "unit_id",
        "org_id",
        "sku",
        "fnsku",
        "fba_shipment_id",
        "order_id",
        "charge_type",
        "quantity",
        "amount_usd",
        "posted_date",
    ]

    rows = []
    for line in lines:
        rows.append(
            {
                "line_id": line["line_id"],
                "report_type": "fee_report",
                "unit_id": subject_id,
                "org_id": org_id,
                "sku": line.get("sku", ""),
                "fnsku": line.get("fnsku", ""),
                "fba_shipment_id": line.get("fba_shipment_id", ""),
                "order_id": line.get("order_id", ""),
                "charge_type": line["charge_type"],
                "quantity": line.get("quantity", "1"),
                "amount_usd": line["amount_usd"],
                "posted_date": line.get("posted_date", ""),
            }
        )

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    return [
        {
            "ref": f"{subject_id}/recovery/fees.csv",
            "kind": "document",
            "sha256": digest,
        }
    ]


def _mock_gemini(
    monkeypatch,
    *,
    position="CONTRADICTS",
    evidence_refs=None,
):
    calls = []

    def fake_interpret(items, timeout_seconds=30.0):
        calls.append(items)
        return {
            "results": [
                {
                    "line_id": item["charge"]["line_id"],
                    "position": position,
                    "confidence": 0.95,
                    "reason": (
                        "The supplied evidence supports the mocked interpretation."
                    ),
                    "evidence_record_ids": (
                        evidence_refs
                        if evidence_refs is not None
                        else [item["evidence"][0]["record_id"]]
                    ),
                }
                for item in items
            ],
            "model": app.os.getenv("GEMINI_MODEL", app.DEFAULT_MODEL),
            "provider": "google",
            "prompt_version": app.PROMPT_VERSION,
            "calls": 1,
        }

    monkeypatch.setattr(app, "interpret_charges", fake_interpret)

    return calls


def test_gemini_success_returns_contract_valid_output_and_preserves_valid_reference(
    monkeypatch,
    cases,
):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")

    case = cases[0]

    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-TEST-001",
            verdict="PASS",
        )
    ]

    calls = _mock_gemini(
        monkeypatch,
        position="CONTRADICTS",
        evidence_refs=["RCV-TEST-001"],
    )

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-001",
                "charge_type": "damaged_in_warehouse",
                "amount_usd": "10.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(
        _recovery_input(
            case,
            inputs,
            previous=previous,
        )
    )

    assert errors("agent-output", out) == []
    assert len(calls) == 1

    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "CONTRADICTS"
    assert charge["evidence_record_ids"] == ["RCV-TEST-001"]
    assert out["evidence"]["payload"]["claimable_usd"] == 10.0
    assert out["evidence"]["model"]["calls"] == 1
    assert out["evidence"]["model"]["name"] == "gemini-test-model"
    assert out["evidence"]["model"]["version"] == "gemini-test-model"
    assert (
        out["evidence"]["model"]["prompt_version"]
        == app.PROMPT_VERSION
    )


def test_gemini_failure_returns_retryable_pending(monkeypatch, cases):
    case = cases[0]

    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-TEST-002",
            verdict="PASS",
        )
    ]

    def failing_interpret(items, timeout_seconds=30.0):
        raise app.GeminiError("simulated Gemini 503", calls=1)

    monkeypatch.setattr(
        app,
        "interpret_charges",
        failing_interpret,
    )

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-002",
                "charge_type": "damaged_in_warehouse",
                "amount_usd": "10.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(
        _recovery_input(
            case,
            inputs,
            previous=previous,
        )
    )

    assert out["status"] != "completed"
    assert out["verdict"] == "UNCERTAIN"
    assert out["error"]["retryable"] is True
    assert out["error"]["code"] == "gemini_unavailable"
    assert out["evidence"]["model"]["calls"] == 1
    assert out["evidence"]["model"]["provider"] == "google"


def test_zero_dollar_charge_is_deterministic_and_skips_gemini(
    monkeypatch,
    cases,
):
    case = cases[0]
    calls = _mock_gemini(monkeypatch)

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-ZERO",
                "charge_type": "lost_inbound",
                "amount_usd": "0.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(_recovery_input(case, inputs))

    assert calls == []

    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "SILENT"
    assert charge["amount_usd"] == 0.0
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_inbound_defect_rule_is_deterministic(
    monkeypatch,
    cases,
):
    case = next(c for c in cases if c["route"] == "fba")
    calls = _mock_gemini(monkeypatch)

    previous = [
        _upstream_record(
            case,
            stage="prep",
            record_id="PRP-TEST-PASS",
            verdict="PASS",
        )
    ]

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-INBOUND",
                "charge_type": "inbound_defect_fee",
                "amount_usd": "15.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(
        _recovery_input(
            case,
            inputs,
            previous=previous,
        )
    )

    assert calls == []

    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "CONTRADICTS"
    assert charge["evidence_record_ids"] == ["PRP-TEST-PASS"]
    assert out["evidence"]["payload"]["claimable_usd"] == 15.0


def test_inbound_defect_with_prep_failure_is_deterministic(
    monkeypatch,
    cases,
):
    case = next(c for c in cases if c["route"] == "fba")
    calls = _mock_gemini(monkeypatch)

    previous = [
        _upstream_record(
            case,
            stage="prep",
            record_id="PRP-TEST-FAIL",
            verdict="FAIL",
        )
    ]

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-INBOUND-FAIL",
                "charge_type": "inbound_defect_fee",
                "amount_usd": "15.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(
        _recovery_input(
            case,
            inputs,
            previous=previous,
        )
    )

    assert calls == []

    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "SUPPORTS"
    assert charge["evidence_record_ids"] == ["PRP-TEST-FAIL"]
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_lost_inbound_is_deterministically_silent(
    monkeypatch,
    cases,
):
    case = cases[0]
    calls = _mock_gemini(monkeypatch)

    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-TEST-003",
            verdict="FAIL",
        )
    ]

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-LOST",
                "charge_type": "lost_inbound",
                "amount_usd": "25.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(
        _recovery_input(
            case,
            inputs,
            previous=previous,
        )
    )

    assert calls == []

    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "SILENT"
    assert charge["evidence_record_ids"] == ["RCV-TEST-003"]
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_weight_tier_without_measurements_is_deterministically_silent(
    monkeypatch,
    cases,
):
    case = cases[0]
    calls = _mock_gemini(monkeypatch)

    previous = [
        _upstream_record(
            case,
            stage="prep",
            record_id="PRP-TEST-WEIGHT",
            verdict="PASS",
            payload={},
        )
    ]

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-WEIGHT",
                "charge_type": "fulfilment_fee_weight_tier",
                "amount_usd": "12.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(
        _recovery_input(
            case,
            inputs,
            previous=previous,
        )
    )

    assert calls == []

    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "SILENT"
    assert charge["evidence_record_ids"] == []
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_hallucinated_evidence_reference_is_rejected(
    monkeypatch,
    cases,
):
    case = cases[0]

    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-TEST-004",
            verdict="PASS",
        )
    ]

    _mock_gemini(
        monkeypatch,
        position="CONTRADICTS",
        evidence_refs=["DOES-NOT-EXIST"],
    )

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-HALLUCINATION",
                "charge_type": "damaged_in_warehouse",
                "amount_usd": "20.00",
                "posted_date": "2026-10-08",
            }
        ],
    )

    out = app.handle(
        _recovery_input(
            case,
            inputs,
            previous=previous,
        )
    )

    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "SILENT"
    assert charge["evidence_record_ids"] == []
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0
    assert out["verdict"] == "UNCERTAIN"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record.update({"workflow_id": "WF-OTHER-UNIT"}),
        lambda record: record.update({"stage": "recovery"}),
        lambda record: record["subject"].update(
            {"org_id": "org_demo_other"}
        ),
    ],
    ids=["wrong-workflow", "recovery-is-not-upstream", "wrong-tenant"],
)
def test_invalid_upstream_evidence_is_ignored(
    monkeypatch,
    cases,
    mutation,
):
    case = cases[0]
    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-INVALID-001",
        )
    ]
    mutation(previous[0])

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-INVALID-EVIDENCE",
                "charge_type": "damaged_in_warehouse",
                "amount_usd": "10.00",
            }
        ],
    )
    calls = _mock_gemini(monkeypatch)

    out = app.handle(_recovery_input(case, inputs, previous=previous))
    charge = out["evidence"]["payload"]["charges"][0]

    assert calls == []
    assert charge["position"] == "SILENT"
    assert charge["evidence_record_ids"] == []
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_tampered_upstream_evidence_is_ignored(monkeypatch, cases):
    case = cases[0]
    record = _upstream_record(
        case,
        stage="receiving",
        record_id="RCV-TAMPERED-001",
    )
    record["reason"] = "tampered after sealing"

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "TEST-TAMPERED-EVIDENCE",
                "charge_type": "damaged_in_warehouse",
                "amount_usd": "10.00",
            }
        ],
    )
    calls = _mock_gemini(monkeypatch)

    out = app.handle(_recovery_input(case, inputs, previous=[record]))
    charge = out["evidence"]["payload"]["charges"][0]

    assert calls == []
    assert charge["position"] == "SILENT"
    assert charge["evidence_record_ids"] == []
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_identical_recovery_assessments_reuse_record_id(
    monkeypatch,
    cases,
):
    case = cases[0]
    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-REPLAY-001",
        )
    ]

    _mock_gemini(monkeypatch, position="CONTRADICTS")
    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [{
            "line_id": "REPLAY-001",
            "charge_type": "damaged_in_warehouse",
            "amount_usd": "10.00",
            "posted_date": "2026-10-08",
        }],
    )

    request = _recovery_input(case, inputs, previous=previous)
    first = app.handle(request)
    second = app.handle(request)

    assert (
        first["evidence"]["record_id"]
        == second["evidence"]["record_id"]
    )


def test_changed_fee_assessment_gets_new_record_id(
    monkeypatch,
    cases,
):
    case = cases[0]
    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-REPLAY-002",
        )
    ]
    _mock_gemini(monkeypatch, position="CONTRADICTS")

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [{
            "line_id": "REPLAY-002",
            "charge_type": "damaged_in_warehouse",
            "amount_usd": "10.00",
            "posted_date": "2026-10-08",
        }],
    )
    first = app.handle(_recovery_input(case, inputs, previous=previous))

    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [{
            "line_id": "REPLAY-002",
            "charge_type": "damaged_in_warehouse",
            "amount_usd": "15.00",
            "posted_date": "2026-10-08",
        }],
    )
    second = app.handle(_recovery_input(case, inputs, previous=previous))

    assert (
        first["evidence"]["record_id"]
        != second["evidence"]["record_id"]
    )


def test_eligible_fee_lines_share_one_gemini_batch(
    monkeypatch,
    cases,
):
    case = cases[0]
    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-BATCH-001",
        )
    ]
    calls = _mock_gemini(monkeypatch, position="CONTRADICTS")
    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {"line_id": "BATCH-001", "charge_type": "damaged_in_warehouse", "amount_usd": "10.00"},
            {"line_id": "BATCH-002", "charge_type": "damaged_in_warehouse", "amount_usd": "20.00"},
        ],
    )

    out = app.handle(_recovery_input(case, inputs, previous=previous))

    assert len(calls) == 1
    assert [item["charge"]["line_id"] for item in calls[0]] == [
        "BATCH-001",
        "BATCH-002",
    ]
    assert out["evidence"]["model"]["calls"] == 1
    assert out["evidence"]["payload"]["claimable_usd"] == 30.0


@pytest.mark.parametrize(
    "response",
    [
        [],
        [
            {
                "line_id": "MALFORMED-001",
                "position": "CONTRADICTS",
                "confidence": "high",
                "reason": "invalid confidence",
                "evidence_record_ids": ["RCV-BATCH-002"],
            }
        ],
        [
            {
                "line_id": "UNKNOWN-LINE",
                "position": "CONTRADICTS",
                "confidence": 1.0,
                "reason": "unknown ID",
                "evidence_record_ids": ["RCV-BATCH-002"],
            }
        ],
    ],
    ids=["missing", "malformed", "unknown-id"],
)
def test_malformed_batch_results_never_recommend_claims(
    monkeypatch,
    cases,
    response,
):
    case = cases[0]
    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-BATCH-002",
        )
    ]

    def fake_interpret(items, timeout_seconds=30.0):
        return {
            "results": response,
            "model": "test-model",
            "provider": "test",
            "prompt_version": "test",
            "calls": 1,
        }

    monkeypatch.setattr(app, "interpret_charges", fake_interpret)
    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "MALFORMED-001",
                "charge_type": "damaged_in_warehouse",
                "amount_usd": "20.00",
            }
        ],
    )

    out = app.handle(_recovery_input(case, inputs, previous=previous))
    charge = out["evidence"]["payload"]["charges"][0]

    assert charge["position"] == "SILENT"
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_duplicate_batch_result_is_silent_for_affected_line(
    monkeypatch,
    cases,
):
    case = cases[0]
    previous = [
        _upstream_record(
            case,
            stage="receiving",
            record_id="RCV-BATCH-003",
        )
    ]
    duplicate = {
        "line_id": "DUPLICATE-001",
        "position": "CONTRADICTS",
        "confidence": 1.0,
        "reason": "duplicate",
        "evidence_record_ids": ["RCV-BATCH-003"],
    }
    monkeypatch.setattr(
        app,
        "interpret_charges",
        lambda items, timeout_seconds=30.0: {
            "results": [duplicate, duplicate],
            "model": "test-model",
            "provider": "test",
            "prompt_version": "test",
            "calls": 1,
        },
    )
    inputs = _patch_fee_lines(
        monkeypatch,
        case,
        [
            {
                "line_id": "DUPLICATE-001",
                "charge_type": "damaged_in_warehouse",
                "amount_usd": "20.00",
            }
        ],
    )

    out = app.handle(_recovery_input(case, inputs, previous=previous))

    assert out["evidence"]["payload"]["charges"][0]["position"] == "SILENT"
    assert out["evidence"]["payload"]["claimable_usd"] == 0.0


def test_gemini_batch_client_sends_one_request_for_multiple_lines(
    monkeypatch,
):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    sent = []
    model_response = {
        "results": [
            {
                "line_id": line_id,
                "position": "SILENT",
                "confidence": 0.5,
                "reason": "test response",
                "evidence_record_ids": [],
            }
            for line_id in ("HTTP-BATCH-001", "HTTP-BATCH-002")
        ]
    }

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": json.dumps(model_response)}]
                        }
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        sent.append(json)
        assert 0 < timeout <= 30.0
        return Response()

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)
    result = gemini_client.interpret_charges(
        items=[
            {"charge": {"line_id": "HTTP-BATCH-001"}, "evidence": []},
            {"charge": {"line_id": "HTTP-BATCH-002"}, "evidence": []},
        ]
    )

    assert len(sent) == 1
    prompt = sent[0]["contents"][0]["parts"][0]["text"]
    assert "HTTP-BATCH-001" in prompt and "HTTP-BATCH-002" in prompt
    assert result["calls"] == 1
    assert [item["line_id"] for item in result["results"]] == [
        "HTTP-BATCH-001",
        "HTTP-BATCH-002",
    ]


@pytest.mark.parametrize(
    ("api_key", "expected_calls"),
    [(None, 0), ("test-key", 1)],
    ids=["not-configured", "request-failed"],
)
def test_gemini_error_reports_actual_request_count(
    monkeypatch,
    api_key,
    expected_calls,
):
    if api_key is None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GEMINI_API_KEY", api_key)

    def failed_post(*args, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(gemini_client.httpx, "post", failed_post)

    with pytest.raises(gemini_client.GeminiError) as error:
        gemini_client.interpret_charges(
            items=[
                {"charge": {"line_id": "HTTP-FAIL-001"}, "evidence": []}
            ]
        )

    assert error.value.calls == expected_calls