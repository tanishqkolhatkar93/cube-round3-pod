"""Explicit Gemini REST observation provider. Bounded HTTP retries; no tools or provider fallback."""

import base64
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
import re
import random
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .domain import TenantMismatch, ValidationError
from .observations import ProviderResponse
from .ollama import observation_schema, SYSTEM_PROMPT
from .vision import ProviderUnavailable, VisionRequest

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models/"
MAX_REQUEST_BYTES = 18_000_000
MAX_RESPONSE_BYTES = 2_000_000
# Official standard Free-tier text/image models checked 2026-09-30.
FREE_MODELS = frozenset({"gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"})


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str = field(default="", repr=False)
    model: str = "gemini-3.8-flash"
    timeout_seconds: float = 90
    free_tier_confirmed: bool = False

    def __post_init__(self):
        if not isinstance(self.api_key, str) or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise ValidationError("invalid Gemini credential configuration")
        if type(self.model) is not str or self.model not in FREE_MODELS:
            raise ValidationError("select a documented Free-tier Gemini model")
        try:
            valid = type(self.timeout_seconds) in (int, float) and math.isfinite(self.timeout_seconds) and 0 < self.timeout_seconds <= 600
        except OverflowError:
            valid = False
        if not valid or type(self.free_tier_confirmed) is not bool:
            raise ValidationError("invalid Gemini timeout/free-tier configuration")

    @classmethod
    def from_env(cls):
        try:
            timeout = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "90"))
        except ValueError:
            raise ValidationError("invalid Gemini timeout") from None
        return cls(os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
                   timeout, os.environ.get("GEMINI_FREE_TIER_CONFIRMED") == "1")

    @property
    def endpoint(self):
        return API_ROOT + self.model + ":generateContent"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderUnavailable("gemini_redirect_rejected")


def post_json(url, payload, timeout, api_key, *, max_attempts=3):
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValidationError("one to three Gemini HTTP attempts required")
    if not url.startswith(API_ROOT) or not re.fullmatch(r"gemini-[a-z0-9.-]+:generateContent", url[len(API_ROOT):]):
        raise ValidationError("Gemini endpoint required")
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise ValidationError("Gemini request too large")
    request = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "x-goog-api-key": api_key})
    # Three attempts maximum, sharing one elapsed-time budget. Never retry an
    # ambiguous network timeout or invalid/authentication response.
    deadline = time.monotonic() + timeout
    for attempt in range(max_attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("gemini_timeout")
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=remaining) as response:
                if response.status != 200:
                    raise ProviderUnavailable("gemini_http_error")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            break
        except HTTPError as exc:
            code = {400: "gemini_request_rejected", 401: "gemini_authentication_failed",
                    403: "gemini_authentication_failed", 404: "gemini_model_unavailable",
                    429: "gemini_rate_limited", 503: "gemini_overloaded"}.get(exc.code, "gemini_http_error")
            retryable = exc.code in {429, 500, 502, 503, 504}
            retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
            exc.close()
            delay = random.uniform(0.5, 1.0) * (2 ** attempt)
            if retry_after:
                try:
                    # Don't retry earlier than the server asks. Long/unsupported
                    # Retry-After values fail safely instead of delaying the demo.
                    seconds = float(retry_after)
                    if not math.isfinite(seconds) or seconds < 0 or seconds > 30:
                        retryable = False
                    else:
                        delay = max(delay, seconds)
                except ValueError:
                    retryable = False
            if not retryable or attempt == max_attempts - 1 or delay >= deadline - time.monotonic():
                raise ProviderUnavailable(code) from None
            time.sleep(delay)
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError("gemini_timeout") from None
            raise ProviderUnavailable("gemini_network_error") from None
        except OSError as exc:
            if isinstance(exc, TimeoutError):
                raise TimeoutError("gemini_timeout") from None
            raise ProviderUnavailable("gemini_network_error") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValidationError("Gemini response too large")
    return raw


def generation_schema(request):
    """Adapt only schema syntax; the existing observation parser stays authoritative."""
    def adapt(node):
        if isinstance(node, list):
            return [adapt(v) for v in node]
        if not isinstance(node, dict):
            return node
        if "const" in node:
            return {"type": "null"} if node["const"] is None else {"type": "string", "enum": [node["const"]]}
        if node.get("enum") == [None, "full_expected_area_visible"]:
            return {"anyOf": [{"type": "null"}, {"type": "string", "enum": ["full_expected_area_visible"]}]}
        return {k: adapt(v) for k, v in node.items() if k not in {"maxItems", "maxLength", "minLength", "uniqueItems"}}
    return adapt(observation_schema(request))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("duplicate Gemini JSON field")
        result[key] = value
    return result


class GeminiVisionProvider:
    name = "gemini"
    mode = "real"

    def __init__(self, config=None, *, transport=post_json):
        self.config = config if config is not None else GeminiConfig.from_env()
        if not isinstance(self.config, GeminiConfig) or not callable(transport):
            raise ValidationError("Gemini configuration and transport required")
        self.transport = transport
        self.last_error = None  # Sanitized diagnostic only; never provider text or secrets.

    def observe(self, request):
        self.last_error = None
        if not self.config.api_key or not self.config.free_tier_confirmed:
            self.last_error = "gemini_key_missing" if not self.config.api_key else "gemini_free_tier_confirmation_required"
            raise ProviderUnavailable(self.last_error)
        if not isinstance(request, VisionRequest) or not 1 <= len(request.images) <= 20 or len(request.images) != len(request.image_contents):
            raise ValidationError("prepared image request required")
        parts = []
        for image, content in zip(request.images, request.image_contents):
            if image.scope != request.scope:
                raise TenantMismatch("image scope mismatch")
            if (image.kind != "genuine" or image.availability != "available" or type(content) is not bytes
                    or not content or len(content) > 10_000_000 or hashlib.sha256(content).hexdigest() != image.sha256):
                raise ValidationError("validated genuine image required")
            if content.startswith(b"\x89PNG\r\n\x1a\n"):
                mime = "image/png"
            elif content.startswith(b"\xff\xd8\xff"):
                mime = "image/jpeg"
            else:
                raise ValidationError("PNG/JPEG required")
            parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(content).decode("ascii")}})
        context = {"scope": asdict(request.scope), "images_in_attachment_order": [
            {"image_id": i.image_id, "evidence_id": i.evidence_id, "image_role": i.image_role} for i in request.images],
            "unverified_expected_components_not_visual_facts": request.expected_components}
        payload = {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT +
            "\nBe concise. Do not enumerate every possible feature; preserve material limitations and conflicts."}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(context, separators=(",", ":"))}, *parts]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 4096,
                "responseMimeType": "application/json", "responseJsonSchema": generation_schema(request)}}
        if len(json.dumps(payload, separators=(",", ":")).encode()) > MAX_REQUEST_BYTES:
            raise ValidationError("Gemini request too large")
        started = time.perf_counter()
        try:
            raw = self.transport(self.config.endpoint, payload, self.config.timeout_seconds, self.config.api_key)
        except ProviderUnavailable as exc:
            self.last_error = str(exc) if str(exc) in {"gemini_authentication_failed", "gemini_rate_limited",
                "gemini_http_error", "gemini_network_error", "gemini_redirect_rejected", "gemini_request_rejected",
                "gemini_model_unavailable", "gemini_overloaded"} else "gemini_unavailable"
            raise ProviderUnavailable(self.last_error) from None
        elapsed_ms = (time.perf_counter() - started) * 1000
        if type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES:
            raise ValidationError("bounded Gemini response required")
        try:
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (ValueError, RecursionError):
            raise ValidationError("invalid Gemini JSON") from None
        if type(envelope) is not dict or "error" in envelope or envelope.get("promptFeedback", {}).get("blockReason"):
            raise ValidationError("Gemini blocked or failed")
        candidates = envelope.get("candidates")
        if type(candidates) is not list or len(candidates) != 1 or candidates[0].get("finishReason") != "STOP":
            raise ValidationError("Gemini incomplete or blocked response")
        response_parts = candidates[0].get("content", {}).get("parts")
        if type(response_parts) is not list or not response_parts:
            raise ValidationError("Gemini text required")
        texts = []
        for part in response_parts:
            if type(part) is not dict or set(part) - {"text", "thought", "thoughtSignature"} or type(part.get("text")) is not str:
                raise ValidationError("unexpected Gemini output part")
            if not part.get("thought", False):
                texts.append(part["text"])
        tokens = envelope.get("usageMetadata", {}).get("totalTokenCount")
        if tokens is not None and (type(tokens) is not int or not 0 <= tokens <= 2**63 - 1):
            raise ValidationError("invalid actual token count")
        return ProviderResponse("".join(texts), self.name, self.mode, model_version=envelope.get("modelVersion"),
            request_id=envelope.get("responseId"), latency_ms=elapsed_ms, token_usage=tokens)
