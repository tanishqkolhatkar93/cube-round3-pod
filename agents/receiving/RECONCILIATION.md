> The implementation described below was subsequently preserved in commit
> `e5dcbe4d15d00ea0f53db4ccd14fb10b98d54768` after a fresh 425-pass/1-skip run.
> The historical worktree notes below predate that commit. Final Pod validation is separate.

# Receiving combined reconciliation

Branch: `integrate/receiving-combined`. HEAD/base/latest remote Test:
`911abdbd14a345dead627695825e6f6d36113ea3`.
Zain remote `integrate/receiving-manager`: `48e63ce8007b7db0831ec1bfedabbff1b9fb9a91`.
Local `fix/receiving-safety`: `2e16f37d3d333b9a38b42ffbc7b3ebb57ef8b2a9`.
Remote tips were reverified with ls-remote on 2026-10-08.

Changes were reconciled by path on the Test worktree, not by an automatic merge
commit. There is no MERGE_HEAD or unresolved index entry. All changes remain
unstaged; no commit, push or PR was created. Existing work was resumed in place.

## Security and behavioral overlap decisions

- Identity: retain Zain's RCV- plus SHA256(request_id)[:12] on every output path.
  app._record_id aliases safety.record_id; ledger replay verification uses the
  same function. Safety's separate org/workflow/subject/request ledger key is
  retained. No competing public identity remains.
- Paths/ownership: retain safety.safe_ref and resolve_captures as the single
  authoritative implementation of Zain's safe-relative/root-containment goal.
  app._safe_rel is an alias. The resolver additionally rejects backslashes,
  symlinks/junctions, foreign ownership, unregistered bytes, mismatched hashes,
  duplicate references and incomplete registered capture sets. No filename fallback.
- Lookup: retain organization-checked fixture specifications and organization-scoped
  sample PO lookup. Sample observed outcomes are not model observations.
- Partial extraction: retain safety's pending/error handling. Mixed usable/unsafe,
  omitted, failed or rejected images cannot become a completed PASS. All-rejected
  quality inputs can produce completed UNCERTAIN, not a clean judgment.
- Per-carton quantity: retain the exported units_per_carton check and safety's
  aggregate safeguard. A mapped summary cannot hide a failing core check.
- Replay: retain SQLite atomic publication, full content/config/capture fingerprint,
  scoped keys, same-content replay and changed-content conflict. Arrival of captures
  after a pending request requires a new attempt; tests no longer expect replacement.
  Thread, process, restart and interrupted-transaction regressions are retained.
- Provider: safety already retains Zain's Part.from_bytes JPEG boundary. Keep its
  image processing/gate/cache-before-provider order, bounded explicit attempts and
  deadlines, safe error categories and actual model accounting.
- Cache: keep safety's serialized SQLite misses/publication and model attribution.
- Upstream: keep first-stage rejection of any previous_evidence on both HTTP and
  in-process paths, including valid but inappropriate evidence; never blindly trust it.
- Shared test setup: combine Zain's discover_inputs in make_input with temporary
  Receiving input/registration/state/cache and disabled live credentials. Existing
  Returns setup remains intact. Explicit fixtures opt selected scenarios into
  synthetic registered captures and offline provider observations.
- Tests: retain adverse/missing-capture scenarios from the earlier reconciliation;
  add the original Test-baseline success/override/uncertain workflow assertions as
  explicit registered scenarios. AST comparison confirms every baseline assertion
  in the four affected scenario files remains. Mangle now corrupts the content hash
  directly so even an empty pending record is actually tampered.
- Fixtures/docs: preserve all 23 Zain JPEG bytes exactly, register trusted owners
  and SHA256 digests, and retain source/fixture caveats. Append Receiving decisions
  to existing Test decisions. Receiving requirements are the authoritative dependency
  list included by the root requirements. No organization-token configuration added.

## Test support boundaries

agents/receiving/tests/integration_support.py defines a non-autouse fixture.
It creates temporary patterns, trusted registrations, isolated ledger/cache and
invented observations indexed by processed image hash. PO fields generate intended
matching synthetic scenarios at setup; they are not sent to a production provider.
UNIT-0012 deliberately has an unresolved visual count. Only the provider is replaced;
real discovery, authorization, image processing, quality gate, cache, domain checks,
evidence sealing and request replay execute. No production module imports test support.
Existing no-capture tests remain as separate negative-path coverage. The HTTP/inproc
Receiving request content is identical, so its real replay ledger stays active;
the existing Returns-only ledger separation is unchanged from Test.

## Validation before the 2026-10-09 adversarial fixes

Temporary external virtualenv, Python 3.13, google-genai 2.29.0 and OpenCV 5.0.0;
no live model calls. Commands used -B and pytest -o addopts='' -q -p no:cacheprovider.

- agents/receiving/tests: **92 passed** (13.29 s).
- tests/integration tests/e2e: **321 passed, 1 skipped** (57.01 s).
- agents/receiving/tests tests: **413 passed, 1 skipped** (72.98 s).
  Thirteen Receiving scenarios are also collected through the integration shim;
  the combined count is not a claim of 413 distinct scenarios.
- Compilation: 33 Receiving Python files; import: 28 production modules, all pass.
  Changed shared Python files are also compiled without writing bytecode.
- git diff --check: passes. No staged files or unresolved merge entries.
- Protected production paths: zero diff for Prep, Pack, Returns, Recovery,
  orchestration, shared schemas/code and pod/workflow definitions.
- Exact upstream bytes and trusted hash verified for all 23 staged fixtures.
- Changed inventory contains no runtime DB, credentials, live environment file or
  cache. .env.example contains comments only. Existing ignored __pycache__ from
  unrelated subprocess imports is excluded, not part of the candidate changes.

The one skip is test_matches_expected_outcomes_for_the_organiser_stubs in
 tests/e2e/test_end_to_end.py. Its stock-stub golden outcomes intentionally stop
applying when a real agent replaces a stub. Explicit real Receiving scenarios and
existing workflow rules cover this integration; no claim is made to replace the
entire stock dataset with a real-model accuracy benchmark. Two uvicorn/websockets
deprecation warnings remain; no failures.

## Adversarial fixes, 2026-10-09

The final adversarial review found two gaps in the earlier green suite. The
quantity check now compares an agreed reliable full count with every other visible
count before accepting it. A larger partial lower bound produces conflicting-evidence
UNCERTAIN, with both observations cited. Compatible partial counts retain existing
PASS behavior; disagreement among reliable full counts remains unchanged.

The engine now catches service context/cleanup exceptions while it still owns
accumulated observations, statistics and earlier errors. Cleanup still runs through
the existing service lifecycle and still prevents completion on failure. Pending
evidence retains calls, actual successful model identities, attempts, cache hits
and quality rejection counts. Earlier provider failures retain precedence, and
exception messages remain sanitized. No replay, capture, deadline or authorization
boundary was changed; shared test infrastructure was untouched.

Twelve Receiving-local regression cases were added: five count combinations in
both image orders, plus cleanup after successful and failed provider work. They
verify sealed output, contradictory-evidence rejection, compatible PASS, truthful
accounting (including a real cache hit), error precedence, and replay without
additional provider calls or cleanup. Before the fixes: 8 failed, 4 passed.
After the fixes, the Receiving suite passed all 104 cases. Compilation of 33
Receiving Python files and import of 28 production modules passed.
The full integrated command (agents/receiving/tests tests) passed **425 tests,
1 existing organizer-stub skip**, in 50.97 s, with two existing websockets
deprecation warnings. git diff --check passed. No files outside Receiving were
changed by these fixes.

## Remaining limits / review readiness

Ready for review, not a production-accuracy certification. Deployment must protect
trusted storage and authenticate the calling tenant. The requested 48-bit display
ID can collide and identical raw request IDs across scopes share a display ID;
use globally scoped IDs as the orchestrator does. SQLite is same-host, not distributed
exactly-once inference; crash recovery may repeat a provider call before publication.
UNIT-0012/0039 staged fixtures retain known PO mismatches. Offline doubles do not
validate real model accuracy. Quality thresholds remain provisional as documented.

## Overlapping files in the two source implementations

The following lists enumerate every overlapping Receiving production/document/test
file and the shared test file. Files exclusive to one source are not overlaps.

Different contents:
- `agents/receiving/PROVENANCE.md`
- `agents/receiving/README.md`
- `agents/receiving/agent.json`
- `agents/receiving/app.py`
- `agents/receiving/core/checks/colour.py`
- `agents/receiving/core/checks/sku.py`
- `agents/receiving/core/checks/variant.py`
- `agents/receiving/core/config.py`
- `agents/receiving/core/engine.py`
- `agents/receiving/core/extraction/gemini.py`
- `agents/receiving/core/extraction/service.py`
- `agents/receiving/core/models.py`
- `agents/receiving/tests/test_adapter.py`
- `tests/conftest.py`

Identical contents:
- `agents/receiving/__init__.py`
- `agents/receiving/core/__init__.py`
- `agents/receiving/core/checks/__init__.py`
- `agents/receiving/core/checks/base.py`
- `agents/receiving/core/checks/carton_count.py`
- `agents/receiving/core/checks/carton_damage.py`
- `agents/receiving/core/checks/missing_components.py`
- `agents/receiving/core/checks/other_quality.py`
- `agents/receiving/core/checks/quantity.py`
- `agents/receiving/core/checks/unit_damage.py`
- `agents/receiving/core/checks/units_per_carton.py`
- `agents/receiving/core/extraction/__init__.py`
- `agents/receiving/core/extraction/barcode.py`
- `agents/receiving/core/extraction/base.py`
- `agents/receiving/core/quality.py`
- `agents/receiving/core/summary.py`
- `agents/receiving/fixtures/units.json`
- `agents/receiving/prompts/observe_carton.v2.txt`

## Exact changed-file inventory (74)

- `.env.example`
- `.gitignore`
- `agents/receiving/PROVENANCE.md`
- `agents/receiving/README.md`
- `agents/receiving/RECONCILIATION.md`
- `agents/receiving/agent.json`
- `agents/receiving/app.py`
- `agents/receiving/core/__init__.py`
- `agents/receiving/core/checks/__init__.py`
- `agents/receiving/core/checks/base.py`
- `agents/receiving/core/checks/carton_count.py`
- `agents/receiving/core/checks/carton_damage.py`
- `agents/receiving/core/checks/colour.py`
- `agents/receiving/core/checks/matching.py`
- `agents/receiving/core/checks/missing_components.py`
- `agents/receiving/core/checks/other_quality.py`
- `agents/receiving/core/checks/quantity.py`
- `agents/receiving/core/checks/sku.py`
- `agents/receiving/core/checks/unit_damage.py`
- `agents/receiving/core/checks/units_per_carton.py`
- `agents/receiving/core/checks/variant.py`
- `agents/receiving/core/config.py`
- `agents/receiving/core/engine.py`
- `agents/receiving/core/extraction/__init__.py`
- `agents/receiving/core/extraction/barcode.py`
- `agents/receiving/core/extraction/base.py`
- `agents/receiving/core/extraction/gemini.py`
- `agents/receiving/core/extraction/service.py`
- `agents/receiving/core/failures.py`
- `agents/receiving/core/models.py`
- `agents/receiving/core/quality.py`
- `agents/receiving/core/summary.py`
- `agents/receiving/fixtures/captures.json`
- `agents/receiving/fixtures/units.json`
- `agents/receiving/prompts/observe_carton.v2.txt`
- `agents/receiving/requirements.txt`
- `agents/receiving/safety.py`
- `agents/receiving/tests/conftest.py`
- `agents/receiving/tests/integration_support.py`
- `agents/receiving/tests/test_adapter.py`
- `agents/receiving/tests/test_combined.py`
- `agents/receiving/tests/test_safety.py`
- `data/input/UNIT-0001/receiving/1_pallet.jpeg`
- `data/input/UNIT-0001/receiving/2_carton.jpeg`
- `data/input/UNIT-0001/receiving/2b_carton_damaged.jpeg`
- `data/input/UNIT-0001/receiving/3_unit.jpeg`
- `data/input/UNIT-0003/receiving/1_pallet.jpeg`
- `data/input/UNIT-0003/receiving/2_carton.jpeg`
- `data/input/UNIT-0003/receiving/3_unit.jpeg`
- `data/input/UNIT-0012/receiving/1_pallet.jpeg`
- `data/input/UNIT-0012/receiving/2_carton.jpeg`
- `data/input/UNIT-0012/receiving/3_unit.jpeg`
- `data/input/UNIT-0014/receiving/1_pallet.jpeg`
- `data/input/UNIT-0014/receiving/2_carton.jpeg`
- `data/input/UNIT-0014/receiving/3_unit.jpeg`
- `data/input/UNIT-0039/receiving/1_pallet.jpeg`
- `data/input/UNIT-0039/receiving/2_carton.jpeg`
- `data/input/UNIT-0039/receiving/3_unit.jpeg`
- `data/input/UNIT-0039/receiving/4_extra_dark.jpeg`
- `data/input/UNIT-9001/receiving/1_pallet.jpeg`
- `data/input/UNIT-9001/receiving/2_carton.jpeg`
- `data/input/UNIT-9001/receiving/3_unit.jpeg`
- `data/input/UNIT-9002/receiving/1_pallet.jpeg`
- `data/input/UNIT-9002/receiving/2_carton.jpeg`
- `data/input/UNIT-9002/receiving/3_unit.jpeg`
- `docs/decisions.md`
- `requirements.txt`
- `tests/conftest.py`
- `tests/e2e/test_examples.py`
- `tests/e2e/test_http.py`
- `tests/helpers.py`
- `tests/integration/test_agent_contracts.py`
- `tests/integration/test_receiving_combined.py`
- `tests/integration/test_workflow_state.py`
