# Configuration readiness — 10 October 2026

Checked main at `06a734e92bf9ea74ff39d93bdb8e27cf6c6c9d20` plus the preserved
local stabilization changes. No production registrations or credentials were
created. No live inference was performed. This is a targeted configuration check,
not a certification of model availability or production readiness.

## Current readiness matrix

| Component | Required configuration | Current initialization/readiness | Offline test | Live inference |
|---|---|---|---|---|
| Orchestration | Tenant access tokens; trusted manager configuration; writable store | Imports/starts; authenticated use blocked by absent tokens. No root `.env`. Default flow/inproc manifests available. | Authenticated FBA/MFN API workflows and disk-store reopen/replay verified | No model of its own |
| Receiving | Trusted unit/capture registries; input bytes; writable ledger/cache; Gemini configuration for new observations | Initializes with defaults. All 23 default synthetic capture files match registry hashes. Production captures not supplied. Key present, validity unverified. | Existing observation fixture; real resolver/rules/ledger | Required for fresh model observations; exact replay/cache may avoid it |
| Prep | PREP_CONFIG, PREP_STATE_DIR; registered criteria/images; explicit Gemini selection for fresh observations | Module imports; configured adapter unavailable because both variables are absent | Existing SyntheticPrep fixture, actual adapter/rules/evidence | Required for fresh decisive observations |
| Pack | PACK_CONFIG, PACK_STATE_DIR; registered order/images; Gemini provider block | Module imports; configuration unavailable because both variables are absent | Existing Scenarios fixture, actual registered-input checks/rules | Required for fresh image observations |
| Returns | RETURNS_CONFIG, RETURNS_STATE_DIR; explicit tenants and synthetic or existing capture source | Module imports; configured adapter unavailable. Production physical capture provenance remains a documented blocker | Existing synthetic CSV correctly remains uncertain; registered source/provider transport tests run offline | Not for stored replay or synthetic mode; explicit Ollama/Groq/Gemini for live inspection |
| Recovery | RECOVERY_CONFIG, RECOVERY_STATE_DIR; complete registered fee report and trusted upstream agents/evidence; policies where needed | Module imports; configuration unavailable because both variables are absent | Existing report fixtures exercise deterministic judgments | Only unresolved eligible fees need configured Gemini; deterministic and complete zero-charge cases do not |

"Offline ready" means opt-in tests, not that the normal application silently
uses fixtures. Health validates local configuration to varying depth; it does
not authenticate a cloud key, probe a model, or prove every input is present.

## Environment inventory

All paths/settings below are non-secret unless marked **secret**. Source
registrations can still contain sensitive business data and require protected
operator ownership. Use absolute paths for deployment. Relative paths resolve
from the process working directory; registration source paths resolve beneath
the registration JSON's directory, except Receiving's separate INPUT_DIR root.

| Variable | Consumer and format | Default / current observation |
|---|---|---|
| ORG_ALPHA_TOKEN, ORG_BRAVO_TOKEN | orchestration.api; **secret**, distinct nonempty high-entropy tenant tokens, not `replace-with-*` placeholders | No default; both absent. Configure each tenant to be used |
| ORCH_MODE | clients.client_for; exact `inproc` or `http`; empty/unset uses manifests | All current manifests use inproc. Invalid values now reject rather than silently selecting HTTP |
| ORCH_FLOW | orchestration.api; valid flow JSON path | Flow from pod.json; unset |
| OUT_DIR | FileStore; writable durable directory | `out`; unset |
| INPUT_DIR | orchestrator discovery and Receiving; trusted capture root | `data/input`; unset |
| DATA_DIR | shared sample_data; sample specifications/routing CSV directory | `data/sample`; unset. Not a source of model observations |
| RECEIVING_UNIT_REGISTRY | Receiving; JSON unit/specification registry path | `agents/receiving/fixtures/units.json`; unset override |
| RECEIVING_CAPTURE_REGISTRY | Receiving; JSON ownership/hash registrations | `agents/receiving/fixtures/captures.json`; unset override; 23/23 files verified |
| RECEIVING_STATE_DIR | Receiving SQLite ledger directory | `out/receiving`; unset |
| RECEIVING_CACHE_DIR | Receiving observation cache directory | `out/receiving-cache`; unset |
| RECEIVING_TIMEOUT_S | Receiving; positive finite seconds, use documented 20-second budget | `20`; unset |
| PREP_CONFIG, PREP_STATE_DIR | Prep app; trusted JSON path and writable durable directory | Neither has a default; both absent |
| PACK_CONFIG, PACK_STATE_DIR | secure_runtime; trusted JSON path and durable directory | Neither has a default; both absent |
| RETURNS_CONFIG, RETURNS_STATE_DIR | Returns app; trusted JSON path and durable directory separate from source DB | Neither has a default; both absent |
| RECOVERY_CONFIG, RECOVERY_STATE_DIR | secure_runtime; trusted JSON path and durable directory | Neither has a default; both absent |
| GEMINI_API_KEY | Receiving and Returns; **secret**; also Prep/Pack/Recovery if their JSON api_key_env names it | Present, printable/nonwhitespace. Authentication, quota and model access NOT verified |
| GROQ_API_KEY | Returns Groq; **secret**, printable credential | Present, printable/nonwhitespace. Authentication/quota NOT verified |
| GEMINI_MODEL | Receiving and Returns; model identifier | Unset. Receiving defaults to `gemini-3-flash-preview`; Returns defaults to `gemini-3.8-flash`. These are code defaults, not verified availability |
| GEMINI_FALLBACK_MODELS | Receiving only; comma-separated explicit model list | Empty. No implicit fallback added |
| GEMINI_TIMEOUT_SECONDS | Returns Gemini; finite positive seconds, adapter maximum 20 | Engine default 90 is incompatible with adapter budget; explicitly set <=20 or override in JSON settings |
| GEMINI_FREE_TIER_CONFIRMED | Returns Gemini; exact `1`, operator confirmation | Absent; live Gemini selection rejected unless explicitly confirmed (or valid JSON setting supplied) |
| RECEIVING_URL, PREP_URL, PACK_URL, RETURNS_URL, RECOVERY_URL | HTTP clients; internal service base URLs | Manifest localhost ports 8101–8105; used only in HTTP mode |
| LOG_LEVEL, LOG_FORMAT | shared logging; Python log level; `json` for JSON formatting | WARNING/json; template selects INFO/json |
| ORCH_DEMO_PRINCIPAL | Explicit server-side demo identity bypass | Unset; leave unset for authenticated console testing/use |

Prep/Pack/Recovery `api_key_env` can name another secret environment variable;
its name comes from trusted JSON, not the request. Their model/deadline settings
come from JSON, not global GEMINI_MODEL. Recovery's directly callable interpreter
has environment defaults, but the integrated bounded runtime uses explicit JSON.

OLLAMA_BASE_URL, OLLAMA_MODEL and OLLAMA_TIMEOUT_SECONDS are read by the inherited
OllamaConfig.from_env helper, **not by the Round 3 selector**. For this application
put those settings in RETURNS_CONFIG.provider.settings. There is no supported
GROQ_MODEL or GROQ_TIMEOUT_SECONDS setting. Generic template entries
ANTHROPIC_API_KEY, OPENAI_API_KEY and MODEL_NAME do not configure these five runtimes.

## Exact registration/provider interfaces

- **Receiving:** capture JSON is `{captures:[{org_id,subject_id,ref,sha256}]}`;
  unit JSON is `{units:{subject_id:{org_id,...PO/specification fields}}}` as in
  `agents/receiving/fixtures/units.json`. Refs must resolve safely under INPUT_DIR
  and match registered bytes and ownership. The built-in samples are synthetic.
- **Prep:** `{version:1,org_id,bindings,client_id?,provider?}`. Each binding has
  subject_id, workflow_id, capture_id, captured_at, criteria, images, with optional
  operator_id/material. Documents/images have ref, path, sha256. Criteria must
  satisfy the rule-pack schema in the Prep README. Provider is
  `{kind:"gemini",model,api_key_env,deadline_s}` with a 0.01–20 second deadline.
  One production registration serves one org/client; the test router is not a
  deployed multi-tenant configuration feature.
- **Pack/Recovery:** `{version:1,bindings,provider?}`. Required binding fields are
  org_id, subject_id, workflow_id, captured_at, files, trusted_agents; optional
  fields include refs, client_id, trusted_overrides, fee_policies, order_lines.
  Files have ref,path,sha256,kind (`image` for Pack, `document` for Recovery).
  Pack additionally requires refs.order_id and positive integer SKU order_lines.
  Provider is `{model,api_key_env,deadline_s}` with a 0.05–20 second deadline.
  Recovery reports must follow its documented CSV/JSON schema, including source
  completeness, scope, references and supported monetary values.
- **Returns:** synthetic mode uses mode,csv,tenants and the exact organizer CSV
  digest, without a provider. Existing mode uses tenants with organization_id
  and non-null client_id, plus bindings for organization_id,unit_id,record_id,
  database,capture_sha256,inspection,images. Stored inspection needs attempt_id
  and attempt_sha256; live inspection needs a real provider. Images need exact
  capture membership, roles, image/evidence IDs, hash and protected relative path.
  See `agents/returns/README.md` for the persisted source/reference schema.
  Physical-capture timestamps must be genuine; ingestion-only CollectionLineage
  cannot currently be exported as a physical Round 3 capture.

Returns provider JSON selects exactly one:

- Ollama: `{name:"ollama",settings:{base_url,model,timeout_seconds}}`. Loopback
  HTTP URL only, no credentials/redirects; default URL localhost:11434 and model
  qwen2.5vl:3b. Default timeout 240 exceeds adapter budget: explicitly choose <=20.
- Groq: `{name:"groq",settings:{timeout_seconds}}`, plus GROQ_API_KEY. The fixed
  endpoint is api.groq.com/openai/v1/chat/completions; exactly one JPEG is supported.
  Fixed model qwen/qwen3.8-27b and its vision availability remain unverified.
  Default timeout 90 exceeds adapter budget; explicitly choose <=20.
- Gemini: `{name:"gemini",settings?:{model,timeout_seconds,free_tier_confirmed}}`.
  Environment is parsed/validated before JSON overrides. The inherited allowlist
  is gemini-3.5-flash through gemini-3.8-flash. Receiving's default model is not in
  this allowlist. A global Receiving model can therefore break Returns even when
  JSON has an override. Use separate service environments if requirements differ;
  no allowlist or provider policy was changed. Availability/free-tier eligibility
  is not established by a syntactically accepted model name.

## Loading and discovery

Run from the repository root after installing root requirements:
`python -m uvicorn orchestration.api:app --host 127.0.0.1 --port 8100 --env-file .env`.
The operator must first prepare the untracked `.env`; no file was invented here.
Uvicorn's explicit dotenv loading precedes application import. Existing process
environment takes precedence. A bare import or a command without --env-file does
not load it. Restart after changing startup settings, especially Receiving's
import-time key/model/input root, API flow and workflow store.

The console does not upload/register sources. Production discovery scans
INPUT_DIR/<subject_id>/<stage> (direct files only), creates forward-slash refs and
hashes bytes. Pack/Recovery registered refs must match those discovered refs;
registration paths may point to separate protected copies with identical hashes.
Do not put unregistered extra files in a stage directory. Returns/Prep additionally
resolve trusted registered sources themselves; submitted refs remain assertions.

## Failure distinctions and verification limits

- Missing keys are local configuration failures; presence/character validation
  cannot establish that a key is valid. No remote authentication was attempted.
- Returns mocked HTTP 401/403, 404, 429, 503, network and timeout paths exercise
  sanitized authentication/model/rate-limit/overload/availability categories.
  Not every manager distinguishes every HTTP cause: Prep deliberately collapses
  non-200 provider responses into provider_unavailable.
- Malformed envelopes/observations are rejected by real canonical parsers and
  deterministic rules. Missing images are evidence failures, not proof of a bad key.
- No selected model, local Ollama installation, quota, remote availability or live
  observation accuracy was verified. No silent fallback was introduced.
- Existing fixture helpers generated only their documented synthetic scenarios in
  temporary directories. API tests exercise both routes, authentication, real
  filesystem discovery, registration checks, canonical hashes, disk-store reopening,
  identical-request replay without additional observation calls, and missing-image
  Returns uncertainty. They do not establish successful physical Returns inspection.

## Additional changes

Invalid ORCH_MODE previously silently chose HTTP. It now fails explicitly, with
a regression test. Added authenticated configuration/persistence tests using the
existing fixtures and documented RECEIVING_UNIT_REGISTRY in .env.example.
All earlier stabilization changes remain intact. No business rules, authorization,
source registrations, manager implementations, secrets or shared fixtures changed.

## Executed validation

- Initial focused API/provider/adapter selection: 154 passed.
- Final targeted console/configuration checks: 9 passed; the further strengthened
  production-discovery/persistence test was then rerun independently: 2 passed.
- Final full repository suite: 662 passed, 1 existing skip, 1 dependency
  deprecation warning, 126.58 seconds. Command: `python -B -m pytest -o addopts=''
  -q -p no:cacheprovider --tb=short`.
- Changed Python sources compiled; all five actual in-process health endpoints
  were queried without inference (Receiving ok, four other managers degraded).
- Git diff whitespace and changed-file credential/runtime artifact checks passed.
- Negative control: invalid ORCH_MODE test failed before the fix. An intermediate
  run also caught a new test using the wrong tenant (correct production 403);
  the test now explicitly verifies 403 and signs in under the owning tenant.

At the time of the configuration checks above, no live provider requests,
production registrations, .env file, commits, staging, pushes, merges or deployments
were made. Earlier local work remains preserved.

## Subsequent bounded AI readiness checks (2026-10-10)

These results supersede the earlier statements that remote authentication and
model availability were not checked. They do not establish successful inference.

- Read-only Gemini and Groq model-list requests returned HTTP 200 (903 ms and
  937 ms respectively). The configured Receiving model `gemini-3-flash-preview`
  and Returns Groq model `qwen/qwen3.8-27b` appeared in the returned inventories.
  Model-list access does not prove generation permission, free-tier eligibility,
  quota, or image capability. Local Ollama's tags endpoint could not be reached.
- A genuine Receiving handler attempt used the existing three registered
  synthetic UNIT-9001 images and isolated temporary ledger/cache state. It
  returned pending/UNCERTAIN in 2880 ms, with six recorded adapter attempts,
  all classified `model_error`, model version `unavailable`, and unknown cost.
  This is not evidence of six accepted or billed generations. The error mapping
  does not establish the underlying provider rejection cause. Evidence schema
  and canonical hash validation passed; exact replay returned the same result.
  No further live retry was made.
- The user conditionally authorized one Groq demo request from the existing
  Returns runtime. Read-only inspection of `runtime/real-products.sqlite3`
  found six captures (RTN-001 through RTN-006). All passed canonical reconstruction,
  tenant/client, record/unit, and lineage checks. None of their 30 image entries'
  stored hashes matched any of the six files under `runtime/demo-images`.
  Therefore **zero Groq inference requests were sent**: the approved runtime
  images do not establish the selected database captures' image bindings.
  The source database SHA-256 remained unchanged and no WAL existed.
- Those captures explicitly declare `ingested_at_not_photographed_at` and null
  client scope. Their collection lineage must not be relabeled as a physical
  capture. Round 3 existing-source execution additionally requires explicit
  client scope, approved registration, and a supported physical capture timestamp.
- Gemini Returns free-tier use remains unconfirmed; its guard was not enabled
  and no Gemini Returns inference was attempted.
- Latest offline regression command: `python -B -m pytest
  tests/integration/test_returns_providers.py
  tests/integration/test_console_stabilization.py
  tests/e2e/test_configured_console.py -o addopts='' -q -p no:cacheprovider --tb=short`.
  Result: **75 passed**, one dependency deprecation warning, 12.53 seconds.

Next prerequisites: supply the original hash-matching images for the approved
demo capture before authorizing another bounded test; supply approved per-manager
registrations and Returns source scope/timestamps for a real Round 3 workflow.
No production registration or physical provenance was fabricated. No source
database records were changed. Successful live AI assessment remains unverified.

## Rescue sprint follow-up (2026-10-10)

The preceding image search was limited to runtime/demo-images. The original
collection directory in the adjacent Returns repository was subsequently found.
All five stored RTN-001 image entries matched their original files. Canonical
capture reconstruction, tenant/record/unit scope, image membership, JPEG decoding,
and the selected image SHA-256 were validated before inference.

Exactly one authorized Groq request then ran through the current Returns provider,
vision parser, canonical run validator, and deterministic assessment rules:

- Requested and returned model: `qwen/qwen3.8-27b`; HTTP 200; 2244 ms.
- Envelope and observation JSON parsed; run status `validated`; no provider error.
- Assessment disposition: `pending_review`. Missing verified catalogue/policies,
  client context, physical capture time, and independent annotations remain blockers.
- Source database SHA-256 unchanged. No source records or new trusted registrations
  were written. This was an isolated collection demo, not a production Round 3
  handler workflow or a physical-capture assessment. No automatic retry occurred.

Windows User variables now contain GEMINI_API_KEY, GEMINI_API_KEY_2, and
GEMINI_API_KEY_3. The current process sees only the primary name. Restart services
to inherit updated variables. GEMINI_FREE_TIER_CONFIRMED is absent in both scopes;
no Gemini generation was attempted in this sprint and the guard remains intact.
Prep, Pack, and Recovery already support explicitly choosing an environment name
via api_key_env. Receiving and Returns use GEMINI_API_KEY in their service process.
No credential pool, rotation, or quota failover was added; optional keys remain unused.

Ollama is installed, but a bounded request to its loopback tags endpoint timed out.
No model download or Ollama inference was attempted.

Receiving's real SDK request serialization was tested with a local HTTP transport.
It reaches that transport; historical live failures cannot be retrospectively
classified because their original error category was discarded. The adapter now
maps SDK HTTP errors to fixed authentication/request/model/quota/overload categories,
without retaining raw messages, and does not retry those errors or try fallback
models. The engine stops further images after these provider rejections while
preserving accumulated accounting and incomplete-result semantics. Thirteen new
offline regression cases cover SDK HTTP mapping and per-unit early termination.
Malformed-response validation and explicitly configured fallback behavior remain.

The initial focused run passed 186 tests before adding the six engine-termination
cases. Changed Python sources compiled in memory; all five manager apps imported.
Final validation: all 117 Receiving tests passed (17.34 seconds); the full root
suite passed 662 tests with one existing skip (123.18 seconds). The root suite
does not discover agents/receiving/tests, which was run separately. Both reported
the existing Starlette/httpx deprecation warning. All 13 new regression cases also
passed independently. Git diff --check passed; the index remained empty.
No business rules, capture authorization, replay identities, or source evidence
were changed. Full configured end-to-end live execution remains blocked by the
missing approved Prep/Pack/Returns/Recovery registrations and source prerequisites.

## Explicit credential-selection follow-up

The user-created root .env now exists, is Git-ignored, and loads distinct tenant
tokens via python-dotenv / the documented uvicorn --env-file launch. The actual
API returned HTTP 200 from /health with that environment. This does not establish
that every manager has valid configuration. No manager registration paths or
Gemini free-tier confirmation were supplied by that file.

Receiving and the Round 3 Returns provider wrapper now accept the optional
process variable GEMINI_API_KEY_ENV. Its only allowed values are GEMINI_API_KEY,
GEMINI_API_KEY_2, and GEMINI_API_KEY_3; absence selects GEMINI_API_KEY exactly as
before. A missing selected key does not fall back. Unknown selectors fail with
fixed diagnostics. The immutable Returns core and its provenance remain unchanged.
Prep, Pack, and Recovery retain their existing per-provider api_key_env selection.
No key values, rotation, or cross-key retry logic were added.

The current process still lacks the two optional keys present in Windows User
variables: restart the application from a refreshed environment before explicitly
selecting them. Do not enable GEMINI_FREE_TIER_CONFIRMED unless project eligibility
has been confirmed. Returns additionally needs a provider timeout at most 20 seconds
(GEMINI_TIMEOUT_SECONDS=20 or its registered provider settings); keys alone do not
provide capture registrations, client scope, physical timestamps, or policies.

No live inference was repeated in this follow-up. Gemini generation remains
unverified, and Ollama's tags endpoint returned a connection timeout. The preceding
single Groq image test remains the genuine validated inference result.
Six new offline cases verify default/explicit selection in actual Receiving config
and Returns provider initialization, the retained free-tier guard, secret-free
public configuration, missing-key rejection, and invalid-selector rejection.
The focused Receiving/Returns/credential run passed 189 tests; four changed Python
files compiled in memory and git diff --check passed.
Final root-suite result: 668 passed, one existing skip, one dependency deprecation
warning, 116.63 seconds. This is separate from the Receiving-local suite included
in the 189-test focused run. No new live inference or source database writes occurred.
