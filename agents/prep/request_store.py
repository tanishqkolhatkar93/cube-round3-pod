"""Durable scoped reservation and exact replay; inspired by Test's Returns ledger.

An interrupted reservation is never automatically released or inferred again.
An operator must reconcile it and submit a NEW request ID for a fresh attempt.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from shared.utils.hashing import verify
from shared.utils.schema import validate
from .common import Rejected, canonical, digest


class RequestStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                scope TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                snapshot TEXT NOT NULL, state TEXT NOT NULL, output TEXT, output_hash TEXT,
                PRIMARY KEY(scope, request_id))""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, scope, request_id, fingerprint, snapshot, invoke, wait_seconds=1):
        key = (canonical(scope), request_id)
        deadline = time.monotonic() + wait_seconds
        while True:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT fingerprint,state,output,output_hash FROM requests WHERE scope=? AND request_id=?", key).fetchone()
                if row is None:
                    db.execute("INSERT INTO requests VALUES (?,?,?,?,'running',NULL,NULL)",
                               (*key, fingerprint, canonical(snapshot)))
                    break
                if row[0] != fingerprint:
                    raise Rejected("request_content_conflict", 409)
                if row[1] == "complete":
                    try:
                        out = json.loads(row[2])
                        if digest(out) != row[3] or not verify(out["evidence"]):
                            raise ValueError("corrupt replay")
                        validate("agent-output", out)
                    except (ValueError, KeyError, TypeError):
                        raise Rejected("replay_integrity_failure", 409) from None
                    return out
                if row[1] == "interrupted":
                    raise Rejected("request_interrupted_requires_reconciliation", 409)
            if time.monotonic() >= deadline:
                raise Rejected("request_in_progress_or_interrupted", 409)
            time.sleep(0.01)
        try:
            output = invoke()
            validate("agent-output", output)
            if not verify(output["evidence"]):
                raise ValueError("invalid output hash")
            encoded = canonical(output)
            with self.connect() as db:
                db.execute("UPDATE requests SET state='complete',output=?,output_hash=? WHERE scope=? AND request_id=?",
                           (encoded, digest(output), *key))
            return json.loads(encoded)
        except BaseException:
            with self.connect() as db:
                db.execute("UPDATE requests SET state='interrupted' WHERE scope=? AND request_id=?", key)
            raise
