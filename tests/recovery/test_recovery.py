import pytest



from agents.recovery import app

from shared.utils.records import build_record, utcnow

from shared.utils.schema import errors

from tests.conftest import make_input





def _recovery_input(case, previous=None, overrides=None):

    return make_input(

        "recovery",

        case,

        previous=previous,

        overrides=overrides,

    )





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





def _patch_fee_lines(monkeypatch, lines):

    def fake_fee_lines(subject_id, org_id):

        return [

            {

                **line,

                "unit_id": subject_id,

                "org_id": org_id,

            }

            for line in lines

        ]



    monkeypatch.setattr(

        app.sample_data,

        "fee_lines",

        fake_fee_lines,

    )





def _mock_gemini(monkeypatch, *, position="CONTRADICTS", evidence_refs=None):

    calls = []



    def fake_interpret(charge, evidence, timeout_seconds=30.0):

        calls.append(

            {

                "charge": charge,

                "evidence": evidence,

            }

        )



        return {

            "position": position,

            "confidence": 0.95,

            "reason": "The supplied evidence supports the mocked interpretation.",

            "evidence_record_ids": (

                evidence_refs

                if evidence_refs is not None

                else [evidence[0]["record_id"]]

            ),

            "model": "test-model",

            "provider": "test",

            "prompt_version": "test",

            "calls": 1,

        }



    monkeypatch.setattr(app, "interpret_charge", fake_interpret)

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



    _patch_fee_lines(

        monkeypatch,

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

    assert out["evidence"]["model"]["prompt_version"] == app.PROMPT_VERSION





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



    def failing_interpret(charge, evidence, timeout_seconds=30.0):

        raise app.GeminiError("simulated Gemini 503")



    monkeypatch.setattr(

        app,

        "interpret_charge",

        failing_interpret,

    )



    _patch_fee_lines(

        monkeypatch,

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

            previous=previous,

        )

    )



    assert out["status"] != "completed"

    assert out["verdict"] == "UNCERTAIN"

    assert out["error"]["retryable"] is True

    assert out["error"]["code"] == "gemini_unavailable"





def test_zero_dollar_charge_is_deterministic_and_skips_gemini(

    monkeypatch,

    cases,

):

    case = cases[0]

    calls = _mock_gemini(monkeypatch)



    _patch_fee_lines(

        monkeypatch,

        [

            {

                "line_id": "TEST-ZERO",

                "charge_type": "lost_inbound",

                "amount_usd": "0.00",

                "posted_date": "2026-10-08",

            }

        ],

    )



    out = app.handle(_recovery_input(case))



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



    _patch_fee_lines(

        monkeypatch,

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



    _patch_fee_lines(

        monkeypatch,

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



    _patch_fee_lines(

        monkeypatch,

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



    _patch_fee_lines(

        monkeypatch,

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



    _patch_fee_lines(

        monkeypatch,

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

            previous=previous,

        )

    )



    charge = out["evidence"]["payload"]["charges"][0]



    assert charge["position"] == "SILENT"

    assert charge["evidence_record_ids"] == []

    assert out["evidence"]["payload"]["claimable_usd"] == 0.0

    assert out["verdict"] == "UNCERTAIN"