"""Exercise SDK serialization and sanitized errors without network inference."""
import time

import httpx
import pytest
from google import genai
from google.genai import types

from agents.receiving.core.extraction.base import VisionRequest
from agents.receiving.core.extraction.gemini import GeminiProvider
from agents.receiving.core.failures import Failure
from agents.receiving.core.models import ImageObservation


@pytest.mark.parametrize("status,code", [
    (400, "provider_request_rejected"), (401, "provider_authentication_failed"),
    (403, "provider_authentication_failed"), (404, "provider_model_unavailable"),
    (429, "provider_rate_limited"), (503, "provider_overloaded"),
    (500, "provider_http_error"),
])
def test_sdk_http_failure_is_sanitized_and_never_retried(status, code):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"code": status,
            "message": "SECRET provider diagnostic", "status": "UNKNOWN"}})

    provider = GeminiProvider.__new__(GeminiProvider)
    provider.types = types
    provider.models = ["primary", "fallback"]
    provider.client = genai.Client(api_key="offline-placeholder", http_options=types.HttpOptions(
        client_args={"transport": httpx.MockTransport(transport)},
        retry_options=types.HttpRetryOptions(attempts=1)))
    stats = {"calls": 0, "attempts": []}
    try:
        with pytest.raises(Failure) as caught:
            provider.analyze(VisionRequest(b"image", "observe", "v", ImageObservation),
                             stats=stats, deadline=time.monotonic() + 20)
        assert str(caught.value) == code
        assert len(calls) == stats["calls"] == 1
        assert stats["attempts"] == [{"model": "primary", "outcome": code}]
        assert "SECRET" not in str(stats)
    finally:
        provider.close()


@pytest.mark.parametrize("code", ["provider_authentication_failed", "provider_rate_limited",
                                 "provider_overloaded", "provider_model_unavailable",
                                 "provider_request_rejected", "provider_http_error"])
def test_provider_rejection_stops_remaining_images(monkeypatch, code):
    from agents.receiving.core import engine
    from agents.receiving.core.extraction.service import ExtractionService
    calls = []

    def reject(self, sha, image_id, raw, *, stats, deadline):
        calls.append(image_id)
        stats["calls"] += 1
        stats["attempts"].append({"model": "primary", "outcome": code})
        raise Failure(code)

    monkeypatch.setattr(ExtractionService, "observe", reject)
    observations, stats, errors = engine.run_engine([("one.jpg", b"one"), ("two.jpg", b"two")])
    assert calls == ["img_1"]
    assert observations == []
    assert stats["calls"] == 1
    assert stats["attempts"] == [{"model": "primary", "outcome": code}]
    assert errors == [{"image_id": "img_1", "code": code}]
