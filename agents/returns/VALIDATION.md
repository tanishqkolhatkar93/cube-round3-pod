# Returns integration validation

Validated on Windows, Python 3.13.4, on branch
`codex/returns-contract-adapter` in the shared Pod fork checkout.
Changes are local and uncommitted; no push or merge was performed.

## Results

- New Returns integration + Specialist tests: **75 passed**, one dependency
  deprecation warning.
- Full Round 3 suite: **165 passed, 2 failed, 1 skipped**, one dependency
  deprecation warning. The skipped test is the organizer-stub golden result test;
  its existing guard skips when any agent implementation is replaced.
- Original Round 2 Returns suite: **392 passed, 2 skipped, 539 subtests passed**.
  Live Ollama/Gemini tests were explicitly disabled. The original working tree
  remains clean at the pinned commit.

The two remaining full-suite failures were also observed on the unmodified starter
before implementation:

1. `tests/e2e/test_end_to_end.py::test_captures_in_data_input_become_content_addressed_inputs`:
   Windows input discovery returns backslashes; the test expects forward slashes.
2. `tests/e2e/test_http.py::test_dead_agent_is_recorded_not_hidden`:
   a connection to an unused localhost port times out on this machine; the test
   expects `agent_unavailable` rather than `agent_timeout`.

Neither unrelated behavior was modified or hidden. Existing Returns-dependent
example/HTTP expectations now explicitly assert pending/UNCERTAIN and missing_image
instead of assuming the removed historical-label stub completes its judgment.

Commands:

```text
python -m pytest tests/integration/test_returns_adapter.py tests/e2e/test_returns_specialist.py -o addopts='' -q -p no:cacheprovider
python -m pytest -o addopts='' -q -p no:cacheprovider
python -m pytest submissions/karthikk-2003/tests -q -p no:cacheprovider
```

The last command runs from the original Round 2 checkout. Test dependencies were
installed into this clone's ignored `out/test-deps` and selected with PYTHONPATH;
PYTHONDONTWRITEBYTECODE was enabled. Installed test versions included pytest 9.1.1,
Pillow 12.3.0, FastAPI 0.142.2, Starlette 1.7.0, httpx 0.28.1 and jsonschema 4.26.0.
Starlette warns that its httpx TestClient compatibility is deprecated. No production
behavior was changed to suppress that warning.

## Changed files

- `agents/returns/app.py`, `agent.json`, `README.md`.
- Added `agents/returns/adapter.py`, `input_resolver.py`, `request_store.py`,
  `PROVENANCE.md`, this validation report and `core/provenance.json`.
- Added nine unchanged engine files under `agents/returns/core/returns_manager/`:
  `__init__.py`, `domain.py`, `validation.py`, `observations.py`, `vision.py`,
  `rules.py`, `storage.py`, `service.py`, `ollama.py`.
- Added `tests/integration/test_returns_adapter.py` and
  `tests/e2e/test_returns_specialist.py`.
- Updated `tests/conftest.py` for explicit synthetic configuration and isolated
  durable state; updated `tests/e2e/test_examples.py` and
  `tests/e2e/test_http.py` for honest Returns pending outcomes.
- Updated `requirements.txt` with `Pillow>=10` and `docs/decisions.md`.

## Review checks and limits

- All nine engine files matched original bytes before Git normalization. Portable
  per-file provenance hashes are tested.
- Diff whitespace check passed. Secret-pattern scan found no private key blocks,
  OpenAI/GitHub/Google API token patterns or AWS access-key IDs in the added Returns
  implementation/tests. This is a pattern scan, not a proof against all possible secrets.
- No changes to pod.json, shared schemas/contracts, orchestration, role assignment,
  organizer CSV, Receiving, Prep, Pack or Recovery. No Round 2 source changes.
- Durable replay is exercised after a real process restart and across concurrent
  worker processes/threads. Interrupted reservations deliberately require operator
  reconciliation instead of an automatic inference retry.
- The actual Ollama adapter/transport boundary is reachable and mock-tested. No real
  model/service invocation was made and no live inference success is claimed.
- Production collection export remains blocked: existing CollectionLineage records
  carry ingestion time, whereas the Round 3 envelope requires physical capture time.
  They are rejected rather than relabelled. No new physical capture lineage was invented.
- Deployment must provide trusted configuration and an authenticated caller boundary,
  retain local durable state and verify model latency. The original provider's socket
  timeout is not a hard end-to-end deadline.
