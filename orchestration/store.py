"""Local storage with verified evidence and explicit tenant-scoped handles.

MemoryStore/FileStore are privileged backends for trusted local CLI/library use.
Untrusted request paths MUST receive for_org(org_id, actor=...) from an authenticated
server context. A scope is authorization context, not a credential supplied by a client.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from shared.utils.hashing import verify


class EvidenceConflict(Exception):
    pass


class StoreIntegrityError(EvidenceConflict):
    pass


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError("invalid storage identifier")
    return value


def _copy(value):
    return json.loads(json.dumps(value))


def _verified(record, record_id):
    if record is not None and (record.get("record_id") != record_id or not verify(record)):
        raise StoreIntegrityError("stored evidence failed integrity validation")
    return _copy(record)


class TenantStore:
    """Capabilities for one org; foreign lookups are indistinguishable from missing."""
    def __init__(self, backend, org_id, actor=None):
        self._backend, self.org_id, self.actor = backend, identifier(org_id), actor

    def for_org(self, org_id, *, actor=None):
        if org_id != self.org_id or (actor is not None and actor != self.actor):
            raise PermissionError("tenant scope cannot be changed")
        return self

    def transaction(self):
        return self._backend.transaction()

    def load_workflow(self, workflow_id):
        wf = self._backend.load_workflow(workflow_id)
        return wf if wf and wf["org_id"] == self.org_id else None

    def save_workflow(self, wf):
        if wf["org_id"] != self.org_id:
            raise PermissionError("foreign workflow")
        self._backend.save_workflow(wf)

    def get_evidence(self, record_id):
        rec = self._backend.get_evidence(record_id)
        return rec if rec and rec["subject"]["org_id"] == self.org_id else None

    def put_evidence(self, record):
        if record["subject"]["org_id"] != self.org_id:
            raise PermissionError("foreign evidence")
        self._backend.put_evidence(record)


class MemoryStore:
    def __init__(self):
        self.workflows, self.evidence = {}, {}
        self._lock = threading.RLock()

    def for_org(self, org_id, *, actor=None):
        return TenantStore(self, org_id, actor)

    @contextmanager
    def transaction(self):
        with self._lock:
            yield

    def load_workflow(self, workflow_id):
        identifier(workflow_id)
        with self.transaction():
            return _copy(self.workflows.get(workflow_id))

    def save_workflow(self, wf):
        identifier(wf["workflow_id"])
        identifier(wf["org_id"])
        with self.transaction():
            old = self.load_workflow(wf["workflow_id"])
            if old and (old["org_id"], old["subject_id"]) != (wf["org_id"], wf["subject_id"]):
                raise EvidenceConflict("workflow identity cannot change")
            self.workflows[wf["workflow_id"]] = _copy(wf)

    def get_evidence(self, record_id):
        identifier(record_id)
        with self.transaction():
            return _verified(self.evidence.get(record_id), record_id)

    def put_evidence(self, record):
        identifier(record["record_id"])
        record = _verified(record, record["record_id"])
        with self.transaction():
            existing = self.get_evidence(record["record_id"])
            if existing is not None and existing != record:
                raise EvidenceConflict("record ID already exists with different evidence")
            self.evidence.setdefault(record["record_id"], record)


class FileStore(MemoryStore):
    """Single-host local filesystem store. Mutations serialize across processes.

The coarse lock deliberately prioritizes correctness over throughput. It is held
through workflow mutations, including agent execution. Not a distributed lock.
"""
    def __init__(self, root=None):
        super().__init__()
        self.root = Path(root or os.environ.get("OUT_DIR", "out")).resolve()
        for folder in ("workflows", "evidence"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    @contextmanager
    def transaction(self):
        with self._lock:
            depth = getattr(self._local, "depth", 0)
            if depth:
                self._local.depth += 1
                try:
                    yield
                finally:
                    self._local.depth -= 1
                return
            with (self.root / ".store.lock").open("a+b") as lock:
                if os.name == "nt":
                    import msvcrt
                    lock.seek(0, 2)
                    if lock.tell() == 0:
                        lock.write(b"0")
                        lock.flush()
                else:
                    import fcntl
                deadline = time.monotonic() + 60
                while True:
                    try:
                        if os.name == "nt":
                            lock.seek(0)
                            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except (OSError, BlockingIOError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("store busy") from None
                        time.sleep(0.02)
                self._local.depth = 1
                try:
                    yield
                finally:
                    self._local.depth = 0
                    if os.name == "nt":
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _path(self, folder, key):
        identifier(key)
        p = (self.root / folder / (key + ".json")).resolve()
        if p.parent != self.root / folder:
            raise ValueError("storage path outside designated directory")
        return p

    def _read(self, folder, key):
        p = self._path(folder, key)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, UnicodeError):
            raise StoreIntegrityError("stored JSON is invalid") from None

    def _write(self, folder, key, value):
        p = self._path(folder, key)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=p.parent,
                                             prefix=".store-", suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                json.dump(value, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, p)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load_workflow(self, workflow_id):
        with self.transaction():
            wf = self._read("workflows", workflow_id)
            if wf is not None and wf.get("workflow_id") != workflow_id:
                raise StoreIntegrityError("stored workflow identity mismatch")
            return wf

    def save_workflow(self, wf):
        identifier(wf["org_id"])
        with self.transaction():
            old = self.load_workflow(wf["workflow_id"])
            if old and (old["org_id"], old["subject_id"]) != (wf["org_id"], wf["subject_id"]):
                raise EvidenceConflict("workflow identity cannot change")
            self._write("workflows", wf["workflow_id"], wf)

    def get_evidence(self, record_id):
        with self.transaction():
            return _verified(self._read("evidence", record_id), record_id)

    def put_evidence(self, record):
        record = _verified(record, record["record_id"])
        with self.transaction():
            existing = self.get_evidence(record["record_id"])
            if existing is not None and existing != record:
                raise EvidenceConflict("record ID already exists with different evidence")
            if existing is None:
                self._write("evidence", record["record_id"], record)
