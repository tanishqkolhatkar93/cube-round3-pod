"""Receiving-only validation, trusted capture membership and durable transactions."""
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from shared.utils.schema import errors
from shared.utils.hashing import verify

class Rejected(LookupError):
    def __init__(self, code, status=422):
        self.code, self.status = code, status
        super().__init__(code)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def scope(request):
    s = request["subject"]
    return [s["org_id"], request["workflow_id"], s["subject_id"], request["request_id"]]

def validate_request(request):
    if errors("agent-input", request) or request.get("stage") != "receiving":
        raise Rejected("invalid_receiving_request")
    for value in scope(request):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise Rejected("invalid_receiving_identity")
    if request["previous_evidence"]:
        raise Rejected("unexpected_upstream_evidence")

def safe_ref(ref):
    return (isinstance(ref, str) and bool(ref) and ref == ref.strip()
            and not any(c in ref for c in ("\\", ":", "%"))
            and not any(ord(c) < 32 for c in ref)
            and all(p not in ("", ".", "..") for p in ref.split("/")))

def resolve_captures(request, root, registry_path):
    """Registry is provisioned by a trusted operator, never supplied by the request.
    All registered captures for a subject are required; exact request membership.
    No fallback filename lookup. No symlink/reparse component is accepted.
    """
    doc = {"captures": []}
    if registry_path.exists():
        try:
            doc = json.loads(registry_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise Rejected("capture_registry_invalid", 503) from None
    registrations = doc.get("captures")
    if not isinstance(registrations, list):
        raise Rejected("capture_registry_invalid", 503)
    s = request["subject"]
    owned = {}
    all_refs = set()
    for item in registrations:
        if (not isinstance(item, dict) or not safe_ref(item.get("ref"))
                or not re.fullmatch("[a-f0-9]{64}", str(item.get("sha256", "")))
                or not isinstance(item.get("org_id"), str) or not isinstance(item.get("subject_id"), str)
                or item["ref"] in all_refs):
            raise Rejected("capture_registry_invalid", 503)
        all_refs.add(item["ref"])
        if (item["org_id"], item["subject_id"]) == (s["org_id"], s["subject_id"]):
            owned[item["ref"]] = item
    found, issues, snapshot = [], [], []
    inputs = request.get("inputs", [])
    seen = set()
    for inp in inputs:
        ref = inp["ref"]
        if not safe_ref(ref):
            issues.append({"code": "capture_rejected", "reason": "unsafe_ref"})
            continue
        if ref in seen:
            issues.append({"code": "capture_rejected", "reason": "duplicate_ref"})
            continue
        seen.add(ref)
        binding = owned.get(ref)
        if binding is None:
            issues.append({"code": "capture_rejected", "reason": "unauthorized_capture"})
            continue
        path = root / ref
        # Reject symlinks and Windows junctions before reading any file bytes.
        parts = [root, *[root.joinpath(*ref.split("/")[:i]) for i in range(1, len(ref.split("/")) + 1)]]
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in parts):
            issues.append({"code": "capture_rejected", "reason": "linked_path"})
            continue
        try:
            if not path.resolve().is_relative_to(root.resolve()):
                issues.append({"code": "capture_rejected", "reason": "outside_root"})
                continue
            raw = path.read_bytes()
        except FileNotFoundError:
            issues.append({"code": "upstream_missing", "reason": "missing_capture"})
            continue
        except OSError:
            issues.append({"code": "capture_rejected", "reason": "capture_unreadable"})
            continue
        actual = hashlib.sha256(raw).hexdigest()
        snapshot.append({"ref": ref, "actual_sha256": actual})
        if actual != binding["sha256"] or (inp.get("sha256") is not None and inp["sha256"] != actual):
            issues.append({"code": "capture_rejected", "reason": "hash_mismatch"})
            continue
        found.append(({"ref": ref, "kind": "image", "sha256": actual}, raw))
    if set(owned) - seen:
        issues.append({"code": "upstream_missing", "reason": "required_capture_omitted"})
    if not inputs:
        issues.append({"code": "upstream_missing", "reason": "no_inputs"})
    return found, issues, {"bindings": owned, "bytes": snapshot, "issues": issues}

class Ledger:
    """SQLite write transaction serializes local processes through inference.
    Crash before commit rolls back: retry may repeat inference but cannot replay
    a partial result. No distributed or exactly-once provider-call guarantee.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "requests.sqlite3"

    def execute(self, request, fingerprint, produce):
        key = digest(scope(request))
        with sqlite3.connect(self.db, timeout=60, isolation_level=None) as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (identity TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, output TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT fingerprint, output FROM requests WHERE identity=?", (key,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise Rejected("request_content_conflict", 409)
                result = json.loads(row[1])
                if (errors("agent-output", result) or not verify(result["evidence"])
                        or result["workflow_id"] != request["workflow_id"]
                        or result["stage"] != "receiving"
                        or result["evidence"]["subject"]["org_id"] != request["subject"]["org_id"]
                        or result["evidence"]["subject"]["subject_id"] != request["subject"]["subject_id"]
                        or result["evidence"]["record_id"] != "RCV-" + key):
                    raise Rejected("replay_integrity_error", 503)
                db.commit()
                return result
            output = produce()
            if errors("agent-output", output) or not verify(output["evidence"]):
                raise Rejected("invalid_receiving_output", 503)
            db.execute("INSERT INTO requests VALUES (?,?,?)", (key, fingerprint, json.dumps(output, allow_nan=False)))
            db.commit()
            return output
