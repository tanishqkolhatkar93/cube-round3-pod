"""Durable reservations: a crashed invocation is never silently repeated."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class Rejected(LookupError):
    """Compatible with the starter's in-process AgentRejected boundary."""
    def __init__(self, code, status=422):
        self.code, self.status = code, status
        super().__init__(code)


class RequestStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                tenant TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                snapshot TEXT NOT NULL, state TEXT NOT NULL, output TEXT, output_hash TEXT,
                PRIMARY KEY (tenant, request_id))""")

    @contextmanager
    def connect(self):
        # A fresh connection per operation also supports threads and separate workers.
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, tenant, request_id, fingerprint, snapshot, invoke, wait_seconds=5):
        key = (canonical(tenant), request_id)
        deadline = time.monotonic() + wait_seconds
        while True:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT fingerprint,state,output,output_hash FROM requests "
                                 "WHERE tenant=? AND request_id=?", key).fetchone()
                if row is None:
                    db.execute("INSERT INTO requests VALUES (?,?,?,?, 'running',NULL,NULL)",
                               (*key, fingerprint, canonical(snapshot)))
                    break
                if row[0] != fingerprint:
                    raise Rejected("request_content_conflict", 409)
                if row[1] == "complete":
                    output = json.loads(row[2])
                    if digest(output) != row[3]:
                        raise Rejected("replay_storage_corrupt", 409)
                    return output
                if row[1] == "interrupted":
                    raise Rejected("request_interrupted_requires_reconciliation", 409)
            if time.monotonic() >= deadline:
                raise Rejected("request_in_progress_or_interrupted", 409)
            time.sleep(0.02)
        try:
            output = invoke()
            encoded = canonical(output)
            with self.connect() as db:
                db.execute("UPDATE requests SET state='complete',output=?,output_hash=? "
                           "WHERE tenant=? AND request_id=?", (encoded, digest(output), *key))
            return json.loads(encoded)
        except BaseException:
            # Do not release the key: an external invocation may already have happened.
            with self.connect() as db:
                db.execute("UPDATE requests SET state='interrupted' WHERE tenant=? AND request_id=?", key)
            raise
