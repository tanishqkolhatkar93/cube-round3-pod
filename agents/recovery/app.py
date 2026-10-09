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
from shared.utils.hashing import verify

import json
import csv
import hashlib
import io
import math
import os
import time
from pathlib import Path
from typing import Any

from shared.utils.errors import AgentInputError
from shared.utils.records import (
    build_output,
    build_record,
    check,
    pending_output,
    utcnow,
)
from shared.utils.server import make_app
from shared.utils.stubs import effective_verdict
from .gemini_client import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    GeminiError,
    interpret_charges,
)


STAGE = "recovery"
AGENT_ID = "recovery-manager@1.0.0"
ROOT = Path(__file__).resolve().parents[2]

FEE_REPORT_COLUMNS = {
    "line_id",
    "unit_id",
    "org_id",
    "charge_type",
    "amount_usd",
}


def _check_key(line_id: str) -> str:
    return f"charge_{line_id.lower().replace('-', '_')}"


def _recovery_record_id(
    request: dict[str, Any],
    verified_inputs: list[dict[str, Any]],
    upstream_refs: list[str],
    charges: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    outcome: str,
    verdict: str,
) -> str:
    """Build a stable ID for the same assessment, distinct for changed assessments."""
    referenced = set(upstream_refs)
    upstream = sorted(
        [
            {
                "record_id": record.get("record_id"),
                "content_hash": record.get("content_hash"),
            }
            for record in request.get("previous_evidence", [])
            if record.get("record_id") in referenced
        ],
        key=lambda item: item["record_id"] or "",
    )

    assessment = {
        "workflow_id": request["workflow_id"],
        "subject": request["subject"],
        "inputs": sorted(
            verified_inputs,
            key=lambda item: (item.get("ref", ""), item.get("sha256", "")),
        ),
        "upstream": upstream,
        "overrides": request.get("context", {}).get("overrides", []),
        "charges": charges,
        "checks": checks,
        "outcome": outcome,
        "verdict": verdict,
    }

    canonical = json.dumps(
        assessment,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    fingerprint = hashlib.sha256(canonical).hexdigest()[:20]
    subject_id = request["subject"]["subject_id"]
    return f"RCY-{subject_id}-{fingerprint}"


def _subject_ref_matches(
    charge: dict[str, Any],
    record: dict[str, Any],
) -> bool:
    """Prefer explicit references when available; otherwise use subject id."""
    subject = record.get("subject", {})
    if subject.get("org_id") != charge.get("org_id"):
        return False

    refs = subject.get("refs") or {}

    for key in ("fba_shipment_id", "order_id", "sku", "fnsku"):
        charge_value = charge.get(key)
        ref_value = refs.get(key)
        if charge_value and ref_value and charge_value != ref_value:
            return False

    return subject.get("subject_id") == charge.get("unit_id")



_ALLOWED_UPSTREAM_STAGES = {
    "receiving",
    "prep",
    "pack",
    "returns",
}


def _usable_previous_evidence(
    request: dict[str, Any],
    charge: dict[str, Any],
) -> list[dict[str, Any]]:
    """Accept only completed, hash-valid evidence for this workflow and subject."""
    records: list[dict[str, Any]] = []
    request_subject = request.get("subject", {})
    workflow_id = request.get("workflow_id")

    for record in request.get("previous_evidence", []):
        if not isinstance(record, dict):
            continue

        if record.get("status") != "completed":
            continue

        if record.get("stage") not in _ALLOWED_UPSTREAM_STAGES:
            continue

        if record.get("workflow_id") != workflow_id:
            continue

        if not record.get("record_id"):
            continue

        record_subject = record.get("subject") or {}

        if (
            record_subject.get("org_id") != request_subject.get("org_id")
            or record_subject.get("subject_id")
            != request_subject.get("subject_id")
        ):
            continue

        if not _subject_ref_matches(charge, record):
            continue

        try:
            if not verify(record):
                continue
        except (TypeError, ValueError, KeyError):
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


def _load_fee_lines(
    request: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load explicitly supplied, hash-verified Recovery CSV inputs."""
    root = Path(
        os.environ.get("INPUT_DIR", ROOT / "data" / "input")
    ).resolve()

    subject = request["subject"]
    org_id = subject["org_id"]
    subject_id = subject["subject_id"]

    lines: list[dict[str, Any]] = []
    verified_inputs: list[dict[str, Any]] = []

    for item in request.get("inputs", []):
        ref = item.get("ref")
        expected_hash = item.get("sha256")

        if not isinstance(ref, str) or not ref.strip():
            raise AgentInputError("Recovery input has no valid file reference")

        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise AgentInputError(f"Recovery input has no valid SHA-256: {ref}")

        if any(c not in "0123456789abcdefABCDEF" for c in expected_hash):
            raise AgentInputError(f"Recovery input has an invalid SHA-256: {ref}")

        relative_ref = Path(ref)

        if relative_ref.is_absolute():
            raise AgentInputError(f"Unsafe Recovery input path: {ref}")

        candidate = (root / relative_ref).resolve()

        if not candidate.is_relative_to(root):
            raise AgentInputError(f"Unsafe Recovery input path: {ref}")

        if not candidate.is_file():
            raise AgentInputError(f"Recovery input file not found: {ref}")

        file_bytes = candidate.read_bytes()
        actual_hash = hashlib.sha256(file_bytes).hexdigest()

        if actual_hash.lower() != expected_hash.lower():
            raise AgentInputError(f"SHA-256 mismatch for Recovery input: {ref}")

        # Record only inputs that this loader actually uses.
        if candidate.suffix.lower() != ".csv":
            continue

        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise AgentInputError(f"Recovery CSV is not valid UTF-8: {ref}") from None

        reader = csv.DictReader(io.StringIO(text))

        if not reader.fieldnames:
            raise AgentInputError(f"Recovery CSV has no header: {ref}")

        missing = FEE_REPORT_COLUMNS - set(reader.fieldnames)
        if missing:
            raise AgentInputError(
                f"Recovery CSV {ref} is missing columns: {sorted(missing)}"
            )

        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise AgentInputError(
                    f"Recovery CSV {ref}, row {row_number}: "
                    "row contains more fields than the header"
                )

            if not row.get("line_id") or not row.get("charge_type"):
                raise AgentInputError(
                    f"Recovery CSV {ref}, row {row_number}: "
                    "line_id and charge_type are required"
                )

            if (
                row.get("org_id") != org_id
                or row.get("unit_id") != subject_id
            ):
                raise AgentInputError(
                    f"Recovery CSV {ref}, row {row_number}: "
                    "organization or subject does not match the request"
                )

            try:
                amount = float(row["amount_usd"])
            except (TypeError, ValueError):
                raise AgentInputError(
                    f"Recovery CSV {ref}, row {row_number}: "
                    "amount_usd must be numeric"
                ) from None

            if not math.isfinite(amount):
                raise AgentInputError(
                    f"Recovery CSV {ref}, row {row_number}: "
                    "amount_usd must be finite"
                )

            if row.get("quantity"):
                try:
                    quantity = float(row["quantity"])
                except (TypeError, ValueError):
                    raise AgentInputError(
                        f"Recovery CSV {ref}, row {row_number}: "
                        "quantity must be numeric"
                    ) from None

                if not math.isfinite(quantity) or quantity < 0:
                    raise AgentInputError(
                        f"Recovery CSV {ref}, row {row_number}: "
                        "quantity must be finite and non-negative"
                    )

            row["amount_usd"] = amount
            row["unit_id"] = subject_id
            row["org_id"] = org_id
            lines.append(row)

        verified_inputs.append({
            "ref": ref,
            "sha256": actual_hash,
            "kind": item.get("kind", "document"),
        })

    line_ids = [line["line_id"] for line in lines]
    if len(line_ids) != len(set(line_ids)):
        raise AgentInputError("Recovery inputs contain duplicate fee line IDs")

    return lines, verified_inputs


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

    # Specialist flow has no Prep evidence; do not invent it.
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

    # F-07: Weight-tier charges require valid upstream measurements.
    if charge_type == "fulfilment_fee_weight_tier":
        measurement_records = []

        required = {"weight_g", "length_mm", "width_mm", "height_mm"}

        for record in evidence:
            if record.get("stage") != "prep":
                continue

            measurements = (record.get("payload") or {}).get("measurements")
            if not isinstance(measurements, dict):
                continue

            try:
                valid = all(
                    math.isfinite(float(measurements[key]))
                    and float(measurements[key]) > 0
                    for key in required
                )
            except (KeyError, TypeError, ValueError):
                valid = False

            if valid:
                measurement_records.append(record)

        if not measurement_records:
            return (
                "SILENT",
                "no valid measured weight/dimensions upstream (F-07)",
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
    *,
    model_calls: int = 0,
) -> dict[str, Any]:
    """Return the contract's fail-open pending response."""
    model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    return pending_output(
        request,
        agent_id=AGENT_ID,
        code="gemini_unavailable",
        message=reason,
        retryable=True,
        model=(
            {
                "name": model_name,
                "version": model_name,
                "provider": "google",
                "prompt_version": PROMPT_VERSION,
                "calls": model_calls,
            }
            if model_calls
            else {
                "name": "rules",
                "version": "1",
                "provider": "local",
                "prompt_version": "recovery-rules-v1",
                "calls": 0,
            }
        ),
    )


def _validated_interpretations(
    items: list[dict[str, Any]],
    results: Any,
) -> dict[str, dict[str, Any]]:
    """Reconcile one batch response; malformed or ambiguous lines stay silent."""
    line_ids = [item["charge"]["line_id"] for item in items]
    silent = lambda reason: {
        line_id: {
            "position": "SILENT",
            "reason": reason,
            "evidence_record_ids": [],
            "confidence": None,
        }
        for line_id in line_ids
    }

    if not isinstance(results, list):
        return silent("Gemini batch response did not contain a results list")

    by_line_id: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if not isinstance(result, dict):
            return silent("Gemini batch response contained a malformed result")
        line_id = result.get("line_id")
        if not isinstance(line_id, str) or not line_id:
            return silent("Gemini batch response contained a malformed line ID")
        if line_id not in line_ids:
            return silent("Gemini batch response contained an unknown line ID")
        by_line_id.setdefault(line_id, []).append(result)

    validated: dict[str, dict[str, Any]] = {}
    for item in items:
        line = item["charge"]
        line_id = line["line_id"]
        matches = by_line_id.get(line_id, [])
        if not matches:
            validated[line_id] = {
                "position": "SILENT",
                "reason": "Gemini batch response omitted this fee line",
                "evidence_record_ids": [],
                "confidence": None,
            }
            continue
        if len(matches) != 1:
            validated[line_id] = {
                "position": "SILENT",
                "reason": "Gemini batch response duplicated this fee line",
                "evidence_record_ids": [],
                "confidence": None,
            }
            continue

        result = matches[0]
        position = result.get("position")
        confidence = result.get("confidence")
        reason = result.get("reason")
        evidence_refs = result.get("evidence_record_ids")

        if (
            not isinstance(position, str)
            or position not in {"SUPPORTS", "CONTRADICTS", "SILENT"}
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
            or not isinstance(reason, str)
            or not reason.strip()
            or not isinstance(evidence_refs, list)
            or any(not isinstance(ref, str) for ref in evidence_refs)
        ):
            validated[line_id] = {
                "position": "SILENT",
                "reason": "Gemini returned a malformed interpretation for this fee line",
                "evidence_record_ids": [],
                "confidence": None,
            }
            continue

        available_ids = {
            record["record_id"] for record in item["evidence"]
        }
        traceable_refs = [
            ref for ref in evidence_refs if ref in available_ids
        ]
        if position != "SILENT" and not traceable_refs:
            validated[line_id] = {
                "position": "SILENT",
                "reason": (
                    "model produced a non-silent judgment without "
                    "traceable evidence references"
                ),
                "evidence_record_ids": [],
                "confidence": None,
            }
            continue

        validated[line_id] = {
            "position": position,
            "reason": reason.strip(),
            "evidence_record_ids": traceable_refs,
            "confidence": confidence,
        }

    return validated


def handle(request: dict[str, Any]) -> dict[str, Any]:
    """Normal Round 3 agent entry point."""
    subject = request["subject"]
    subject_id = subject["subject_id"]
    lines, verified_inputs = _load_fee_lines(request)

    checks: list[dict[str, Any]] = []
    charges: list[dict[str, Any]] = []
    unclaimable: list[dict[str, Any]] = []
    claimable_usd = 0.0

    model_calls = 0
    decisions: dict[str, dict[str, Any]] = {}
    model_items: list[dict[str, Any]] = []
    for line in lines:
        evidence = _effective_records(
            request,
            _usable_previous_evidence(request, line),
        )

        deterministic_position, deterministic_reason, deterministic_refs = (
            _deterministic_position(line, evidence)
        )

        if deterministic_position:
            decisions[line["line_id"]] = {
                "position": deterministic_position,
                "reason": deterministic_reason,
                "evidence_record_ids": deterministic_refs,
                "confidence": None,
            }
        elif not evidence:
            decisions[line["line_id"]] = {
                "position": "SILENT",
                "reason": "no usable upstream evidence for this charge",
                "evidence_record_ids": [],
                "confidence": None,
            }
        else:
            model_items.append({"charge": line, "evidence": evidence})

    model_metadata = {
        "name": "rules",
        "version": "1",
        "provider": "local",
        "prompt_version": "recovery-rules-v1",
    }
    if model_items:
        deadline = time.monotonic() + 30.0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _build_pending(
                request,
                "Gemini Recovery interpretation deadline expired",
            )
        try:
            batch = interpret_charges(
                items=model_items,
                timeout_seconds=remaining,
            )
        except GeminiError as exc:
            return _build_pending(
                request,
                f"Gemini Recovery interpretation failed: {exc}",
                model_calls=exc.calls,
            )

        model_calls = batch["calls"]
        model_metadata = {
            "name": batch["model"],
            "version": batch["model"],
            "provider": batch["provider"],
            "prompt_version": batch["prompt_version"],
        }
        decisions.update(
            _validated_interpretations(model_items, batch.get("results"))
        )

    for line in lines:
        amount = float(line.get("amount_usd", 0) or 0)
        interpretation = decisions[line["line_id"]]
        position = interpretation["position"]
        reason = interpretation["reason"]
        evidence_refs = interpretation["evidence_record_ids"]
        confidence = interpretation["confidence"]

        verdict = _position_to_verdict(position)
        outcome = _outcome_for_position(position)

        checks.append(
            check(
                _check_key(line["line_id"]),
                verdict,
                confidence,
                expected="charge supported by evidence",
                observed=position,
                detail=reason,
                evidence_refs=evidence_refs,
                uncertain_reason=(
                    "insufficient_evidence" if verdict == "UNCERTAIN" else None
                ),
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

    if any(c["verdict"] == "FAIL" for c in checks):
        overall_verdict = "FAIL"
    elif any(c["verdict"] == "UNCERTAIN" for c in checks) or not checks:
        overall_verdict = "UNCERTAIN"
    else:
        overall_verdict = "PASS"

    if claimable_usd > 0:
        overall_outcome = "claim_recommended"
    elif any(c["verdict"] == "UNCERTAIN" for c in checks) or not checks:
        overall_outcome = "insufficient_evidence"
    else:
        overall_outcome = "no_claim"

    # Only cite upstream evidence that was actually accepted for a charge.
    used_upstream_refs = {
        ref
        for charge in charges
        for ref in charge["evidence_record_ids"]
    }
    upstream_refs = [
        record["record_id"]
        for record in request.get("previous_evidence", [])
        if record.get("record_id") in used_upstream_refs
    ]

    record = build_record(
        request,
        agent_id=AGENT_ID,
        record_id=_recovery_record_id(
            request,
            verified_inputs,
            upstream_refs,
            charges,
            checks,
            overall_outcome,
            overall_verdict,
        ),
        model={
            **model_metadata,
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
        inputs=verified_inputs,
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