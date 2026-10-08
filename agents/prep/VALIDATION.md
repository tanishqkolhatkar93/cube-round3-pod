# Prep implementation validation

Validated 2026-10-08 on Windows / Python 3.13. Tests use explicitly synthetic
captures and offline observation providers. No live provider calls or dependency
installations. No implementation commit, PR or merge created.

## Revision and scope

- Branch: `codex/integrate-prep-manager`.
- Worktree: `C:/Users/karth/.codex/worktrees/integrate-prep-manager/cube-round3-pod`.
- HEAD and unchanged local Test: `911abdbd14a345dead627695825e6f6d36113ea3`.
- Organizer Prep source: `f5f8ad98fa8085a092c796b0681689d52ffc871e`.

The integration-support follow-up changes only:

- `agents/prep/tests/integration_support.py` (new opt-in fixture).
- `agents/prep/tests/test_integration_support.py` (four new regression tests).
- `agents/prep/README.md` and this validation report.
- `tests/integration/test_prep_manager.py` (discovers the new Prep-owned tests).
- `tests/integration/test_agent_contracts.py` (explicit fixture opt-in and stronger assertions).
- `tests/e2e/test_http.py` (explicit opt-in, separate Prep ledger per execution).
- `tests/e2e/test_examples.py` and `tests/e2e/test_end_to_end.py` (explicit opt-in).

No production behavior changed in this follow-up. All pre-existing test assertions
remain; additional assertions verify real configured execution. Shared
`tests/conftest.py`, orchestration, shared production code/schemas, pod/flows,
Receiving, Pack, Returns and Recovery have no diff from Test. The previously
implemented Prep production files remain uncommitted and unchanged by this work.

## Test-support architecture

`prep_synthetic` is a non-autouse fixture imported and explicitly requested by
selected tests. Other tests do not activate it; non-Prep parameterizations of
agent contracts do not activate it either. No global pytest plugin is installed.

Each test receives temporary per-organization registrations, hashed PNGs and
versioned criteria, fixed factual observation responses, and separate durable
SQLite state per organization. The sample case list supplies identity/ownership
only; no CSV verdicts or evidence records are replayed. These synthetic scenarios
are not claims about the original physical sample units. UNIT-0012 has an unknown
handling mark; UNIT-0014 has the observations required for a genuine rule PASS.

The real environment/config loader, /health and /run are retained. The fixture
replaces the adapter-construction seam with a test-only organization router that
constructs real Adapter instances with an injected offline provider. Registered
scope, bytes, hashes, observations, rules, output and replay all pass through
production validation. Wrong-org subjects reach the real resolver and fail before
provider invocation. Health still becomes degraded when configuration is removed.

Calls within a test share state for exact replay and conflict validation. The
HTTP/inproc comparison explicitly selects a new Prep state namespace between
independent workflow executions, preserving the first ledger. It verifies two
inferences. A separate regression verifies one inference for identical replay,
409 rejection for changed content in the same ledger, and a fresh inference in
an independently selected ledger.

## Commands and results

Every pytest command used `python -B -m pytest`, `-o addopts=''`, `-q`, and
`-p no:cacheprovider`.

- `agents/prep/tests`: **139 passed**, no skips (13.51 s).
- Affected files: `tests/integration/test_agent_contracts.py`,
  `tests/e2e/test_examples.py`, `tests/e2e/test_end_to_end.py`,
  `tests/e2e/test_http.py`: **61 passed, 1 skipped**.
- Full default suite: **441 passed, 1 skipped, zero failures**, 442 collected
  (76.61 s). Two existing websockets/uvicorn deprecation warnings.
- Compiled all 16 Prep Python files and five affected/discovery test files in
  memory; imports of the support, its regressions and production app passed.
- `git diff --check`: passed (Git LF-to-CRLF notices only).
- Protected-path diff against Test, including shared conftest: empty.

The existing skip is
`tests/e2e/test_end_to_end.py::test_matches_expected_outcomes_for_the_organiser_stubs`,
reason `not the stock stubs + standard flow`. No new skips or xfails were added.
No credentials or generated runtime captures/ledgers belong to the repository;
fixture files are created only in pytest temporary directories.

## Resolution of the previous failures

The prior run had 135 Prep tests passing and a full-suite result of 427 passed,
10 failed, 1 skipped. All ten failures now pass with explicit test support:

1. `test_outputs_are_contract_valid[prep]`: real completed evidence for both orgs.
2. `test_other_tenant_gets_nothing[prep]`: real source_not_found authorization rejection.
3. `test_same_request_same_record_id[prep]`: durable replay with one inference.
4. `test_each_stage_can_consume_the_previous_stages_output`: completed, hash-valid Prep handoff.
5. `test_recovery_honours_overrides_of_previous_evidence`: genuine Prep PASS before override.
6. `test_claim_names_amount_and_cites_evidence`: real Prep-generated claim support and citations.
7. `test_example_cases_with_integrated_returns[uncertain-path]`: unresolved factual observation, completed UNCERTAIN.
8. `test_example_cases_with_integrated_returns[end-to-end]`: Prep PASS supports claim while Returns stays pending.
9. `test_health_endpoints`: valid configuration, unchanged health semantics.
10. `test_full_workflow_over_http_matches_in_process`: configured execution and separate Prep ledgers.

The earlier report overstated the need to modify shared fixtures. Shared
conftest was not required. Configuration alone would also have missed the
transport comparison's ledger lifecycle; that is now explicitly handled.

## Readiness and limits

**PR-ready for code review:** the scoped offline integration-validation gaps are
closed and the full suite is green. No remaining test failures to classify.
No PR or commit has been created. This does not activate or certify production
use. Production Gemini transport/process cleanup and live model accuracy have
not been established by these provider-double tests. Marketplace requirements
remain organizer-derived and independently unverified. Trusted registration,
protected source/state directories, authenticated deployment routing and durable
single-host SQLite remain deployment assumptions. See PROVENANCE.md.
