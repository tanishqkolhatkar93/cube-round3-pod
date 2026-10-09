"""Image/provider boundary; optional real adapters are explicitly supplied by callers."""

import hashlib
import io
import warnings
from dataclasses import dataclass
from typing import Protocol

from .domain import Capture, TenantMismatch, ValidationError
from .observations import (
    ImageDescriptor, ObservationBatch, ObservationScope, ProviderResponse,
    parse_response, validate_images, choice, text,
)
from .validation import validate_capture


@dataclass(frozen=True)
class ImageInput:
    scope: ObservationScope
    image_id: str
    evidence_id: str
    reference: str
    image_role: str
    kind: str
    content: bytes | None = None


@dataclass(frozen=True)
class VisionRequest:
    scope: ObservationScope
    images: tuple[ImageDescriptor, ...]
    # Bytes are transient, never written into the normalized model or SQLite.
    image_contents: tuple[bytes | None, ...]
    expected_components: tuple[str, ...]


class VisionProvider(Protocol):
    name: str
    mode: str

    def observe(self, request: VisionRequest) -> ProviderResponse:
        """Batch related images. Real adapters must enforce their own network timeout.

        Return observations only, with actual metadata or null; never policy decisions.
        """
        ...


class ProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FixtureProvider:
    """Replays explicitly supplied synthetic test JSON; it does not analyze images."""
    response_text: str
    name: str = "fixture-json"
    mode: str = "fixture"

    def observe(self, request: VisionRequest) -> ProviderResponse:
        if self.name != "fixture-json" or self.mode != "fixture":
            raise ValidationError("fixture provider cannot impersonate a real provider")
        if any(image.kind != "fixture" for image in request.images):
            raise ValidationError("fixture provider requires explicitly labelled fixture inputs")
        return ProviderResponse(self.response_text, self.name, self.mode)


@dataclass(frozen=True)
class VisionRun:
    scope: ObservationScope
    images: tuple[ImageDescriptor, ...]
    provider_name: str
    provider_mode: str
    status: str
    error_code: str | None
    raw_response: ProviderResponse | None
    observations: ObservationBatch | None


def image_availability(content: bytes | None) -> str:
    if content is None or content == b"":
        return "missing"
    if type(content) is not bytes:
        raise ValidationError("image content must be bytes or unavailable")
    if len(content) > 10_000_000:
        return "unreadable"
    # Reject obvious non-images even when the optional decoder is not installed.
    if not (content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")):
        return "unreadable"
    try:
        from PIL import Image
    except ImportError:
        return "decoder_unavailable"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=("PNG", "JPEG")) as image:
                if image.width * image.height > 20_000_000 or getattr(image, "n_frames", 1) != 1:
                    return "unreadable"
                image.verify()
            with Image.open(io.BytesIO(content), formats=("PNG", "JPEG")) as image:
                image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "unreadable"
    return "available"


def prepare_request(capture: Capture, inputs: tuple[ImageInput, ...], mode: str) -> VisionRequest:
    validate_capture(capture)
    choice(mode, {"fixture", "real"})
    if type(inputs) is not tuple or len(inputs) > 20:
        raise ValidationError("at most 20 image inputs required")
    scope = ObservationScope.from_capture(capture)
    descriptors, contents = [], []
    for image in inputs:
        if not isinstance(image, ImageInput):
            raise ValidationError("ImageInput required")
        if image.scope != scope:
            raise TenantMismatch("input organization/client/unit/record mismatch")
        choice(image.kind, {"fixture", "genuine"})
        if image.kind == "fixture":
            if mode != "fixture" or image.content is not None:
                raise ValidationError("fixture inputs are metadata only and cannot be used with real providers")
            availability = "fixture_only"
        else:
            availability = image_availability(image.content)
        descriptors.append(ImageDescriptor(
            image.scope, image.image_id, image.evidence_id, image.reference, image.image_role,
            "capture_photo_ref", image.kind, availability,
            hashlib.sha256(image.content).hexdigest() if availability == "available" else None,
        ))
        contents.append(image.content if availability == "available" else None)
    images = tuple(descriptors)
    validate_images(capture, images, mode)
    return VisionRequest(scope, images, tuple(contents), tuple(c.raw for c in capture.reference.components))


def observe(capture: Capture, inputs: tuple[ImageInput, ...], provider: VisionProvider | None) -> VisionRun:
    validate_capture(capture)
    scope = ObservationScope.from_capture(capture)
    if provider is None:
        return VisionRun(scope, (), "unconfigured", "unconfigured", "unavailable", "provider_unavailable", None, None)
    text(provider.name)
    choice(provider.mode, {"fixture", "real"})
    # Scope/input violations propagate before any provider call; do not retain foreign inputs.
    request = prepare_request(capture, inputs, provider.mode)

    def failure(code):
        return VisionRun(scope, request.images, provider.name, provider.mode, "unavailable", code, None, None)

    if not request.images or any(i.availability == "missing" for i in request.images):
        return failure("missing_image")
    if any(i.availability == "unreadable" for i in request.images):
        return failure("unreadable_image")
    if any(i.availability == "decoder_unavailable" for i in request.images):
        return failure("image_decoder_unavailable")
    try:
        raw = provider.observe(request)
    except TimeoutError:
        return failure("provider_timeout")
    except ProviderUnavailable:
        return failure("provider_unavailable")
    except Exception:
        return failure("provider_failure")
    if not isinstance(raw, ProviderResponse):
        return failure("invalid_response")
    if raw.provider_name != provider.name or raw.mode != provider.mode:
        return failure("provider_metadata_mismatch")
    if type(raw.text) is str and not raw.text.strip():
        return failure("empty_response")
    try:
        batch = parse_response(capture, request.images, raw)
    except TenantMismatch:
        return failure("response_scope_mismatch")
    except ValidationError:
        # Reject the complete payload, not a best-effort partial interpretation.
        # Do not persist potentially foreign/invalid raw content under this capture.
        diagnostic = getattr(provider, 'diagnose_validation_failure', None)
        if callable(diagnostic):
            try:
                diagnostic(capture, request.images, raw)
            except Exception:
                pass  # Diagnostics must never alter rejection or persistence behavior.
        return failure("invalid_response")
    return VisionRun(scope, request.images, provider.name, provider.mode, "validated", None, raw, batch)


def validate_run(capture: Capture, run: VisionRun) -> None:
    validate_capture(capture)
    if not isinstance(run, VisionRun):
        raise ValidationError("VisionRun required")
    if run.scope != ObservationScope.from_capture(capture):
        raise TenantMismatch("vision run scope mismatch")
    text(run.provider_name)
    choice(run.provider_mode, {"real", "fixture", "unconfigured"})
    if run.provider_mode == "unconfigured" and (
        run.provider_name != "unconfigured" or run.images or run.status != "unavailable"
        or run.error_code != "provider_unavailable"
    ):
        raise ValidationError("unconfigured provider cannot claim an observation run")
    validate_images(capture, run.images, run.provider_mode)
    if run.status == "validated":
        if run.error_code is not None or run.raw_response is None or run.observations is None:
            raise ValidationError("incomplete validated run")
        if run.raw_response.provider_name != run.provider_name or run.raw_response.mode != run.provider_mode:
            raise ValidationError("provider metadata mismatch")
        if parse_response(capture, run.images, run.raw_response) != run.observations:
            raise ValidationError("normalized observations differ from raw response")
    elif run.status == "unavailable":
        choice(run.error_code, {"provider_unavailable", "missing_image", "unreadable_image", "image_decoder_unavailable",
                               "provider_timeout", "provider_failure", "invalid_response", "empty_response",
                               "provider_metadata_mismatch", "response_scope_mismatch"})
        if run.raw_response is not None or run.observations is not None:
            raise ValidationError("failed run cannot carry observations")
    else:
        raise ValidationError("unsupported run status")
