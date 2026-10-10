"""Groq observations pass the same ImageObservation validator and receiving rules."""
import time

from agents.groq_provider import invoke, key_for
from agents.prep.common import Failure as TransportFailure, canonical
from ..config import provider_selection
from ..failures import Failure
from .base import VisionProvider, VisionResponse


class GroqProvider(VisionProvider):
    name = 'groq'

    def __init__(self):
        self.selection = provider_selection()
        try:
            key_for(self.selection)
        except TransportFailure as exc:
            raise Failure('provider_configuration_required' if exc.code == 'provider_unconfigured' else exc.code) from None
        except (ValueError, TypeError, KeyError):
            raise Failure('provider_configuration_invalid') from None

    def analyze(self, req, *, stats, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Failure('agent_timeout')
        started = time.monotonic()
        data, code = invoke({**self.selection, 'deadline_s': remaining}, req.prompt_text,
            {'required_json_schema': req.schema_model.model_json_schema()},
            [{'ref': 'current-image', 'bytes': req.image_bytes, 'media_type': 'image/jpeg'}], stats)
        if code:
            raise Failure(code)
        try:
            parsed = req.schema_model.model_validate(data)
        except Exception:
            raise Failure('model_invalid_response') from None
        return VisionResponse(parsed, canonical(data), stats['version'], req.prompt_version,
                              int((time.monotonic() - started) * 1000), stats.get('usage', {}).get('total_tokens', 0))
