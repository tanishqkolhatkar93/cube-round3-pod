"""Persist accepted input before rule execution so interruptions do not lose it."""

from .domain import ObservationPlaceholder
from .rules import assess
from .storage import Store
from .validation import parse_record, validate_decision_reference


def ingest(row, source, store: Store) -> dict:
    capture = parse_record(row, store.context, source)
    store.save_capture(capture)
    existing = store.get(capture.record_id)
    if existing["assessment"] is not None:
        return existing
    try:
        result = assess(capture, ObservationPlaceholder())
    except Exception as exc:
        # Capture is already committed and remains pending_review, with no result.
        # Store only the exception type, not potentially sensitive provider text.
        store.record_failure(capture, type(exc).__name__)
        # Propagate failure to the caller instead of reporting fabricated success.
        raise
    store.save_assessment(capture, result)
    return store.get(capture.record_id)


def inspect_capture(row, source, store: Store, images, provider=None, *, reference=None) -> int:
    """Explicit observation attempt, separate from idempotent Phase 1 CSV ingestion.

    Retains the original capture/assessment. Returns an actual local attempt ID,
    never a fabricated provider request ID. Repeat calls append separate attempts.
    """
    from .vision import observe

    capture = parse_record(row, store.context, source)
    if reference is not None:
        validate_decision_reference(capture, reference)
    store.save_capture(capture)
    run = observe(capture, images, provider)
    observation = run.observations if run.observations is not None else ObservationPlaceholder(run.error_code)
    result = assess(capture, observation, reference)
    return store.save_vision_attempt(capture, run, result)
