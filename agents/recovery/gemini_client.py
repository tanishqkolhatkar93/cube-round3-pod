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

    def __init__(self, message: str, *, calls: int = 0):
        super().__init__(message)
        self.calls = calls


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


def interpret_charges(
    *,
    items: list[dict[str, Any]],
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Interpret eligible fee lines in one Gemini request."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not configured")

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    prompt = f"""
You are the Recovery evidence interpreter for a financial recovery workflow.

For EACH fee line below, interpret whether its charge is SUPPORTED,
CONTRADICTED, or SILENT based ONLY on evidence supplied for that line.

Do not invent facts, use outside knowledge, decide workflow state, or turn
missing evidence into a contradiction. SILENT means evidence is absent,
insufficient, conflicting, or does not establish whether the charge is valid.
Receiving supplier shortfall does NOT prove a channel-side lost_inbound fee.
Prefer explicit evidence over inference. Return exactly one result per input
line, using its line_id unchanged. Do not add, omit, or duplicate line IDs.

Return ONLY JSON in this shape:
{{
  "results": [
    {{
      "line_id": "fee-line-id",
      "position": "SUPPORTS | CONTRADICTS | SILENT",
      "confidence": 0.0,
      "reason": "short explanation grounded in the supplied evidence",
      "evidence_record_ids": ["record-id-1"]
    }}
  ]
}}

Fee lines and their evidence:
{json.dumps(items, ensure_ascii=False, sort_keys=True)}
""".strip()

    result_schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "line_id": {"type": "string"},
                        "position": {
                            "type": "string",
                            "enum": ["SUPPORTS", "CONTRADICTS", "SILENT"],
                        },
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                        "evidence_record_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "line_id",
                        "position",
                        "confidence",
                        "reason",
                        "evidence_record_ids",
                    ],
                },
            },
        },
        "required": ["results"],
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": result_schema,
            "maxOutputTokens": min(8192, max(300, 250 * len(items))),
        },
    }
    url = f"{GEMINI_API_BASE}/{model}:generateContent"

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
        raise GeminiError(f"Gemini request failed: {exc}", calls=1) from exc
    except ValueError as exc:
        raise GeminiError("Gemini returned invalid JSON", calls=1) from exc

    try:
        result = _extract_json(_extract_text(data))
    except GeminiError as exc:
        raise GeminiError(str(exc), calls=1) from exc

    if not isinstance(result.get("results"), list):
        raise GeminiError("Gemini response results must be an array", calls=1)

    return {
        "results": result["results"],
        "model": model,
        "provider": "google",
        "prompt_version": PROMPT_VERSION,
        "calls": 1,
    }
