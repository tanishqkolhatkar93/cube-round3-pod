# Pod 14 Prep Manager

Python port of the organizer-supplied Prep domain core, using the unchanged
Round 3 contract. Source revision and adaptations: [PROVENANCE.md](PROVENANCE.md).

## Execution

`authorized registration -> verify criteria/captures -> reserve request -> factual
observations -> strict validation -> deterministic rules -> canonical evidence ->
durable exact output`

`agents.prep.app.handle` supports the existing InProcClient. HTTP entry points
are `POST /run` and `GET /health` (`uvicorn agents.prep.app:app --port 8102`).
No flow, pod configuration, other agent, or orchestration change is required to
call Prep. Workflow activation remains a separate decision.

There is no production CSV replay or implicit fixture fallback. Without trusted
configuration, health is degraded and /run returns a sanitized 503. The
orchestrator records failure; absence of configuration never becomes PASS.

## Trusted configuration

Set `PREP_CONFIG` to an absolute JSON registration file and `PREP_STATE_DIR` to
a separate persistent state directory. Neither comes from request content.
Capture/document paths are relative to the registration file directory. Keep
configuration and source files writable only by the trusted operator.

One registration serves one org/client. The service is an INTERNAL capability:
authenticate callers at the hardened orchestrator and restrict direct /run
access. Do not deploy it publicly with caller-chosen org headers as credentials.

Example registration (replace placeholder hashes with actual SHA-256 values):

```json
{
  "version": 1,
  "org_id": "org_demo_alpha",
  "client_id": "client_alpha",
  "provider": {
    "kind": "gemini",
    "model": "gemini-2.5-flash",
    "api_key_env": "GEMINI_API_KEY",
    "deadline_s": 15
  },
  "bindings": [{
    "subject_id": "UNIT-0014",
    "workflow_id": "WF-org_demo_alpha-UNIT-0014",
    "capture_id": "CAP-0014",
    "captured_at": "2026-10-01T10:00:00Z",
    "operator_id": "operator_1",
    "criteria": {"ref": "criteria/SKU1-v1.json", "path": "criteria/SKU1-v1.json", "sha256": "REPLACE_WITH_ACTUAL_HASH"},
    "images": [{"ref": "UNIT-0014/prep/front.png", "path": "UNIT-0014/prep/front.png", "sha256": "REPLACE_WITH_ACTUAL_HASH"}]
  }]
}
```

Versioned criteria document:

```json
{
  "criteria_id": "SKU1-prep", "version": "1",
  "source": "Operator-approved criteria; organizer implementation policy unverified",
  "rule_pack": "organizer-fba@1-pod14.1", "sku": "SKU1",
  "expected_fnsku": "X001ABC123", "requires_polybag": true,
  "requires_suffocation_warning": true, "cover_original_barcode": true,
  "has_expiry": false, "required_handling_marks": ["Fragile", "This Way Up"]
}
```

All applicability booleans are mandatory actual booleans. Caller context cannot
override them. The expected identifier must be exact uppercase alphanumeric.
Unknown rule packs and extra criteria fields are rejected.

A polybag also requires a registered material attestation or its material check
remains UNCERTAIN. Optional binding `material` uses the same `{ref,path,sha256}`
shape. Its JSON must contain `org_id`, `subject_id`, `workflow_id`, `capture_id`,
`captured_at` (exactly matching the binding), `attested_by`, `thickness_mil`
(nonnegative finite number), and `durable` (boolean). This is an operator physical
attestation, never a measurement invented from an image.

References are identifiers, not file locators supplied by callers. Empty
request `inputs` selects the trusted registered set. Nonempty inputs must match
registered references, kinds and hashes. All bound images are processed; a
subset assertion never hides another image. Maximum six images, 10 MB each,
20 million pixels, PNG/JPEG/WebP. Excess, duplicates and hash mismatches are
rejected. Missing/invalid images produce pending uncertainty without constructing
a provider. Symlinks, junctions, absolute/UNC/drive/encoded/traversal paths fail.

## Provider and rules

The sole production provider is explicit opt-in Gemini. No API key is read until
request/capture/criteria/upstream validation finishes. Missing key produces a
canonical pending record. One attempt is made; no provider fallback or hidden
retry. A spawned worker is terminated on deadline (maximum configured 20 s).
The HTTP timeout is additionally bounded. External operation cancellation is
best effort: the ledger prevents a second call for the same request.

Tests inject a provider factory into `Adapter` and never invoke live Gemini.
Injected transports must implement cancellation; the adapter bounds waiting and
discards late results. Real model accuracy has not been evaluated in these tests.

The provider returns `{photos, observations}` only. Each fact names a known
field, value, authorized positive integer photo index, confidence in [0,1], and
description. No model verdict is accepted. Confidence below 0.8, missing facts,
missing/unusable quality, ambiguous identity and conflicting images require
review. Duplicate field/photo observations are rejected, not overwritten.

Any applicable FAIL determines FAIL; otherwise any required uncertainty means
UNCERTAIN; otherwise PASS. FAIL with another unresolved check still requests
human review. Nonapplicable checks remain separate payload annotations.

## Failures, evidence, replay

- Business judgments: `completed` with PASS/FAIL/UNCERTAIN.
- Missing/invalid images or failed provider/response: `pending`, UNCERTAIN,
  structured error, review required. HTTP 200 does not imply a successful judgment.
- Unauthorized scope: 404. Invalid assertions/schema: 422. Replay conflicts: 409.
- Configuration/storage/unexpected service failure: sanitized 503; orchestration
  records a degraded failure. No raw provider exception is exported.

The evidence retains the registered physical timestamp, authorized input hashes,
criteria, normalized observations, requirement annotations, model/prompt/source
identity and consumed upstream IDs. Raw provider text is not persisted; its hash
is retained. Upstream records are verified and kept as audit context, not used to
invent a physical observation. Prep does not require Receiving to have passed
before it can independently inspect a registered capture.

The SQLite ledger key includes org/client/subject/workflow/request. Exact same
content returns exact persisted output. Changes to request, criteria, registered
sources or provider configuration conflict. Another tenant/subject/workflow has
an independent key. Concurrent workers reserve atomically. After crash, a running
or interrupted reservation is not reused: investigate the provider/capture state
and submit a NEW request ID after reconciliation. A new request creates new
immutable PRP evidence. Existing completed/pending outputs are never overwritten.

Source validation precedes replay: sources must remain available and unchanged.
The ledger is not an archive that authorizes missing/replaced source files.

## Offline validation

```powershell
python -B -m pytest agents/prep/tests -o addopts='' -q -p no:cacheprovider
python -B -m pytest -o addopts='' -q -p no:cacheprovider
```

`tests/integration/test_prep_manager.py` exposes the Prep-owned tests to default
repository discovery. Tests use temporary explicitly synthetic PNGs, registrations,
criteria and provider doubles; no generated state or credentials belong in Git.
See `VALIDATION.md` for exact results and any remaining integration limitations.

### Explicit support for shared integration scenarios

Selected tests import and request `prep_synthetic` from
`agents.prep.tests.integration_support`. It is not autouse and requires no
plugin registration or shared conftest change. Non-Prep parameterizations do
not activate it. The fixture creates per-organization JSON registrations,
hashed synthetic PNGs/criteria, fixed factual responses and temporary ledgers.
These are synthetic test scenarios, not reconstructions of physical sample
captures or CSV verdict replay. UNIT-0012 has an unresolved handling mark;
UNIT-0014 has the required facts to produce PASS through the real rules.

The existing environment/config loader and HTTP endpoints remain in use. A
test-only replacement at the adapter-construction seam routes to real adapters
for each registered organization and injects the offline observation provider.
The resolver, observations, rules, evidence construction and SQLite ledger are
unchanged. Unknown subjects still reach the real resolver and are rejected.

State persists across calls within each test. The HTTP/inproc comparison calls
`prep_synthetic.fresh_state("inproc_comparison")` before its independent second
execution. This selects a separate ledger without deleting or rewriting the
first one. Exact replay and changed-content conflicts remain covered separately.
