"""Opt-in synthetic scenarios; only the vision provider is replaced.

Invented observations are paired with generated patterns, not inferred from them.
Production discovery, authorization, gate, cache, rules and replay still run.
"""
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from agents.receiving import app as receiving
from agents.receiving.core.config import CFG
from agents.receiving.core.extraction import gemini
from agents.receiving.core.extraction.base import VisionResponse
from agents.receiving.core.extraction.service import process_image
from agents.receiving.core.models import ImageObservation
from agents.receiving.core.quality import assess_quality


@pytest.fixture
def receiving_observed(tmp_path, monkeypatch, cases):
    root = tmp_path / "explicit-receiving-input"
    root.mkdir()
    repo = Path(__file__).resolve().parents[3]
    selected = [cases[0], next(c for c in cases if c["route"] == "unknown"),
                next(c for c in cases if c["route"] == "fba" and c["returned"])]
    selected += [json.loads((repo / "examples" / name / "case.json").read_text())
                 for name in ("happy-path", "uncertain-path", "end-to-end")]
    responses, captures, calls = {}, [], []
    for index, case in enumerate({c["unit_id"]: c for c in selected}.values()):
        unit, org = case["unit_id"], case["org_id"]
        spec = receiving._spec_of(*receiving._lookup(unit, org))
        img = Image.new("RGB", (640, 480), (190, 190, 190))
        draw = ImageDraw.Draw(img)
        for x in range(0, 640, 24):
            draw.rectangle((x, 0, x + 10, 479), fill=(50 + index * 7, 70, 90))
        raw = io.BytesIO()
        img.save(raw, "JPEG")
        raw = raw.getvalue()
        processed = process_image(raw)
        assert assess_quality(processed)["verdict"] == "ACCEPTABLE"
        observation = ImageObservation(
            visible_sku_text=spec["sku"], label_colour_text=spec["spec_colour"],
            label_variant_text=spec["spec_variant"], visible_unit_count=spec["qty_ordered"],
            count_confidence=0.95, full_contents_visible=True,
            cartons_visible=spec["cartons_ordered"] or 1,
            visible_components=spec["spec_components"], contents_open_for_inspection=True)
        if unit == "UNIT-0012":
            observation.visible_unit_count = None
            observation.full_contents_visible = False
        responses[hashlib.sha256(processed).hexdigest()] = observation
        ref = f"{unit}/receiving/synthetic.jpg"
        path = root / ref
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
        captures.append(dict(ref=ref, org_id=org, subject_id=unit,
                             sha256=hashlib.sha256(raw).hexdigest()))
    registry = tmp_path / "explicit-receiving-captures.json"
    registry.write_text(json.dumps({"captures": captures}), encoding="utf-8")

    class OfflineProvider:
        def analyze(self, request, *, stats, deadline):
            key = hashlib.sha256(request.image_bytes).hexdigest()
            calls.append(key)
            stats["calls"] += 1
            return VisionResponse(responses[key].model_copy(deep=True), "",
                                  "synthetic-test-provider", request.prompt_version, 0, 0)

        def close(self):
            pass

    monkeypatch.setenv("INPUT_DIR", str(root))
    monkeypatch.setattr(receiving, "DATA_INPUT", root)
    monkeypatch.setenv("RECEIVING_CAPTURE_REGISTRY", str(registry))
    monkeypatch.setenv("RECEIVING_STATE_DIR", str(tmp_path / "explicit-receiving-state"))
    monkeypatch.setattr(CFG, "cache_dir", tmp_path / "explicit-receiving-cache")
    monkeypatch.setattr(gemini, "GeminiProvider", OfflineProvider)
    return calls
