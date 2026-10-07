# Round 3 provider wiring

This change wires existing providers only. No Gemini, Groq or Ollama service was
called. No API availability or real-image inference success is claimed.

## Boundary and selection

`Adapter` calls `providers.select_provider` for explicitly registered live
inspection. The selector accepts only `ollama`, `gemini`, or `groq`, validates
settings, constructs the existing class, and rejects unknown names/settings.
There is no fallback. Synthetic CSV mode still refuses providers; stored attempts
still replay through the existing resolver without inference.

Registered capture -> existing provider -> raw `ProviderResponse` -> unchanged
strict canonical parser -> unchanged deterministic `assess` -> Round 3 evidence
-> unchanged orchestrator. Business dispositions, grades and financial recovery
are never delegated to a model. Contradictions retain the canonical conflict and
uncertainty behavior. Invalid responses are discarded whole.

The twelve modules under `core/returns_manager` are byte-for-byte imports from
Round 2 commit `eb555a998d005345c167dacbdcb1dbe035c7c2ad`; normalized hashes are
recorded in `core/provenance.json`. The original nine remain untouched.

## Configuration for the separate live test

Keep `RETURNS_CONFIG` pointing to an operator-reviewed JSON registration and
`RETURNS_STATE_DIR` pointing to a separate writable runtime directory. Use the
existing-capture registration described in README, with `mode: "existing"`,
explicit tenant, hash-bound database/capture/image registration and
`inspection: "live"`. Keep `allow_fixture` absent or false.

For Gemini, the exact provider block is:

```json
{"provider": {"name": "gemini"}}
```

Set process environment through the operator's secret mechanism:

```text
GEMINI_API_KEY=<operator-supplied secret>
GEMINI_FREE_TIER_CONFIRMED=1
GEMINI_MODEL=gemini-3.8-flash
GEMINI_TIMEOUT_SECONDS=20
RETURNS_CONFIG=<absolute path to separately prepared registration JSON>
RETURNS_STATE_DIR=<absolute path to separate durable runtime directory>
```

`GeminiConfig.from_env()` retains its existing semantics: confirmation is true
only for `1`; model defaults to `gemini-3.8-flash`, timeout to 90 seconds. The
inherited model allowlist is `gemini-3.8-flash`, `gemini-3.7-flash`,
`gemini-3.6-flash`, `gemini-3.5-flash`. These are source-code settings, not newly
verified service availability. Optional JSON `settings` may override `model`,
`timeout_seconds`, and `free_tier_confirmed`; environment parsing must first be
valid. Credentials cannot appear in JSON settings.

The existing Gemini REST endpoint, image parts, observation-only system prompt,
`responseMimeType`, `responseJsonSchema`, free-tier gate and bounded retry behavior
are preserved. No Vertex, location or HTTP redesign was introduced.

For Groq, use this exact provider block:

```json
{"provider": {"name": "groq", "settings": {"timeout_seconds": 20}}}
```

Set `GROQ_API_KEY` through the secret environment mechanism, plus `RETURNS_CONFIG`
and `RETURNS_STATE_DIR` as above. The original Groq config reads only `GROQ_API_KEY`;
there is no invented `GROQ_MODEL` or `GROQ_TIMEOUT_SECONDS` environment setting.
The existing default timeout is 90 seconds, so Round 3 requires the JSON override.
Its fixed endpoint remains `https://api.groq.com/openai/v1/chat/completions`, model
`qwen/qwen3.8-27b`, exactly one hash-bound JPEG, base64 data URI, JSON-object response,
and no retry/fallback. Model vision availability has not been checked live.

All selected providers retain the adapter's existing positive timeout limit of
20 seconds. No hard end-to-end deadline was added. Missing keys, missing Gemini
confirmation, invalid settings and over-budget timeouts fail before request state
creation. Ollama's class, defaults, HTTP implementation and replay settings remain
unchanged; its previously required explicit timeout still applies.

## Errors, secrets and replay

Configuration failures raise fixed `Rejected` codes (HTTP 422); constructor failures
use `<provider>_initialization_failed` (HTTP 503). Unknown names use
`unknown_returns_provider`. No submitted name, setting value, URL or exception body
is interpolated into these errors.

The cloud boundary preserves the engine's existing error codes. Runtime failures
produce pending/UNCERTAIN evidence with `provider_unavailable`, `provider_timeout`,
`provider_failure` or `invalid_response`. A fixed `payload.provider_diagnostic`
adds authentication, request rejection, model-unavailable, overload, rate-limit,
network or other safe categories when the existing implementation provides them.
Gemini categories are allowlisted; Groq HTTP status maps to fixed categories.
Groq already collapses non-HTTP provider-unavailable exceptions, so that path
remains `groq_unavailable`. Unknown exception text is discarded.

No shared contract or pinned error vocabulary changed. Canonical scope/schema
errors retain their original codes. Groq's existing ephemeral validation helper is
preserved; it never repairs output. Diagnostics use thread-local state and cannot
carry into another request or a missing-image result.

Keys are environment-only, excluded from public configuration and durable replay
snapshots. Effective model/timeout/confirmation settings enter the fingerprint;
changing the model conflicts with an existing request ID, while key rotation does
not invalidate an otherwise identical replay. The request-store implementation is
unchanged. Responses containing the configured key or authorization/header markers
are rejected before canonical parsing/persistence, including decoded JSON strings
and response metadata. Exception messages and provider HTTP error bodies are not
persisted. This guard is not a claim to detect arbitrary unrelated secrets.

## Synthetic capture scope

The user confirmed that `DEMO-b052beca-1e9f-4232-bcaf-cb6b92a14b97`, organization
`org_returns_provider_test`, client `client_returns_provider_test`, image SHA-256
`f03972133a5732d735c389823524b997b4d2958a117850a12e98bbf45cf6165b`, remains in the
previous clone's local runtime package. Per the updated instruction, it was not
copied, recreated, altered or used. Resolution of that exact package is deferred
to the separately controlled live task. No timestamp or lineage was fabricated.

Offline tests use independent generated pixels and clearly labelled mocked
observations. They prove existing source resolution reaches both real provider
classes through mocked transports, preserves source bytes and synthetic lineage,
applies unchanged assessment, and replays without a second call. They do not claim
that the user's specific package has been resolved.

## Audit scope and changed files

Inspected in the permanent repository:

- `agents/returns/adapter.py`, `app.py`, `input_resolver.py`, `request_store.py`
- `agents/returns/core/returns_manager/vision.py`, `ollama.py`, `validation.py`,
  `observations.py`, `rules.py`, `service.py`
- `agents/returns/core/provenance.json`, `README.md`, `PROVENANCE.md`, `VALIDATION.md`
- `tests/integration/test_returns_adapter.py`, `test_agent_contracts.py`
- `tests/e2e/test_returns_specialist.py`, `test_examples.py`, `test_http.py`,
  `test_end_to_end.py`; `tests/conftest.py`
- `requirements.txt`, `pytest.ini`, `.gitignore`

Inspected in the original Round 2 repository, read-only:

- `submissions/karthikk-2003/agent/returns_manager/gemini.py`, `groq.py`,
  `observation_diagnostics.py` (including their configuration models)
- `submissions/karthikk-2003/tests/test_gemini.py`, `test_groq.py`
- `submissions/karthikk-2003/.env.example`
- Capture lookup only in `submissions/karthikk-2003/runtime/{returns,ollama-demo,
  real-products,phase5b-demo,fixture-demo,gemini-demo}.sqlite3`, opened `mode=ro`
  before the user clarified the package location. No matching unit was found.

Exactly ten files were added/edited for this task (the earlier transferred changes
are still uncommitted):

- `adapter.py`: delegate selection, fingerprint public effective config, attach
  safe diagnostics to existing evidence payload.
- `providers.py`: small factory and cloud error/credential boundary.
- `core/returns_manager/gemini.py`, `groq.py`, `observation_diagnostics.py`:
  import existing implementations and required helper unchanged.
- `core/provenance.json`: extend pinned hash coverage to these three imports.
- `tests/integration/test_returns_providers.py`: focused offline coverage.
- `README.md`, `PROVENANCE.md`, `PROVIDERS.md`: document selection, provenance,
  exact configuration, validation and live-test limits.

No Round 2 writes, orchestrator/role/shared-contract/other-agent edits, engine
redesign, Ollama edits, new dependencies, commits or pushes were performed.

## Offline validation

The new tests cover explicit selection, missing/invalid configuration, constructor
failure, provider-specific failures, timeout, malformed envelopes, strict canonical
rejection, contradictions, unchanged Groq JPEG restriction, header/credential
sanitization, secret-bearing responses, source preservation, deterministic
assessment and durable replay including effective environment changes.

Cloud tests prohibit sockets and real provider HTTP openers; every provider
response is mocked. Full regression permits local HTTP test servers and blocks
external socket connections. Existing dependencies were read from the prior
clone's `out/test-deps` with bytecode disabled; no dependencies were added to
requirements. The sandbox could not access those packages, so tests used elevated
filesystem access. An initial sandbox package-install attempt failed without
installing packages.

Results on 2026-10-07:

- Initial focused Returns run: **133 passed** (58 then-current new provider
  tests plus 75 existing adapter/Specialist tests).
- Final full Round 3 suite: **231 passed, 2 failed, 1 skipped** in 34.73 seconds.
  All **66 new provider tests**, all 75 existing adapter/Specialist tests, and
  existing agent-contract tests passed. The final suite includes eight additional
  contradiction, JPEG, stale-diagnostic and HTTP secret-handling cases.
- Both failures match the pre-existing failures documented in `VALIDATION.md`:
  `tests/e2e/test_end_to_end.py::test_captures_in_data_input_become_content_addressed_inputs`
  (Windows backslashes), and
  `tests/e2e/test_http.py::test_dead_agent_is_recorded_not_hidden`
  (`agent_timeout` instead of `agent_unavailable`). They were not modified.
- The existing organizer-stub golden-result test remains skipped; one existing
  Starlette/httpx deprecation warning remains.
- `git diff --check` passed; only existing LF-to-CRLF checkout warnings occurred.
  Newly added/edited Python was also compiled without creating bytecode and checked
  for trailing whitespace. All twelve imported modules matched the provenance
  manifest and original Round 2 source.
- Secret-sentinel checks passed for configuration/constructor exceptions, HTTP
  errors, provider failures, evidence, captured logs/output, replay snapshots and
  persisted SQLite state. Actual HTTP requests in transport tests used mock openers.

Regression command: `python -m pytest tests -o addopts='' -q -p no:cacheprovider`,
invoked through `pytest.main` with an external-socket guard and
`PYTHONDONTWRITEBYTECODE=1`.

Live readiness blockers: the intentionally excluded runtime package must be
prepared/reviewed separately; operator credentials and Gemini free-tier
confirmation must be supplied; real model availability and latency remain untested.
The existing production physical-capture timestamp blocker is unchanged.
