"""Only trusted configuration selects sources; request paths are never opened."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3

from .core.returns_manager.domain import (
    Component, DecisionReference, ObservationPlaceholder, TenantContext,
    CollectionLineage, lineage_from_dict,
)
from .core.returns_manager.validation import read_csv, parse_record, validate_decision_reference
from .core.returns_manager.observations import (
    ImageDescriptor, ObservationScope, ProviderResponse, parse_response,
)
from .core.returns_manager.vision import ImageInput, VisionRun, prepare_request, validate_run
from .core.returns_manager.rules import assess
from .request_store import Rejected, canonical, digest

SAMPLE_SHA256 = "0cca916d25c9db57495420e4c02cebd1ac298de9fa3f9f148fe3e9289e9b3103"


def safe_ref(ref):
    if (not isinstance(ref, str) or not ref or "\\" in ref or ":" in ref or "%" in ref
            or ref.startswith("/") or any(p in ("", ".", "..") for p in ref.split("/"))
            or any(ord(c) < 32 for c in ref)):
        raise Rejected("unsupported_source_reference")
    return ref


def local_path(root, relative):
    safe_ref(relative)
    path = (root / PurePosixPath(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise Rejected("source_path_escape")
    return path


def reference_from(value):
    if value is None:
        return None
    fields = dict(value)
    expected = fields.pop("source_sha256")
    fields["tenant"] = TenantContext(**fields["tenant"])
    fields["components"] = tuple(Component(**c) for c in fields["components"])
    ref = DecisionReference(**fields)
    if ref.source_sha256 != expected:
        raise Rejected("reference_hash_mismatch")
    return ref


def scope_from(value):
    return ObservationScope(TenantContext(**value["tenant"]), value["unit_id"], value["record_id"])


def run_from(capture, value):
    images = tuple(ImageDescriptor(**{**i, "scope": scope_from(i["scope"])}) for i in value["images"])
    raw = ProviderResponse(**value["raw_response"]) if value["raw_response"] is not None else None
    batch = parse_response(capture, images, raw) if raw is not None else None
    run = VisionRun(scope_from(value["scope"]), images, value["provider_name"], value["provider_mode"],
                    value["status"], value["error_code"], raw, batch)
    validate_run(capture, run)
    if canonical(asdict(run)) != canonical(value):
        raise Rejected("stored_run_tampered")
    return run


@dataclass
class Resolved:
    capture: object
    reference: object
    images: tuple
    run: object
    snapshot: dict
    inputs: list
    inspection: str


class Resolver:
    def __init__(self, config, root):
        # Copy caller-owned configuration; no mutable request state is retained.
        self.config = json.loads(canonical(config))
        self.root = Path(root).resolve()
        if config.get("mode") not in ("synthetic", "existing"):
            raise Rejected("explicit_source_mode_required")
        scopes = [TenantContext(**t) for t in config["tenants"]]
        if not scopes or len({t.organization_id for t in scopes}) != len(scopes):
            # Wire contract cannot select client; use a separate service per client.
            raise Rejected("ambiguous_tenant_configuration")
        if config["mode"] == "existing" and any(t.client_id is None for t in scopes):
            raise Rejected("explicit_client_scope_required")
        self.tenants = {t.organization_id: t for t in scopes}

    def resolve(self, request):
        subject = request["subject"]
        tenant = self.tenants.get(subject["org_id"])
        if tenant is None:
            raise Rejected("source_not_found", 404)
        if self.config["mode"] == "synthetic":
            result = self.synthetic(tenant, subject["subject_id"])
        else:
            result = self.existing(tenant, subject["subject_id"])
        # Submitted refs are assertions against the registry, never file locators.
        registered = {i["ref"]: i for i in result.inputs}
        seen = set()
        for item in request.get("inputs", []):
            ref = safe_ref(item["ref"])
            if ref in seen or ref not in registered:
                raise Rejected("unregistered_or_duplicate_reference")
            seen.add(ref)
            actual = registered[ref]
            if item.get("kind", actual["kind"]) != actual["kind"]:
                raise Rejected("input_kind_mismatch")
            if item.get("sha256") != actual.get("sha256"):
                raise Rejected("input_hash_mismatch")
        return result

    def synthetic(self, tenant, unit):
        path = local_path(self.root, self.config["csv"])
        rows = read_csv(path)
        if not rows or any(s.source_sha256 != SAMPLE_SHA256 for _, s in rows):
            raise Rejected("organizer_source_tampered")
        matches = [(r, s) for r, s in rows if r["org_id"] == tenant.organization_id and r["unit_id"] == unit]
        if not matches:
            raise Rejected("source_not_found", 404)
        if len(matches) != 1:
            raise Rejected("ambiguous_capture_binding")
        row, source = matches[0]
        capture = parse_record(row, tenant, source)
        inputs = [{"ref": f"{source.source_name}#row={source.row_number}", "kind": "csv_row",
                   "sha256": source.source_sha256}]
        inputs += [{"ref": safe_ref(i.reference), "kind": "image", "sha256": None} for i in capture.images]
        return Resolved(capture, None, (), None,
                        {"mode": "synthetic", "capture": asdict(capture), "missing_photos": True},
                        inputs, "unavailable")

    def existing(self, tenant, unit):
        matches = [b for b in self.config["bindings"]
                   if b["organization_id"] == tenant.organization_id and b["unit_id"] == unit]
        if not matches:
            raise Rejected("source_not_found", 404)
        if len(matches) != 1:
            raise Rejected("ambiguous_capture_binding")
        binding = matches[0]
        action = binding["inspection"]
        if action not in ("stored", "live") or (action == "stored") != ("attempt_id" in binding):
            raise Rejected("explicit_inspection_selection_required")
        path = local_path(self.root, binding["database"])
        params = (tenant.organization_id, json.dumps(tenant.client_id), binding["record_id"], unit)
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            row = db.execute("SELECT payload FROM captures WHERE organization_id=? AND client_scope=? "
                             "AND record_id=? AND unit_id=?", params).fetchone()
            if row is None:
                raise Rejected("source_not_found", 404)
            value = json.loads(row[0])
            if digest(value) != binding["capture_sha256"] or value["tenant"] != asdict(tenant):
                raise Rejected("capture_hash_or_scope_mismatch")
            capture = parse_record(dict(value["raw_fields"]), tenant, lineage_from_dict(value["source"]))
            if capture.record_id != binding["record_id"] or capture.unit.unit_id != unit:
                raise Rejected("capture_binding_mismatch")
            if canonical(asdict(capture)) != canonical(value):
                raise Rejected("capture_lineage_mismatch")
            # The wire schema requires a physical timestamp. Never reinterpret ingestion time.
            if isinstance(capture.source, CollectionLineage):
                raise Rejected("physical_capture_timestamp_unavailable")
            reference = reference_from(binding.get("reference"))
            if reference is not None:
                validate_decision_reference(capture, reference)
            run, stored = None, None
            if action == "stored":
                if type(binding["attempt_id"]) is not int or binding["attempt_id"] < 1:
                    raise Rejected("explicit_attempt_required")
                attempt = db.execute("SELECT payload,assessment FROM vision_attempts WHERE organization_id=? "
                    "AND client_scope=? AND record_id=? AND unit_id=? AND attempt_id=?",
                    (*params, binding["attempt_id"])).fetchone()
                if attempt is None:
                    raise Rejected("attempt_not_found", 404)
                run_value, stored = map(json.loads, attempt)
                if digest({"run": run_value, "assessment": stored}) != binding["attempt_sha256"]:
                    raise Rejected("attempt_hash_mismatch")
                run = run_from(capture, run_value)
                stored_reference = reference_from(stored.get("decision_reference"))
                if canonical(asdict(stored_reference) if stored_reference else None) != canonical(binding.get("reference")):
                    raise Rejected("attempt_reference_mismatch")
                result = assess(capture, run.observations or ObservationPlaceholder(run.error_code), reference)
                if canonical(asdict(result)) != canonical(stored):
                    raise Rejected("stored_assessment_tampered")
        finally:
            db.close()
        images, citations = [], []
        for item in binding["images"]:
            ref = safe_ref(item["ref"])
            if ref not in {i.reference for i in capture.images}:
                raise Rejected("image_membership_mismatch")
            kind = item["kind"]
            content = None
            if kind == "genuine":
                image_path = local_path(self.root, item["path"])
                if image_path.exists():
                    with image_path.open("rb") as stream:
                        content = stream.read(10_000_001)
                    if hashlib.sha256(content).hexdigest() != item["sha256"]:
                        raise Rejected("image_hash_mismatch")
                if not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
                    raise Rejected("registered_image_hash_required")
            elif kind != "fixture" or self.config.get("allow_fixture") is not True:
                raise Rejected("fixture_mode_not_authorized")
            images.append(ImageInput(ObservationScope.from_capture(capture), item["image_id"],
                item["evidence_id"], ref, item["role"], kind, content))
            citations.append({"ref": ref, "kind": "image",
                              "sha256": item.get("sha256") if content is not None else None})
        mode = run.provider_mode if run else ("fixture" if self.config.get("allow_fixture") else "real")
        prepared = prepare_request(capture, tuple(images), "real" if mode == "unconfigured" else mode)
        if run is not None and canonical([asdict(i) for i in prepared.images]) != canonical([asdict(i) for i in run.images]):
            raise Rejected("stored_image_binding_mismatch")
        snapshot = {"mode": "existing", "capture": asdict(capture), "binding": binding,
                    "images": [asdict(i) for i in prepared.images],
                    "run": asdict(run) if run else None, "assessment": stored}
        citations.insert(0, {"ref": f"returns-capture/{capture.record_id}", "kind": "other",
                             "sha256": digest(asdict(capture))})
        if reference is not None:
            citations.append({"ref": f"returns-reference/{capture.record_id}", "kind": "document",
                              "sha256": reference.source_sha256})
        if action == "stored":
            citations.append({"ref": f"returns-attempt/{capture.record_id}/{binding['attempt_id']}",
                              "kind": "other", "sha256": binding["attempt_sha256"]})
        return Resolved(capture, reference, tuple(images), run, snapshot, citations, action)
