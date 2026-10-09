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

import json
import csv
import io
import math
import os
import time
from typing import Any

from shared.utils.errors import AgentInputError
from shared.utils.records import check
from agents import secure_runtime as runtime
from agents.prep.common import fields, text
from .reports import reports, eligible, money, measurements_valid
from .gemini_client import invoke
from .gemini_client import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    GeminiError,
    interpret_charges,
)


STAGE = "recovery"
AGENT_ID = "recovery-manager@2"
POLICY = "owner-recovery-registered-v2"

FEE_REPORT_COLUMNS = {
    "line_id",
    "unit_id",
    "org_id",
    "charge_type",
    "amount_usd",
}


def _load_fee_lines(
    request: dict[str, Any], documents, binding,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load explicitly supplied, hash-verified Recovery CSV inputs."""
    subject = request["subject"]
    org_id = subject["org_id"]
    subject_id = subject["subject_id"]

    lines: list[dict[str, Any]] = []
    verified_inputs: list[dict[str, Any]] = []

    for item in documents:
        ref = item['ref']
        file_bytes = item['bytes']
        if ref.lower().endswith('.json'):
            lines.extend(reports([item], binding))
            verified_inputs.append({k:item[k] for k in ('ref','sha256','kind')})
            continue
        if not ref.lower().endswith('.csv'):
            raise AgentInputError('unsupported_report_format')
        actual_hash = item['sha256']
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise AgentInputError(f"Recovery CSV is not valid UTF-8: {ref}") from None

        reader = csv.DictReader(io.StringIO(text))

        if not reader.fieldnames:
            raise AgentInputError(f"Recovery CSV has no header: {ref}")

        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise AgentInputError("duplicate_columns")
        missing = (FEE_REPORT_COLUMNS | {"workflow_id", "complete", "line_count", "currency", "unit_scope"}) - set(reader.fieldnames)
        if missing:
            raise AgentInputError(
                f"Recovery CSV {ref} is missing columns: {sorted(missing)}"
            )

        rows = list(reader)
        if not rows or len(rows)>200:
            raise AgentInputError("unproven_or_oversized_report")
        for row_number, row in enumerate(rows, start=2):
            if row.get("workflow_id") != request["workflow_id"] or row.get("complete") != "true" or row.get("line_count") != str(len(rows)):
                raise AgentInputError("incomplete_or_foreign_report")
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

            row['amount_usd'] = float(money(row['amount_usd']))
            row['refs'] = {k:row[k] for k in ('order_id','po_number','po_line','sku','fnsku','fba_shipment_id') if row.get(k)}
            # Reuse the established typed fee/scope parser after CSV normalization.
            normalized = {k:row[k] for k in ('line_id','charge_type','amount_usd','currency','unit_scope','refs')}
            envelope = {**{k:binding[k] for k in ('org_id','subject_id','workflow_id')},
                        'complete':True,'line_count':1,'lines':[normalized]}
            normalized = reports([{'bytes':json.dumps(envelope).encode(),'ref':ref}],binding)[0]
            row.update(normalized)
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

    if len(lines)>200:
        raise AgentInputError("too_many_fees")
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

        for record in evidence:
            if record.get("stage") != "prep":
                continue

            measurements = (record.get("payload") or {}).get("measurements")
            if not isinstance(measurements, dict):
                continue

            valid = measurements_valid(record)
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


def _validated_interpretations(
    items: list[dict[str, Any]],
    results: Any,
) -> dict[str, dict[str, Any]]:
    """Reconcile one complete batch; invalid interpretations cannot authorize claims."""
    line_ids = [item["charge"]["line_id"] for item in items]
    def silent(reason):
        raise ValueError('invalid_provider_response')

    if not isinstance(results, list) or len(results)!=len(line_ids):
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
        if len(matches)!=1:
            raise ValueError('missing_or_duplicate_line')

        result = matches[0]
        fields(result, ("line_id","position","confidence","reason","evidence_record_ids"))
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
            raise ValueError('invalid_interpretation')

        available_ids = {
            record["record_id"] for record in item["evidence"]
        }
        if len(set(evidence_refs))!=len(evidence_refs) or not set(evidence_refs)<=available_ids or (position!='SILENT' and not evidence_refs):
            raise ValueError('untraceable_interpretation')
        traceable_refs=evidence_refs

        validated[line_id] = {
            "position": position,
            "reason": reason.strip(),
            "evidence_record_ids": traceable_refs,
            "confidence": confidence,
        }

    return validated


def assess(request, binding, evidence, documents, inputs, failure, provider, rid, fingerprint):
    """Normal Round 3 agent entry point."""
    stats = {'calls':0,'attempts':[]}
    deadline=time.monotonic()+(provider or {}).get('deadline_s',20)
    def pending(code):
        return runtime.output(STAGE,request,binding,inputs,rid,fingerprint,[],
            {'charges':[],'claimable_usd':0,'provider_usage':stats.get('usage',{})},stats,code)
    if failure:
        return pending(failure)
    try:
        lines, verified_inputs = _load_fee_lines(request,documents,binding)
    except (ValueError,TypeError,KeyError,UnicodeError,ArithmeticError):
        return pending('invalid_or_incomplete_report')

    checks: list[dict[str, Any]] = []
    charges: list[dict[str, Any]] = []
    unclaimable: list[dict[str, Any]] = []
    claimable_usd = 0.0

    decisions: dict[str, dict[str, Any]] = {}
    model_items: list[dict[str, Any]] = []
    for line in lines:
        records = eligible(line, evidence)
        if line['charge_type']=='fulfilment_fee_weight_tier':
            records=[r for r in records if r['stage']=='prep' and measurements_valid(r)]

        deterministic_position, deterministic_reason, deterministic_refs = (
            _deterministic_position(line, records)
        )

        if deterministic_position:
            decisions[line["line_id"]] = {
                "position": deterministic_position,
                "reason": deterministic_reason,
                "evidence_record_ids": deterministic_refs,
                "confidence": None,
            }
        elif not records:
            decisions[line["line_id"]] = {
                "position": "SILENT",
                "reason": "no usable upstream evidence for this charge",
                "evidence_record_ids": [],
                "confidence": None,
            }
        else:
            policy = binding.get('fee_policies',{}).get(line['charge_type'])
            if not policy:
                decisions[line['line_id']]={'position':'SILENT','reason':'No registered fee policy',
                    'evidence_record_ids':[],'confidence':None}
                continue
            try:
                fields(policy,('version','text'));text(policy['version']);text(policy['text'])
            except (ValueError,TypeError):
                return pending('invalid_fee_policy')
            model_items.append({'charge':line,'evidence':records,'policy':policy})

    if model_items:
        remaining=deadline-time.monotonic()
        if remaining<=0:return pending('processing_deadline_exceeded')
        if provider:provider={**provider,'deadline_s':remaining}
        try:
            batch, error = invoke(provider, '', {'unresolved':model_items}, [], stats)
        except Exception:
            return pending('provider_failure')
        if error:
            return pending(error)
        try:
            fields(batch, ('results',))
            decisions.update(_validated_interpretations(model_items,batch['results']))
        except (ValueError,TypeError,KeyError):
            return pending('invalid_provider_response')

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
                "charge_"+runtime.digest(line["line_id"])[:16],
                verdict,
                confidence,
                expected="charge supported by evidence",
                observed=position,
                detail=reason,
                evidence_refs=[line["source_ref"],*evidence_refs],
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

    if claimable_usd > 0:
        overall_outcome = "claim_recommended"
    elif any(c["verdict"] == "UNCERTAIN" for c in checks) or not checks:
        overall_outcome = "insufficient_evidence"
    else:
        overall_outcome = "no_claim"

    if not lines:
        checks=[check('complete_report_has_no_fees','PASS',None,expected=0,observed=0,
                      evidence_refs=[i['ref'] for i in inputs])]
        overall_outcome='no_claim'
    return runtime.output(STAGE,request,binding,inputs,rid,fingerprint,checks,
        {'charges':charges,'claimable_usd':round(claimable_usd,2),'unclaimable':unclaimable,
         'provider_usage':stats.get('usage',{}),'report_complete':True},stats,outcome=overall_outcome)


def handle(request):
    return runtime.run(STAGE,request,POLICY,assess)


app = runtime.make_app(STAGE,handle)
