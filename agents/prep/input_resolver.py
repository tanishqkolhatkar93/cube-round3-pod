"""Trusted registrations select captures. Request refs are assertions, not paths.

This service is an internal capability of the authenticated orchestrator. A
deployment must protect direct /run access. JSON org fields are not credentials.
"""
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import warnings

from PIL import Image

from .common import Rejected, canonical, digest, fields, identifier, number, strict_json, text, timestamp
from .core.rulepacks.organizer import validate_criteria

MAX_IMAGES = 6
MAX_IMAGE_BYTES = 10_000_000


def safe_ref(ref):
    if (not isinstance(ref, str) or not ref or len(ref) > 512 or ref.startswith("/")
            or any(c in ref for c in ("\\", ":", "%"))
            or any(p in ("", ".", "..") for p in ref.split("/")) or any(ord(c) < 32 for c in ref)):
        raise Rejected("unsafe_reference")
    return ref


def local_path(root, relative):
    safe_ref(relative)
    root = Path(root).resolve()
    candidate = root / relative
    # Reject symlinks and Windows junctions even when their destination is inside
    # the root. Privileged host mutations remain outside this trust boundary.
    current = root
    for component in relative.split("/"):
        current = current / component
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise Rejected("source_link_rejected")
    if not candidate.resolve().is_relative_to(root):
        raise Rejected("source_path_escape")
    return candidate


def registered_bytes(root, item, limit):
    fields(item, ("ref", "path", "sha256"))
    safe_ref(item["ref"])
    if not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
        raise Rejected("registered_hash_required")
    path = local_path(root, item["path"])
    before = path.stat()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not os.path.samestat(before, opened):
            raise Rejected("source_changed_during_read")
        content = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    local_path(root, item["path"])
    final = path.stat()
    if (not os.path.samestat(opened, final) or opened.st_mtime_ns != after.st_mtime_ns
            or after.st_mtime_ns != final.st_mtime_ns or opened.st_size != final.st_size):
        raise Rejected("source_changed_during_read")
    if len(content) > limit:
        raise Rejected("source_too_large")
    if hashlib.sha256(content).hexdigest() != item["sha256"]:
        raise Rejected("input_hash_mismatch")
    return content


@dataclass
class Resolved:
    binding: dict
    criteria: dict
    images: list
    inputs: list
    material: dict | None
    snapshot: dict
    failure: str | None


class Resolver:
    def __init__(self, config, root):
        try:
            self.config = strict_json(canonical(config))
            fields(self.config, ("version", "org_id", "bindings"), ("client_id", "provider"))
            if type(config["version"]) is not int or config["version"] != 1:
                raise ValueError("unsupported registration version")
            identifier(config["org_id"])
            if config.get("client_id") is not None:
                identifier(config["client_id"])
            if not isinstance(config["bindings"], list):
                raise ValueError("bindings must be a list")
            identities = set()
            for binding in self.config["bindings"]:
                fields(binding, ("subject_id", "workflow_id", "capture_id", "captured_at", "criteria", "images"),
                       ("material", "operator_id"))
                for name in ("subject_id", "workflow_id", "capture_id"):
                    identifier(binding[name])
                timestamp(binding["captured_at"])
                if binding.get("operator_id") is not None:
                    text(binding["operator_id"])
                identity = (binding["subject_id"], binding["workflow_id"])
                if identity in identities:
                    raise ValueError("ambiguous capture binding")
                identities.add(identity)
                if not isinstance(binding["images"], list) or len(binding["images"]) > MAX_IMAGES:
                    raise ValueError("capture count exceeds explicit limit")
            self.root = Path(root).resolve()
        except (ValueError, TypeError, KeyError):
            raise Rejected("invalid_registration") from None

    def resolve(self, request):
        try:
            subject = request["subject"]
            if subject["org_id"] != self.config["org_id"]:
                raise Rejected("source_not_found", 404)
            matches = [b for b in self.config["bindings"] if b["subject_id"] == subject["subject_id"]
                       and b["workflow_id"] == request["workflow_id"]]
            if len(matches) != 1:
                raise Rejected("source_not_found", 404)
            binding = matches[0]
            entries = [(binding["criteria"], "document"), *[(i, "image") for i in binding["images"]]]
            if binding.get("material") is not None:
                entries.append((binding["material"], "document"))
            registered, paths = {}, set()
            for item, kind in entries:
                fields(item, ("ref", "path", "sha256"))
                ref = safe_ref(item["ref"])
                path = local_path(self.root, item["path"]).resolve()
                if ref in registered or path in paths:
                    raise Rejected("duplicate_registration")
                if not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
                    raise Rejected("registered_hash_required")
                registered[ref] = {"ref": ref, "kind": kind, "sha256": item["sha256"]}
                paths.add(path)
            # Empty assertions mean use the trusted binding. Any submitted ref
            # must belong to this exact binding; a correct hash is insufficient.
            seen = set()
            for item in request.get("inputs", []):
                ref = safe_ref(item["ref"])
                if ref in seen or ref not in registered:
                    raise Rejected("unregistered_or_duplicate_reference")
                seen.add(ref)
                if item.get("sha256") != registered[ref]["sha256"] or item.get("kind", registered[ref]["kind"]) != registered[ref]["kind"]:
                    raise Rejected("input_assertion_mismatch")
            criteria = validate_criteria(strict_json(registered_bytes(self.root, binding["criteria"], 100_000)))
            material = None
            if binding.get("material") is not None:
                material = strict_json(registered_bytes(self.root, binding["material"], 100_000))
                fields(material, ("org_id", "subject_id", "workflow_id", "capture_id", "captured_at",
                                  "attested_by", "thickness_mil", "durable"))
                for k, expected in (("org_id", self.config["org_id"]), ("subject_id", binding["subject_id"]),
                                    ("workflow_id", binding["workflow_id"]), ("capture_id", binding["capture_id"]),
                                    ("captured_at", binding["captured_at"])):
                    if material[k] != expected:
                        raise Rejected("material_scope_mismatch")
                text(material["attested_by"])
                number(material["thickness_mil"], 0, 1000)
                if type(material["durable"]) is not bool:
                    raise ValueError("invalid material attestation")
                material = {**material, "ref": binding["material"]["ref"]}
            images, failure = [], None
            hashes = set()
            for item in binding["images"]:
                if item["sha256"] in hashes:
                    raise Rejected("duplicate_capture_bytes")
                hashes.add(item["sha256"])
                try:
                    content = registered_bytes(self.root, item, MAX_IMAGE_BYTES)
                except FileNotFoundError:
                    failure = failure or "missing_image"
                    continue
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", Image.DecompressionBombWarning)
                        with Image.open(io.BytesIO(content)) as picture:
                            fmt = picture.format
                            if fmt not in ("JPEG", "PNG", "WEBP") or picture.width * picture.height > 20_000_000:
                                raise ValueError("unsupported image")
                            picture.verify()
                    images.append({"ref": item["ref"], "sha256": item["sha256"], "bytes": content,
                                   "media_type": {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]})
                except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                    failure = failure or "invalid_image"
            if not binding["images"]:
                failure = "missing_image"
            snapshot = {"registration": binding, "criteria": criteria, "material": material,
                        "authorized_inputs": list(registered.values()), "input_failure": failure}
            return Resolved(binding, criteria, images, list(registered.values()), material, snapshot, failure)
        except Rejected:
            raise
        except FileNotFoundError:
            raise Rejected("registered_document_missing") from None
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise Rejected("invalid_registered_source") from None
