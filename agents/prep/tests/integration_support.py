"""Explicit, non-autouse synthetic Prep support for existing sample scenarios.

This is not a CSV verdict replay. Registered PNGs, criteria and fixed factual
responses exercise the real resolver, parser, rules, evidence and SQLite ledger.
Only tests importing AND requesting prep_synthetic activate the support.
"""
from collections import Counter
import json
from pathlib import Path

import pytest

from agents.prep import app as prep_app
from agents.prep.adapter import Adapter
from agents.prep.common import canonical, strict_json
from agents.prep.tests.test_prep import Harness, facts, image_bytes, write_item

ROOT = Path(__file__).resolve().parents[3]


class SyntheticPrep:
    def __init__(self, root, monkeypatch):
        self.root = root
        self.monkeypatch = monkeypatch
        self.registrations = {}
        self.responses = {}
        self.calls = Counter()
        cases = json.loads((ROOT / "data/sample/cases.json").read_text())
        for org in sorted({c["org_id"] for c in cases}):
            folder = root / org
            folder.mkdir(parents=True)
            h = Harness(folder)
            h.config.update(org_id=org, client_id=None)
            h.config["bindings"] = []
            for case in (c for c in cases if c["org_id"] == org and c["route"] == "fba"):
                unit = case["unit_id"]
                criteria = {**h.criteria, "criteria_id": "synthetic-" + unit,
                            "sku": "synthetic-" + unit,
                            "required_handling_marks": ["Fragile", "This Way Up"]}
                photo = write_item(h.root, unit + "/front.png", image_bytes())
                binding = {"subject_id": unit, "workflow_id": f"WF-{org}-{unit}",
                           "capture_id": "SYNTHETIC-" + unit,
                           "captured_at": "2026-10-01T10:00:00Z", "operator_id": "synthetic-test-operator",
                           "criteria": write_item(h.root, unit + "/criteria.json", canonical(criteria).encode()),
                           "images": [photo]}
                h.config["bindings"].append(binding)
                response = facts(criteria)
                # The documented review scenario has a visible label but an
                # unresolved handling mark. UNIT-0014 has all required facts.
                if unit == "UNIT-0012":
                    next(o for o in response["observations"] if o["field"] == "handling_mark:Fragile")["value"] = None
                self.responses[criteria["criteria_id"]] = (photo["sha256"], canonical(response))
            config = h.root / "registration.json"
            config.write_text(canonical(h.config), encoding="utf-8")
            self.registrations[org] = config
        monkeypatch.setenv("PREP_CONFIG", str(next(iter(self.registrations.values()))))
        self.fresh_state("initial")
        # Keep configured_adapter(), /health and /run unchanged. Replace only
        # the adapter construction seam with an explicit test deployment router.
        monkeypatch.setattr(prep_app, "Adapter", self.construct_router)

    def fresh_state(self, name):
        """Select a NEW ledger namespace; never clear/rewrite an existing ledger."""
        if not name.isidentifier():
            raise ValueError("test state name must be an identifier")
        self.monkeypatch.setenv("PREP_STATE_DIR", str(self.root / "state" / name))

    def observe(self, images, criteria, deadline_s):
        key = criteria["criteria_id"]
        expected_hash, response = self.responses[key]
        assert len(images) == 1 and images[0]["sha256"] == expected_hash
        self.calls[key] += 1
        return {"text": response, "model_version": "explicit-synthetic-facts-v1"}

    def construct_router(self, config, root, state):
        # The default org was loaded by the actual environment/config loader.
        adapters = {config["org_id"]: Adapter(config, root, Path(state) / config["org_id"],
                                             provider_factory=lambda _: self)}
        for org, filename in self.registrations.items():
            if org not in adapters:
                adapters[org] = Adapter(strict_json(filename.read_text(encoding="utf-8")),
                                        filename.parent, Path(state) / org, provider_factory=lambda _: self)
        default = adapters[config["org_id"]]

        class Router:
            def handle(self, request):
                # Routing grants no capture rights: the selected real resolver
                # must authorize the org/subject/workflow against its registry.
                subject = request.get("subject", {}) if isinstance(request, dict) else {}
                org = subject.get("org_id") if isinstance(subject, dict) else None
                return adapters.get(org, default).handle(request)

        return Router()


@pytest.fixture
def prep_synthetic(tmp_path, monkeypatch, request):
    # Parametrized contract tests for other agents retain their original setup.
    if getattr(request.node, "callspec", None) and request.node.callspec.params.get("stage", "prep") != "prep":
        yield None
        return
    yield SyntheticPrep(tmp_path / "prep-synthetic", monkeypatch)
