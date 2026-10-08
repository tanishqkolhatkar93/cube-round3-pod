"""Round 3 Recovery Manager agent.

Recovery evaluates each fee line against the accumulated upstream evidence.

Contract semantics:

    PASS      evidence supports the charge -> no claim
    FAIL      evidence contradicts the charge -> claim recommended
    UNCERTAIN evidence is silent/insufficient -> never claim

Gemini interprets evidence. Deterministic policy below owns the final
Recovery semantics and claimability rules.

"""

from __future__ import annotations

import os
from typing import Any

from shared.utils import sample_data
from shared.utils.records import (
    build_output,
    build_record,
    check,
    pending_output,
    utcnow,
)
from shared.utils.server import make_app
from shared.utils.stubs import effective_verdict, previous
from .gemini_client import DEFAULT_MODEL, PROMPT_VERSION, GeminiError, interpret_charge


STAGE = "recovery"
AGENT_ID = "recovery-manager@1.0.0"


def _check_key(line_id: str) -> str:
    return f"charge_{line_id.lower().replace('-', '_')}"


def _subject_ref_matches(
    charge: dict[str, Any],
    record: dict[str, Any],
) -> bool:
    """Prefer explicit references when available; otherwise use subject id."""
    subject = record.get("subject", {})
    if subject.get("org_id") != charge.get("org_id"):
        return False

    refs = subject.get("refs") or {}

    # Prefer exact shipment/order/SKU references when both sides have them.
    for key in ("fba_shipment_id", "order_id", "sku", "fnsku"):
        charge_value = charge.get(key)
        ref_value = refs.get(key)
        if charge_value and ref_value and charge_value != ref_value:
            return False

    return subject.get("subject_id") == charge.get("unit_id")


def _usable_previous_evidence(
    request: dict[str, Any],
    charge: dict[str, Any],
) -> list[dict[str, Any]]:
    """Collect completed upstream records relevant to this fee line."""
    records: list[dict[str, Any]] = []

    for record in request.get("previous_evidence", []):
        if record.get("status") != "completed":
            continue

        if not _subject_ref_matches(charge, record):
            continue

        records.append(record)

    return records


def _effective_records(
    request: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply workflow overrides without mutating the original evidence."""
    effective: list[dict[str, Any]] = []

    for record in records:
        copy = dict(record)
        copy["effective_verdict"] = effective_verdict(request, record)
        effective.append(copy)

    return effective


def _deterministic_position(
    charge: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> tuple[str, str, list[str]]:
    """Apply Recovery rules that must not be delegated to the model."""

    amount = float(charge.get("amount_usd", 0) or 0)
    charge_type = charge.get("charge_type", "")

    # D-005: zero-dollar reimbursements are not claimable.
    if amount <= 0:
        return (
            "SILENT",
            "amount is 0.00: zero-amount reimbursement is not claimable (D-005)",
            [],
        )

    # Inbound-defect fees are evaluated against Prep evidence.
    # PASS = Prep shows compliance, so the fee is contradicted.
    # FAIL = Prep shows a defect, so the fee is supported.
    if charge_type == "inbound_defect_fee":
        prep_records = [
            r for r in evidence
            if r.get("stage") == "prep"
        ]

        if not prep_records:
            return (
                "SILENT",
                "no usable Prep record for this subject",
                [],
            )

        prep = prep_records[-1]
        prep_verdict = prep.get("effective_verdict")

        if prep_verdict == "PASS":
            return (
                "CONTRADICTS",
                "Prep evidence shows the unit compliant",
                [prep["record_id"]],
            )

        if prep_verdict == "FAIL":
            return (
                "SUPPORTS",
                "Prep evidence shows a defect",
                [prep["record_id"]],
            )

        return (
            "SILENT",
            "Prep evidence is uncertain",
            [prep["record_id"]],
        )

    # F-10: Receiving supplier shortfall cannot prove channel-side lost inbound.
    if charge_type == "lost_inbound":
        receiving = [
            r for r in evidence
            if r.get("stage") == "receiving"
        ]
        if receiving:
            return (
                "SILENT",
                "Receiving shortfall is supplier-side and cannot prove "
                "channel-side lost_inbound (F-10)",
                [r["record_id"] for r in receiving],
            )
        return (
            "SILENT",
            "no valid channel-side evidence for lost_inbound",
            [],
        )

    # Weight-tier charges require measured weight/dimensions. Prep is the
    # natural upstream source; without those measurements the charge is silent.
    if charge_type == "fulfilment_fee_weight_tier":
        measurement_records = []
        for record in evidence:
            if record.get("stage") != "prep":
                continue
            measurements = (record.get("payload") or {}).get("measurements")
            if measurements:
                measurement_records.append(record)

        if not measurement_records:
            return (
                "SILENT",
                "no measured weight/dimensions upstream (F-07)",
                [],
            )

    return "", "", []


def _position_to_verdict(position: str) -> str:
    return {
        "SUPPORTS": "PASS",
        "CONTRADICTS": "FAIL",
        "SILENT": "UNCERTAIN",
    }[position]


def _outcome_for_position(position: str) -> str:
    return {
        "SUPPORTS": "no_claim",
        "CONTRADICTS": "claim_recommended",
        "SILENT": "insufficient_evidence",
    }[position]


def _build_pending(
    request: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Return the contract's fail-open pending response."""
    return pending_output(
        request,
        agent_id=AGENT_ID,
        code="gemini_unavailable",
        message=reason,
        retryable=True,
    )


def handle(request: dict[str, Any]) -> dict[str, Any]:
    """Normal Round 3 agent entry point."""
    subject = request["subject"]
    org_id = subject["org_id"]
    subject_id = subject["subject_id"]

    # Tenant isolation: unknown subject must not be interpreted as
    # "nothing to claim".
    if not sample_data.has("receiving", subject_id, org_id):
        raise LookupError(
            f"unknown subject {subject_id} in {org_id}"
        )

    lines = sample_data.fee_lines(subject_id, org_id)

    checks: list[dict[str, Any]] = []
    charges: list[dict[str, Any]] = []
    unclaimable: list[dict[str, Any]] = []
    claimable_usd = 0.0

    model_calls = 0

    for line in lines:
        amount = float(line.get("amount_usd", 0) or 0)

        evidence = _effective_records(
            request,
            _usable_previous_evidence(request, line),
        )

        deterministic_position, deterministic_reason, deterministic_refs = (
            _deterministic_position(line, evidence)
        )

        if deterministic_position:
            position = deterministic_position
            reason = deterministic_reason
            evidence_refs = deterministic_refs
            confidence = None

        elif not evidence:
            # No upstream evidence means SILENT. Do not call the model
            # just to discover that nothing was provided.
            position = "SILENT"
            reason = "no usable upstream evidence for this charge"
            evidence_refs = []
            confidence = None

        else:
            try:
                interpretation = interpret_charge(
                    charge=line,
                    evidence=evidence,
                )
                model_calls += 1

                position = interpretation["position"]
                reason = interpretation["reason"]
                evidence_refs = interpretation["evidence_record_ids"]
                confidence = interpretation["confidence"]

                # Never trust model-supplied references to records that were
                # not actually supplied to this Recovery invocation.
                available_ids = {
                    record["record_id"] for record in evidence
                }
                evidence_refs = [
                    ref for ref in evidence_refs
                    if ref in available_ids
                ]

                if not evidence_refs and position != "SILENT":
                    # A non-silent model judgment without traceable evidence
                    # is not acceptable under the contract.
                    position = "SILENT"
                    reason = (
                        "model produced a non-silent judgment without "
                        "traceable evidence references"
                    )
                    confidence = None

            except GeminiError as exc:
                # Model failure is not a judgment. Save a pending record.
                return _build_pending(
                    request,
                    f"Gemini Recovery interpretation failed: {exc}",
                )

        verdict = _position_to_verdict(position)
        outcome = _outcome_for_position(position)

        uncertain_reason = None
        if verdict == "UNCERTAIN":
            uncertain_reason = "insufficient_evidence"

        checks.append(
            check(
                _check_key(line["line_id"]),
                verdict,
                confidence,
                expected="charge supported by evidence",
                observed=position,
                detail=reason,
                evidence_refs=evidence_refs,
                uncertain_reason=uncertain_reason,
            )
        )

        charge_result = {
            "line_id": line["line_id"],
            "charge_type": line["charge_type"],
            "amount_usd": amount,
            "position": position,
            "reason": reason,
            "evidence_record_ids": evidence_refs,
            "outcome": outcome,
        }

        charges.append(charge_result)

        if position == "CONTRADICTS":
            claimable_usd += amount
        else:
            unclaimable.append(charge_result)

    # The evidence-record rollup is determined by the individual checks.
    if any(c["verdict"] == "FAIL" for c in checks):
        overall_verdict = "FAIL"
    elif any(c["verdict"] == "UNCERTAIN" for c in checks):
        overall_verdict = "UNCERTAIN"
    else:
        overall_verdict = "PASS"

    if claimable_usd > 0:
        overall_outcome = "claim_recommended"
    elif any(c["verdict"] == "UNCERTAIN" for c in checks):
        overall_outcome = "insufficient_evidence"
    else:
        overall_outcome = "no_claim"

    upstream_refs = [
        record["record_id"]
        for record in request.get("previous_evidence", [])
        if record.get("record_id")
    ]

    model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    record = build_record(
        request,
        agent_id=AGENT_ID,
        record_id=f"RCY-{subject_id}",
        model={
            "name": model_name,
            "version": model_name,
            "provider": "google",
            "prompt_version": PROMPT_VERSION,
            "calls": model_calls,
        },
        captured_at=max(
            (
                f"{line['posted_date']}T00:00:00Z"
                for line in lines
                if line.get("posted_date")
            ),
            default=utcnow(),
        ),
        checks=checks,
        outcome=overall_outcome,
        verdict=overall_verdict,
        needs_human=False,
        reason=(
            f"Recovery evaluated {len(charges)} charge(s); "
            f"{sum(c['position'] == 'CONTRADICTS' for c in charges)} "
            f"contradicted, "
            f"{sum(c['position'] == 'SUPPORTS' for c in charges)} supported, "
            f"{sum(c['position'] == 'SILENT' for c in charges)} silent"
        ),
        payload={
            "charges": charges,
            "claimable_usd": round(claimable_usd, 2),
            "unclaimable": unclaimable,
        },
        upstream_refs=upstream_refs,
    )

    return build_output(
        record,
        next_step="complete",
    )


app = make_app(STAGE, handle)