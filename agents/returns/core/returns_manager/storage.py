"""Tenant-bound SQLite repository for trusted local callers, not authentication.

All public lookups include organization AND client scope. Image bytes are never served.
The owner of the SQLite file can read it; host/file access remains a deployment concern.
"""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .domain import Assessment, Capture, TenantContext, TenantMismatch, ValidationError, identifier
from .rules import assess
from .validation import validate_capture


class ConflictError(ValueError):
    """Same scoped record ID submitted with different lineage; no overwrite allowed."""


def encode(value) -> str:
    return json.dumps(asdict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Store:
    def __init__(self, path: Path, context: TenantContext):
        if not isinstance(context, TenantContext):
            raise ValidationError("trusted TenantContext required")
        self.context = context
        # JSON null is an internal SQL scope key, not a generated client identifier.
        self._scope = (context.organization_id, json.dumps(context.client_id))
        self._db = sqlite3.connect(path)
        self._db.execute("""CREATE TABLE IF NOT EXISTS captures (
            organization_id TEXT NOT NULL,
            client_scope TEXT NOT NULL,
            record_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            assessment TEXT,
            processing_error TEXT,
            PRIMARY KEY (organization_id, client_scope, record_id)
        )""")
        # Additive Phase 2 storage: never replace a Phase 1 assessment.
        self._db.execute("""CREATE TABLE IF NOT EXISTS vision_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id TEXT NOT NULL,
            client_scope TEXT NOT NULL,
            record_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            assessment TEXT NOT NULL
        )""")
        self._db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._db.close()

    def save_capture(self, capture: Capture) -> bool:
        validate_capture(capture)
        if capture.tenant != self.context:
            raise TenantMismatch("organization/client context mismatch")
        payload = encode(capture)
        with self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO captures VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                (*self._scope, capture.record_id, capture.unit.unit_id, payload),
            )
            existing = self._db.execute(
                "SELECT payload FROM captures WHERE organization_id=? AND client_scope=? AND record_id=?",
                (*self._scope, capture.record_id),
            ).fetchone()[0]
            if existing != payload:
                raise ConflictError("record_id already exists with different input lineage")
            return cursor.rowcount == 1

    def save_assessment(self, capture: Capture, assessment: Assessment) -> None:
        from .observations import ObservationBatch

        if isinstance(assessment, Assessment) and isinstance(assessment.observation, ObservationBatch):
            raise ValidationError("vision observations require save_vision_attempt with the raw response")
        # Prevent mismatched/manual fabricated results from being attached to a capture.
        if not isinstance(assessment, Assessment) or assessment != assess(capture, assessment.observation, assessment.decision_reference):
            raise ValidationError("assessment does not match Phase 1 rules")
        self.save_capture(capture)
        payload = encode(assessment)
        with self._db:
            self._db.execute(
                "UPDATE captures SET assessment=?, processing_error=NULL WHERE organization_id=? AND client_scope=? "
                "AND record_id=? AND assessment IS NULL", (payload, *self._scope, capture.record_id),
            )
            existing = self._db.execute(
                "SELECT assessment FROM captures WHERE organization_id=? AND client_scope=? AND record_id=?",
                (*self._scope, capture.record_id),
            ).fetchone()[0]
            if existing != payload:
                raise ConflictError("existing assessment cannot be silently replaced")

    def record_failure(self, capture: Capture, error_code: str) -> None:
        identifier(error_code, "error_code")
        self.save_capture(capture)
        with self._db:
            self._db.execute(
                "UPDATE captures SET processing_error=? WHERE organization_id=? AND client_scope=? "
                "AND record_id=? AND assessment IS NULL",
                (error_code, *self._scope, capture.record_id),
            )

    @staticmethod
    def _decode(row):
        return {"capture": json.loads(row[0]),
                "assessment": json.loads(row[1]) if row[1] is not None else None,
                "status": "pending_review", "processing_error": row[2]}

    def get(self, record_id: str) -> dict | None:
        identifier(record_id, "record_id")
        row = self._db.execute(
            "SELECT payload, assessment, processing_error FROM captures WHERE organization_id=? AND client_scope=? AND record_id=?",
            (*self._scope, record_id),
        ).fetchone()
        return self._decode(row) if row else None

    def for_unit(self, unit_id: str) -> list[dict]:
        identifier(unit_id, "unit_id")
        rows = self._db.execute(
            "SELECT payload, assessment, processing_error FROM captures WHERE organization_id=? AND client_scope=? "
            "AND unit_id=? ORDER BY record_id", (*self._scope, unit_id),
        ).fetchall()
        return [self._decode(row) for row in rows]

    def evidence_reference(self, record_id: str, reference: str) -> dict | None:
        record = self.get(record_id)
        if record is None:
            return None
        return next((image for image in record["capture"]["images"]
                     if image["reference"] == reference), None)

    def save_vision_attempt(self, capture: Capture, run, assessment: Assessment) -> int:
        from .vision import validate_run
        from .domain import ObservationPlaceholder

        if capture.tenant != self.context:
            raise TenantMismatch("vision persistence scope mismatch")
        validate_run(capture, run)
        observation = run.observations if run.observations is not None else ObservationPlaceholder(run.error_code)
        if not isinstance(assessment, Assessment) or assessment != assess(capture, observation, assessment.decision_reference):
            raise ValidationError("vision assessment must match validated run")
        self.save_capture(capture)
        with self._db:
            cursor = self._db.execute(
                "INSERT INTO vision_attempts (organization_id, client_scope, record_id, unit_id, payload, assessment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (*self._scope, capture.record_id, capture.unit.unit_id, encode(run), encode(assessment)),
            )
            return cursor.lastrowid

    def vision_attempts(self, record_id: str) -> list[dict]:
        identifier(record_id, "record_id")
        rows = self._db.execute(
            "SELECT attempt_id, payload, assessment FROM vision_attempts "
            "WHERE organization_id=? AND client_scope=? AND record_id=? ORDER BY attempt_id",
            (*self._scope, record_id),
        ).fetchall()
        return [{"attempt_id": row[0], "run": json.loads(row[1]), "assessment": json.loads(row[2])} for row in rows]
