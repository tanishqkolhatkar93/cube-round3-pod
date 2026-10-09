import json
import hashlib
import pytest
from pathlib import Path
from agents.receiving import app as receiving
from agents.receiving.core.config import CFG

@pytest.fixture(autouse=True)
def isolated_receiving(tmp_path, monkeypatch):
    root = tmp_path / "input"
    root.mkdir()
    manifest = tmp_path / "captures.json"
    manifest.write_text('{"captures":[]}')
    monkeypatch.setattr(receiving, "DATA_INPUT", root)
    monkeypatch.setenv("RECEIVING_CAPTURE_REGISTRY", str(manifest))
    monkeypatch.setenv("RECEIVING_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(CFG,"cache_dir",tmp_path / "cache")
    monkeypatch.setattr(CFG,"gemini_api_key","")
    monkeypatch.setattr(CFG,"gemini_fallback_models",[])
    return root, manifest

@pytest.fixture
def register(isolated_receiving):
    root, manifest = isolated_receiving
    def add(ref="UNIT-9001/receiving/image.jpg", raw=b"image", org="org_demo_alpha", subject="UNIT-9001"):
        path = root / ref
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        d=json.loads(manifest.read_text())
        d["captures"].append({"ref":ref,"org_id":org,"subject_id":subject,"sha256":hashlib.sha256(raw).hexdigest()})
        manifest.write_text(json.dumps(d))
        return {"ref":ref,"kind":"image","sha256":hashlib.sha256(raw).hexdigest()}
    return add
