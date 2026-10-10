"""Small Gemini REST client for the Recovery agent."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx
from agents.prep.common import strict_json, canonical
from agents import bounded_provider
from agents.readiness import provider_http_error, PROVIDER_HTTP_ERRORS


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
        if len(data.get('candidates',[])) != 1 or data['candidates'][0].get('finishReason') != 'STOP' or data.get('promptFeedback',{}).get('blockReason'):
            raise GeminiError('incomplete_provider_response')
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
        value = strict_json(cleaned)
        canonical(value)
    except ValueError as exc:
        raise GeminiError("Gemini response was not valid JSON") from exc

    if not isinstance(value, dict):
        raise GeminiError("Gemini response JSON must be an object")

    return value


def interpret_charges(
    *,
    items: list[dict[str, Any]],
    timeout_seconds: float = 30.0,
    selection=None, key=None, report=None,
) -> dict[str, Any]:
    """Interpret eligible fee lines in one Gemini request."""
    api_key = key if key is not None else os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not configured")

    model = selection["model"] if selection else os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
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

    report = report or (lambda event: None)
    client = None
    calls = 0
    try:
        client = httpx.Client(timeout=timeout_seconds,follow_redirects=False)
        report({'event':'attempt','model':model});calls=1
        response = client.post(url,headers={'x-goog-api-key':api_key,'Content-Type':'application/json'},json=body)
        response.raise_for_status()
        data = response.json()
        version = data.get('modelVersion','unknown')
        if not isinstance(version,str) or not version or len(version)>200:raise ValueError()
        report({'event':'accounting','version':version})
        usage=data.get('usageMetadata',{})
        if not isinstance(usage,dict):raise ValueError()
        usage={k:usage[k] for k in ('promptTokenCount','candidatesTokenCount','cachedContentTokenCount','totalTokenCount') if k in usage}
        if any(type(v) is not int or v<0 for v in usage.values()):raise ValueError()
        report({'event':'accounting','version':version,'usage':usage})
        result = _extract_json(_extract_text(data))
        if not isinstance(result.get('results'),list):raise ValueError()
    except httpx.TimeoutException:
        raise GeminiError('provider_timeout',calls=calls) from None
    except httpx.HTTPStatusError as exc:
        raise GeminiError(provider_http_error(exc.response.status_code), calls=calls) from None
    except (ValueError,TypeError,KeyError,GeminiError):
        raise GeminiError('invalid_provider_response',calls=calls) from None
    except Exception:
        raise GeminiError('provider_unavailable',calls=calls) from None
    finally:
        active_error = sys.exc_info()[0] is not None
        if client is not None:
            try:client.close()
            except Exception:
                # Keep an earlier provider failure; accounting has already crossed the pipe.
                if not active_error:raise GeminiError('provider_cleanup_failure',calls=calls) from None

    return {
        "results": result["results"],
        "model": model,
        "provider": "google",
        "prompt_version": PROMPT_VERSION,
        "calls": 1,
    }


def worker(connection,selection,key,prompt,payload,images):
    try:
        batch=interpret_charges(items=payload['unresolved'],timeout_seconds=selection['deadline_s'],
            selection=selection,key=key,report=connection.send)
        result={'data':{'results':batch['results']}}
    except GeminiError as exc:
        result={'error':str(exc) if str(exc) in {'provider_timeout','provider_cleanup_failure','invalid_provider_response','provider_unavailable', *PROVIDER_HTTP_ERRORS} else 'provider_unavailable'}
    except Exception:
        result={'error':'provider_unavailable'}
    try:connection.send({'event':'result',**result})
    finally:connection.close()


def invoke(selection,prompt,payload,images,stats):
    if selection and selection.get('kind') == 'groq':
        from agents.groq_provider import invoke as groq_invoke
        prompt = ('Interpret each supplied fee line using only its registered policy and eligible evidence. '
                  'Return {"results":[{"line_id":"supplied line ID","position":"SUPPORTS or CONTRADICTS or SILENT",'
                  '"confidence":0.0,"reason":"grounded explanation","evidence_record_ids":[]}]}. '
                  'Return exactly one entry per line. Cite only supplied evidence record IDs. '
                  'Missing, conflicting or insufficient evidence must be SILENT; never invent a claim.')
        return groq_invoke(selection, prompt, payload, [], stats)
    return bounded_provider.invoke(selection,prompt,payload,images,stats,worker_target=worker)
