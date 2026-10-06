"""Small Gemini REST client for the Recovery agent."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3-flash-preview"
PROMPT_VERSION = "recovery-v1"


class GeminiError(RuntimeError):
    """Raised when Gemini cannot produce a usable response."""


def _extract_text(data: dict[str, Any]) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict)
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiError("Gemini returned an unexpected response shape") from exc

    if not text:
        raise GeminiError("Gemini returned an empty response")

    return text


def _extract_json(text: str) -> dict[str, Any]:
    """Accept strict JSON or JSON wrapped in a markdown code fence."""
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini response was not valid JSON") from exc

    if not isinstance(value, dict):
        raise GeminiError("Gemini response JSON must be an object")

    return value


def interpret_charge(
    *,
    charge: dict[str, Any],
    evidence: list[dict[str, Any]],
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Ask Gemini to interpret whether the fee charge is supported by evidence.

    Gemini only interprets evidence. The Recovery policy remains authoritative
    about PASS/FAIL/UNCERTAIN and claimability.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not configured")

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    prompt = f"""
You are the Recovery evidence interpreter for a financial recovery workflow.

Your ONLY task is to interpret whether the specific fee charge below is
SUPPORTED, CONTRADICTED, or SILENT based ONLY on the supplied evidence.

Do not invent facts.
Do not use outside knowledge.
Do not turn missing evidence into a contradiction.
Do not decide workflow state.

Recovery semantics:
- SUPPORTS means the evidence supports the charge being valid.
- CONTRADICTS means the evidence contradicts the charge being valid.
- SILENT means the evidence is absent, insufficient, conflicting, or does not
  establish whether the charge is valid.

Important:
- Receiving supplier shortfall does NOT prove a channel-side lost_inbound fee.
- A $0.00 charge is handled by deterministic Recovery rules outside you.
- If evidence from different records conflicts, return SILENT.
- Prefer explicit evidence over inference.

Return ONLY JSON with exactly these fields:
{{
  "position": "SUPPORTS | CONTRADICTS | SILENT",
  "confidence": 0.0,
  "reason": "short explanation grounded in the supplied evidence",
  "evidence_record_ids": ["record-id-1"]
}}

Charge:
{json.dumps(charge, ensure_ascii=False, sort_keys=True)}

Previous evidence:
{json.dumps(evidence, ensure_ascii=False, sort_keys=True)}
""".strip()

    url = f"{GEMINI_API_BASE}/{model}:generateContent"

    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                ]
            }
        ],
    "generationConfig": {
        "temperature": 0,
        "responseMimeType": "application/json",
        "responseJsonSchema": {
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "enum": ["SUPPORTS", "CONTRADICTS", "SILENT"]
                },
                "confidence": {
                    "type": "number"
                },
                "reason": {
                    "type": "string"
                },
                "evidence_record_ids": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                }
            },
            "required": [
                "position",
                "confidence",
                "reason",
                "evidence_record_ids"
            ]
        },
        "maxOutputTokens": 300,
    },
    }

    try:
        response = httpx.post(
            url,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise GeminiError(f"Gemini request failed: {exc}") from exc
    except ValueError as exc:
        raise GeminiError("Gemini returned invalid JSON") from exc

    result = _extract_json(_extract_text(data))

    position = result.get("position")
    if position not in {"SUPPORTS", "CONTRADICTS", "SILENT"}:
        raise GeminiError(f"Invalid Gemini position: {position!r}")

    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    reason = str(result.get("reason", "")).strip()
    evidence_record_ids = result.get("evidence_record_ids", [])

    if not isinstance(evidence_record_ids, list):
        evidence_record_ids = []

    return {
        "position": position,
        "confidence": confidence,
        "reason": reason,
        "evidence_record_ids": [
            str(record_id) for record_id in evidence_record_ids
        ],
        "model": model,
        "provider": "google",
        "prompt_version": PROMPT_VERSION,
        "calls": 1,
    }