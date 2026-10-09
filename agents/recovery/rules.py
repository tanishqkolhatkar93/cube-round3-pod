"""Recovery deterministic policy ported from PR #8, commit 739d957.
Input scope and measurement eligibility are enforced by the adapter before use.
"""
from typing import Any

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
