"""Controlled one-JPEG Groq experiment; no retries, redirects or fallback."""
import base64
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .domain import TenantMismatch, ValidationError
from .observations import ProviderResponse
from .ollama import SYSTEM_PROMPT, observation_schema, _unique
from .vision import ProviderUnavailable, VisionRequest

ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'
MODEL = 'qwen/qwen3.8-27b'
MAX_RESPONSE = 2_000_000
USER_AGENT = 'cube-returns-manager/1.0'

# Groq generation guidance only; canonical parsing remains authoritative.
GROQ_SYSTEM_PROMPT = SYSTEM_PROMPT + """
Condition entry rules (check each entry before returning JSON):
- observed: describe the concrete physical feature visibly seen in a nonempty description;
  cite the supplied image evidence ID supporting it.
- not_observed: use only when the relevant area is visible and the feature is not seen.
  A nonempty description must explain that limited visible finding; cite its image and
  include nonempty limitations describing the inspected coverage. This is not proof
  about hidden surfaces.
- conflicting: requires a nonempty description of the conflicting visible findings,
  at least two distinct supplied evidence IDs, and nonempty limitations. With only
  one supplied image/evidence ID, do not emit conflicting.
- unknown or not_visible: description must be null, with nonempty limitations explaining
  why the feature cannot be determined. not_visible must cite the supplied image;
  unknown may have empty evidence_refs.
Never pair observed, not_observed or conflicting with description=null. Never invent
a description to satisfy this rule. If the image does not support a finding, represent
that uncertainty honestly using the rules above, or omit the entry with an explicit
batch limitation. Empty condition arrays are allowed.
Cite only supplied evidence IDs, never invented references. Do not infer a business
condition grade, product authenticity or disposition from these physical observations.
"""


class GroqHTTPFailure(ProviderUnavailable):
    def __init__(self, status):
        self.status = status
        super().__init__('groq_http_error')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderUnavailable('groq_redirect_rejected')


def post_json(url, payload, timeout, key):
    if url != ENDPOINT:
        raise ValidationError('fixed Groq endpoint required')
    body = json.dumps(payload, allow_nan=False).encode()
    if len(body) > 18_000_000:
        raise ValidationError('Groq request too large')
    request = Request(url, data=body, method='POST', headers={
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'User-Agent': USER_AGENT, 'Authorization': 'Bearer ' + key})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise GroqHTTPFailure(response.status)
            return response.status, response.read(MAX_RESPONSE + 1)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise GroqHTTPFailure(status) from None
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise TimeoutError('groq_timeout') from None
        raise ProviderUnavailable('groq_network_error') from None
    except OSError as exc:
        if isinstance(exc, TimeoutError):
            raise TimeoutError('groq_timeout') from None
        raise ProviderUnavailable('groq_network_error') from None


@dataclass(frozen=True)
class GroqConfig:
    api_key: str = field(default='', repr=False)
    timeout_seconds: float = 90

    def __post_init__(self):
        if type(self.api_key) is not str or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise ValidationError('invalid Groq credential configuration')
        try:
            valid = type(self.timeout_seconds) in (float, int) and math.isfinite(self.timeout_seconds) and 0 < self.timeout_seconds <= 240
        except OverflowError:
            valid = False
        if not valid:
            raise ValidationError('invalid Groq timeout')

    @classmethod
    def from_env(cls):
        return cls(os.environ.get('GROQ_API_KEY', ''))


class GroqVisionProvider:
    name, mode = 'groq', 'real'

    def __init__(self, config=None, *, transport=post_json):
        self.config = config if config is not None else GroqConfig.from_env()
        if not isinstance(self.config, GroqConfig) or not callable(transport):
            raise ValidationError('Groq config and transport required')
        self.transport = transport
        self.http_status = None
        self.response_json_parsed = False
        self.observation_json_parsed = False
        self.last_error = None
        self.validation_diagnostic = None

    def diagnose_validation_failure(self, capture, images, response):
        from .observation_diagnostics import diagnose
        self.validation_diagnostic = diagnose(capture, images, response)

    def observe(self, request):
        self.validation_diagnostic = None
        self.http_status = None
        self.response_json_parsed = self.observation_json_parsed = False
        self.last_error = None
        if not self.config.api_key:
            self.last_error = 'groq_key_missing'
            raise ProviderUnavailable(self.last_error)
        if not isinstance(request, VisionRequest) or len(request.images) != 1 or len(request.image_contents) != 1:
            raise ValidationError('one prepared JPEG required')
        image, content = request.images[0], request.image_contents[0]
        if image.scope != request.scope:
            raise TenantMismatch('image scope mismatch')
        if (image.kind != 'genuine' or image.availability != 'available' or type(content) is not bytes
                or not content.startswith(b'\xff\xd8\xff') or len(content) > 10_000_000
                or hashlib.sha256(content).hexdigest() != image.sha256):
            raise ValidationError('validated hash-bound JPEG required')
        context = {'scope': asdict(request.scope), 'evidence_id': image.evidence_id,
                   'image_id': image.image_id, 'image_role': image.image_role,
                   'required_json_schema': observation_schema(request)}
        payload = {'model': MODEL, 'stream': False, 'temperature': 0, 'max_completion_tokens': 4096,
                   'response_format': {'type': 'json_object'},
                   'messages': [{'role': 'system', 'content': GROQ_SYSTEM_PROMPT}, {'role': 'user', 'content': [
                       {'type': 'text', 'text': 'Return only concise grounded observation JSON matching this schema. ' + json.dumps(context)},
                       {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(content).decode('ascii')}}]}]}
        started = time.perf_counter()
        try:
            self.http_status, raw = self.transport(ENDPOINT, payload, self.config.timeout_seconds, self.config.api_key)
        except GroqHTTPFailure as exc:
            self.http_status = exc.status
            self.last_error = 'groq_http_error'
            raise
        except TimeoutError:
            self.last_error = 'groq_timeout'
            raise
        except ProviderUnavailable:
            self.last_error = 'groq_unavailable'
            raise ProviderUnavailable(self.last_error) from None
        elapsed_ms = (time.perf_counter() - started) * 1000
        if self.http_status != 200 or type(raw) is not bytes or len(raw) > MAX_RESPONSE:
            raise ValidationError('invalid Groq response')
        def strict(raw):
            return json.loads(raw, object_pairs_hook=_unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        try:
            envelope = strict(raw.decode('utf-8'))
            self.response_json_parsed = True
            choices = envelope['choices']
            if len(choices) != 1 or choices[0]['finish_reason'] != 'stop':
                raise ValueError('incomplete response')
            message = choices[0]['message']
            if message.get('role') != 'assistant' or message.get('tool_calls') or message.get('refusal'):
                raise ValueError('unsupported response')
            content = message['content']
            if type(content) is not str or type(strict(content)) is not dict:
                raise ValueError('observation JSON object required')
            self.observation_json_parsed = True
        except (ValueError, KeyError, TypeError, RecursionError, IndexError):
            self.last_error = 'groq_invalid_response'
            raise ValidationError(self.last_error) from None
        return ProviderResponse(content, self.name, self.mode, model_version=envelope.get('model'),
            request_id=envelope.get('id'), latency_ms=elapsed_ms,
            token_usage=envelope.get('usage', {}).get('total_tokens'))
