"""Every agent, on every applicable sample subject, must return a valid Agent Output with a valid Evidence Record.

This runs against whatever agents/<stage>/agent.json points at (stub, in-process, or HTTP).
When you replace the stub, replace the sample loop with your own fixtures, but keep the assertions.
"""
import pytest
import csv
import hashlib
from pathlib import Path
from orchestration.clients import AgentRejected, client_for
from shared.utils.hashing import verify
from shared.utils.records import add_agent_override
from shared.utils.schema import errors
from tests.conftest import AGENTS, applies, make_input

PREFIX = {"receiving": "RCV", "prep": "PRP", "pack": "PCK", "returns": "RTN", "recovery": "RCY"}


def _attach_recovery_fee_report(request, case, tmp_path, monkeypatch):
    """Attach a filtered, hash-verified sample fee report to a test request."""
    root = tmp_path / "input"
    folder = root / case["unit_id"] / "recovery"
    folder.mkdir(parents=True)

    source = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "sample"
        / "fee_report_sample.csv"
    )
    target = folder / "fees.csv"

    with source.open("r", newline="", encoding="utf-8-sig") as src:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames
        rows = [
            row
            for row in reader
            if row["unit_id"] == case["unit_id"]
            and row["org_id"] == case["org_id"]
        ]

    if not rows:
        raise AssertionError(
            f"No sample fee rows for {case['unit_id']} / {case['org_id']}"
        )

    with target.open("w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    monkeypatch.setenv("INPUT_DIR", str(root))

    request["inputs"] = [
        {
            "ref": f"{case['unit_id']}/recovery/fees.csv",
            "kind": "document",
            "sha256": digest,
        }
    ]
    return request


@pytest.mark.parametrize("stage", AGENTS)
def test_outputs_are_contract_valid(stage, cases):
    client, checked = client_for(stage), 0
    for case in (c for c in cases if applies(stage, c)):
        out = client.run(make_input(stage, case), 30)
        assert errors("agent-output", out) == [], f"{stage} {case['unit_id']}"
        ev = out["evidence"]
        assert ev["record_id"].startswith(PREFIX[stage] + "-")
        assert ev["stage"] == out["stage"] == stage and ev["agent_id"] == out["agent_id"]
        assert ev["workflow_id"] == out["workflow_id"] == f"WF-{case['org_id']}-{case['unit_id']}"
        assert (ev["subject"]["org_id"], ev["subject"]["subject_id"]) == (case["org_id"], case["unit_id"])
        assert out["verdict"] == ev["decision"]["verdict"] and out["status"] == ev["status"]
        assert verify(ev), "content_hash does not match the record body"
        for c in ev["checks"]:
            if c["verdict"] == "UNCERTAIN":
                assert c.get("uncertain_reason"), "UNCERTAIN needs a reason (it is a verdict, not a shrug)"
        checked += 1
    assert checked > 0


@pytest.mark.parametrize("stage", AGENTS)
def test_other_tenant_gets_nothing(stage, cases):
    """Refuse cross-tenant requests only where the agent has an authority source."""
    case = next(c for c in cases if applies(stage, c))
    other = "org_demo_bravo" if case["org_id"] == "org_demo_alpha" else "org_demo_alpha"
    if stage == "recovery":
        # Recovery has no independent authorization source; without a report it
        # can only echo the scope asserted by the request.
        out = client_for(stage).run(
            make_input(stage, {**case, "org_id": other}),
            30,
        )
        assert out["evidence"]["subject"]["org_id"] == other
        assert out["evidence"]["payload"]["charges"] == []
        return

    with pytest.raises(AgentRejected):
        client_for(stage).run(make_input(stage, {**case, "org_id": other}), 30)


@pytest.mark.parametrize("mismatch", ["org_id", "unit_id"])
def test_recovery_rejects_hash_verified_fee_report_with_mismatched_scope(
    mismatch,
    cases,
    tmp_path,
    monkeypatch,
):
    case = next(c for c in cases if c["unit_id"] == "UNIT-0002")
    request = _attach_recovery_fee_report(
        make_input("recovery", case),
        case,
        tmp_path,
        monkeypatch,
    )
    root = tmp_path / "input"
    target = root / request["inputs"][0]["ref"]
    with target.open("r", newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames
        rows = list(reader)

    rows[0][mismatch] = (
        "org_demo_mismatch" if mismatch == "org_id" else "UNIT-MISMATCH"
    )
    with target.open("w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    request["inputs"][0]["sha256"] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()

    with pytest.raises(AgentRejected, match="organization or subject"):
        client_for("recovery").run(request, 30)


@pytest.mark.parametrize("stage", AGENTS)
def test_same_request_same_record_id(stage, cases):
    case = next(c for c in cases if applies(stage, c))
    req = make_input(stage, case)
    client = client_for(stage)
    assert client.run(req, 30)["evidence"]["record_id"] == client.run(req, 30)["evidence"]["record_id"]


def test_each_stage_can_consume_the_previous_stages_output(cases):
    """The hand-off: feed every stage the evidence the earlier stages produced; it must work and reference it."""
    case = next(c for c in cases if c["route"] == "fba" and c["returned"])
    previous = []
    for stage in [s for s in AGENTS if applies(s, case)]:
        out = client_for(stage).run(make_input(stage, case, previous), 30)
        assert errors("agent-output", out) == []
        assert set(out["evidence"]["upstream_refs"]) == {r["record_id"] for r in previous}, \
            f"{stage} must list the previous evidence it consumed in upstream_refs"
        previous.append(out["evidence"])


def test_recovery_honours_overrides_of_previous_evidence(
    cases,
    tmp_path,
    monkeypatch,
):
    """Prep PASS makes the inbound-defect fee contradicted. A person overriding Prep to FAIL must change that."""
    if "recovery" not in AGENTS or "prep" not in AGENTS:
        pytest.skip("needs both Prep and Recovery in the flow")
    case = next(c for c in cases if c["unit_id"] == "UNIT-0014")
    prior = []
    for stage in ("receiving", "prep", "returns"):
        prior.append(client_for(stage).run(make_input(stage, case, prior), 30)["evidence"])
    prep_id = prior[1]["record_id"]
    base_request = _attach_recovery_fee_report(
        make_input("recovery", case, prior),
        case,
        tmp_path,
        monkeypatch,
    )
    base = client_for("recovery").run(base_request, 30)["evidence"]

    override = {
        "override_id": "OVR-001",
        "supersedes": {
            "record_id": prep_id,
            "override_id": None,
        },
        "target": "decision",
        "actor": "t",
        "at": "2026-01-01T00:00:00Z",
        "reason": "label creased",
        "original_verdict": "PASS",
        "previous_verdict": "PASS",
        "new_verdict": "FAIL",
    }

    changed_request = make_input(
        "recovery",
        case,
        prior,
        [override],
    )
    changed_request["inputs"] = base_request["inputs"]

    changed = client_for("recovery").run(
        changed_request,
        30,
    )["evidence"]

    pos = lambda ev: {
        c["charge_type"]: c["position"]
        for c in ev["payload"]["charges"]
    }

    assert pos(base)["inbound_defect_fee"] == "CONTRADICTS"
    assert pos(changed)["inbound_defect_fee"] == "SUPPORTS"

def test_agent_level_override_is_append_only(cases):
    out = client_for("receiving").run(make_input("receiving", cases[0]), 30)
    rec, target = out["evidence"], out["evidence"]["checks"][0]
    new = add_agent_override(rec, by="op_test", target=target["check_key"], new_verdict="FAIL", reason="operator disagrees")
    assert new["overrides"][0]["original_verdict"] == target["verdict"]
    assert new["checks"] == rec["checks"], "an override must never rewrite the original check"
    assert verify(new), "agent-level overrides sit outside the content hash"
    assert len(add_agent_override(new, by="op2", target="decision", new_verdict="PASS", reason="second look")["overrides"]) == 2
