# UNIT-0014 deployment diagnosis and verification

Inspected 2026-10-10. Local checkout was `main`, despite the requested branch
being `feature/returns-manager`. No branch switch was performed. Existing changes
to frontend/app.js and docs/IMAGE-FIRST-CONSOLE.md were left alone.

## Observed deployed state

Public GET https://cube-round3-pod-yjee.onrender.com/health returned degraded,
standard-v1, all five managers inproc. Receiving reported provider_configured=false;
Prep, Pack, Returns and Recovery reported degraded. No revision was supplied.
The workflow's 12 records and detailed errors were supplied by the operator;
the authenticated workflow was not fetched or modified. Record count is not
evidence of 12 successful assessments.

The operator's screenshot subsequently confirmed Groq key variables in Render.
Those keys do not select Groq automatically: the inspected deployed Receiving
still reported an absent Gemini credential. Groq support for the other managers
was then explicitly requested and implemented locally as described below.

The deployed commit/branch cannot be established from these manager version
strings. The new health response includes the Render-provided RENDER_GIT_COMMIT
only when it is a 40-character hexadecimal SHA. Compare it with the actual
deployed commit after publishing; do not manually claim a revision for other code.

## Exact causes and boundaries

- Receiving: agents/receiving/app.py `_execute` produces the reported message
  when `run_engine` returns extraction errors. Model `none/unavailable` means no
  successful model attribution and no counted calls, not a model named "none".
  agents/receiving/core/extraction/gemini.py `GeminiProvider.__init__` refuses an
  empty CFG.gemini_api_key with provider_configuration_required. Deployed health
  independently confirms this missing effective key. The historical record's
  exact error.code/payload.diagnostics must still be inspected; initialization,
  cache or image failures can also precede a model call.
- Prep: agents/prep/app.py `configured_adapter` requires both PREP_CONFIG and
  PREP_STATE_DIR. The reported prep_configuration_required proves at least one
  was empty/missing at execution. Which one cannot be distinguished from that
  message. An API key does not supply a registration.
- Pack: orchestration/orchestrator.py `applies` and `new_workflow` skip Pack for
  FBA in orchestration/flow.json. The displayed route predicate is skipped_reason,
  not an exception from Pack execution. agents/secure_runtime.py `request_boundary`
  separately refuses non-MFN direct Pack requests. Its degraded health indicates
  its configuration cannot load, but it did not cause this FBA workflow failure.
- Returns: agents/returns/app.py `configured_adapter` requires RETURNS_CONFIG and
  RETURNS_STATE_DIR. At least one was empty/missing at execution. Existing-source
  bindings additionally need explicit client scope, canonical capture lineage,
  physical capture timestamps, matching images and stored/live inspection choice.
- Recovery: agents/secure_runtime.py `configuration('recovery')` raises
  configuration_required if RECOVERY_CONFIG or RECOVERY_STATE_DIR is empty/missing.
  Recovery needs registered complete reports and trusted upstream evidence. A
  Gemini key is needed only for eligible fee lines requiring model interpretation.

Health diagnostics are offline configuration checks, not proof of source validity,
state-directory writability, remote authentication, quota or model availability.
The status field retains handler/config-loader health semantics; inspect error,
provider_status, provider_required and source_validation too. A configured provider
is reported as not_verified, never as successfully tested. Returns health no longer
creates a requests database just by constructing its adapter.

## Local and Render settings

Locally, restart from a process that inherited updated Windows User variables and
launch `python -m uvicorn orchestration.api:app --port 8100 --env-file .env`.
Importing modules alone does not load .env. Receiving caches configuration at import
time. Existing process variables take precedence over dotenv values.

In Render's Environment dashboard configure the following independently. Windows
User variables and the ignored local .env are not uploaded by this application.
render.yaml currently declares Python 3.12.11, tenant token placeholders and
OUT_DIR=out; its startup command has no --env-file. It supplies no manager config,
source provisioning, model credentials or persistent disk.

- Common: unique ORG_ALPHA_TOKEN and ORG_BRAVO_TOKEN; OUT_DIR on durable writable
  storage; INPUT_DIR pointing to approved sources; ORCH_MODE=inproc for this
  single service; ORCH_FLOW=orchestration/flow.json for standard-v1 (or retain
  the pod.json default). LOG_LEVEL/LOG_FORMAT are optional. Do not enable the
  ORCH_DEMO_PRINCIPAL authentication bypass. HTTP mode instead needs each
  RECEIVING_URL/PREP_URL/PACK_URL/RETURNS_URL/RECOVERY_URL and protected services.
- Receiving Gemini: GEMINI_API_KEY_ENV selects exactly GEMINI_API_KEY, GEMINI_API_KEY_2
  or GEMINI_API_KEY_3; provide that selected secret in Render. GEMINI_MODEL selects
  its model (current default gemini-3-flash-preview); RECEIVING_TIMEOUT_S defaults
  to 20. Leave GEMINI_FALLBACK_MODELS unset. For Groq set RECEIVING_PROVIDER=groq,
  RECEIVING_GROQ_MODEL=qwen/qwen3.8-27b, GROQ_API_KEY_ENV to exactly one of the four
  supported Groq key names, and supply that key. RECEIVING_TIMEOUT_S must be at
  most 20 for Groq. Default provider remains Gemini. Set RECEIVING_UNIT_REGISTRY,
  RECEIVING_CAPTURE_REGISTRY, INPUT_DIR, RECEIVING_STATE_DIR and RECEIVING_CACHE_DIR
  to provisioned source/state paths. Default fixture paths are synthetic demos.
- Prep: PREP_CONFIG, PREP_STATE_DIR. Registration provider must have kind=gemini or groq,
  model, api_key_env and deadline_s (maximum 20). Set the secret named by api_key_env
  in Render. This JSON selection, not GEMINI_MODEL or GEMINI_API_KEY_ENV, controls
  Prep. For Groq use model=qwen/qwen3.8-27b and one of GROQ_API_KEY/_2/_3/_4 as api_key_env.
- Pack (MFN): PACK_CONFIG, PACK_STATE_DIR. Registration provider has model,
  api_key_env and deadline_s (0.05–20). Optional kind defaults to gemini for existing
  registrations; set kind=groq, model=qwen/qwen3.8-27b and the selected Groq api_key_env
  explicitly to use the new transport. Supply the selected environment secret.
- Returns: RETURNS_CONFIG, RETURNS_STATE_DIR. Existing/live mode selects one
  provider.name and provider.settings in JSON. Groq uses GROQ_API_KEY_ENV selecting
  exactly GROQ_API_KEY or _2/_3/_4, plus that secret. Its model is fixed in the
  adapter at qwen/qwen3.8-27b and requires one validated JPEG per inspection.
  Groq settings allow timeout_seconds only, at most 20. This existing Returns
  one-image contract is unchanged; the new managers have their own adapters.
  Gemini uses GEMINI_API_KEY_ENV and selected key; settings.model/timeout_seconds/
  free_tier_confirmed override GEMINI_MODEL/GEMINI_TIMEOUT_SECONDS/
  GEMINI_FREE_TIER_CONFIRMED. Current code allowlist: gemini-3.5-flash through
  gemini-3.8-flash. Keep the free-tier guard; confirmation must be factual.
  Ollama uses settings.base_url/model/timeout_seconds and a reachable approved
  server, not a cloud API key; localhost on Render is not the Windows host.
  Stored replay and synthetic mode do not require a live model key. Synthetic
  mode lacks inspection photos and is not a successful physical assessment.
- Recovery: RECOVERY_CONFIG, RECOVERY_STATE_DIR. Optional provider has model,
  api_key_env and deadline_s (0.05–20); supply that key only for model-assisted
  fee interpretation. Complete zero-fee reports and supported deterministic
  decisions do not require model calls. Optional kind defaults to gemini; select
  kind=groq, model=qwen/qwen3.8-27b and a supported Groq api_key_env to use Groq.

## Explicit Groq selection for the new managers

After deploying the reviewed code, Receiving can use these dashboard settings
(names and public selectors only; enter the secret through Render separately):

```dotenv
RECEIVING_PROVIDER=groq
RECEIVING_GROQ_MODEL=qwen/qwen3.8-27b
GROQ_API_KEY_ENV=GROQ_API_KEY_2
RECEIVING_TIMEOUT_S=20
```

Prep, Pack and Recovery use this provider object inside each approved registration.
This is a provider fragment, NOT a complete registration or permission to invent
the missing bindings, hashes, timestamps or policies:

```json
{"kind":"groq","model":"qwen/qwen3.8-27b","api_key_env":"GROQ_API_KEY_2","deadline_s":20}
```

Returns retains its existing selection shape:

```json
{"name":"groq","settings":{"timeout_seconds":20}}
```

Supply GROQ_API_KEY_2 in Render when selecting these examples. It is also valid
to select another one of the four supported names explicitly. A missing selected
key does not fall back to the primary or another key. JSON api_key_env controls
Prep/Pack/Recovery independently of the global GROQ_API_KEY_ENV selector.

The new shared transport uses the existing fixed Groq endpoint, bounded request
and response sizes, one request, no redirects/retries/tools, strict JSON and exact
returned-model validation. The existing killable worker provides a deadline.
Receiving still runs each image through its image gate, cache and ImageObservation
validator; provider selection separates Groq from Gemini cache/replay identities.
The existing Gemini replay identity remains compatible. Prep and Pack submit all
registered views together; more than three images fails before any call, with
provider_image_limit_exceeded. No image is silently dropped. Existing evidence
contracts may allow larger capture sets; those remain usable with their original
provider, not with this bounded Groq adapter. Recovery sends only policy and
eligible evidence as text. Existing parsers, citation validation and deterministic
business rules remain authoritative for every provider.

The three-image limit, JSON mode and model's text/image support were checked against
[Groq vision documentation](https://console.groq.com/docs/vision) and
[the Qwen model page](https://console.groq.com/docs/model/qwen/qwen3.8-27b) on 2026-10-10.
This does not verify the deployed account's permissions, quota or inference quality.

No selector rotates keys. No new fallback or live model request was introduced.
Returns' explicit Gemini settings now merge before validation, so an incompatible
Receiving global model or an unselected credential cannot veto the valid override.
The effective Returns configuration still passes the unchanged core validation.

## Required registrations and evidence

Paths must exist inside the deployed container, not merely on Windows. Provision
operator-approved immutable sources separately from writable runtime state.
Use persistent storage for OUT_DIR and every manager STATE_DIR; the checked-in
free-plan blueprint has no persistent disk declaration. Resolve hosting/storage
capability before relying on history surviving a restart; no plan was changed.

- Receiving: tenant-owned unit/specification and exact image ref/SHA-256 registry.
  All required captures must exist under INPUT_DIR. Synthetic demo images remain
  labeled synthetic; no physical provenance is inferred from them.
- Prep: one org/client config; subject/workflow/capture identity, actual captured_at,
  hash-bound criteria and photos, and required material attestation. Criteria use
  organizer-fba@1-pod14.1. Missing attestations remain uncertain.
- Pack: exact org/subject/workflow binding, physical timestamp, order_id and
  order_lines, hash-bound open-box images, trusted upstream agent identities.
- Returns: tenant/client and source DB binding, record/unit/capture hash, registered
  image membership and hashes, inspection=live or explicit stored attempt/hash;
  approved decision reference where needed. Collection ingestion time is rejected
  as physical capture time. The adjacent real-products.sqlite3 captures have null
  client scope and collection timestamps: they cannot be relabeled to qualify.
- Recovery: exact tenant/subject/workflow binding, timestamp, hash-bound complete
  report with currency, line count, fee scopes/refs; trusted_agents matching actual
  upstream identities; registered versioned fee_policies for model-assisted lines.
  No report, policy, zero-fee assertion or upstream finding may be invented.

See each agents/<stage>/README.md and the actual resolvers for full shapes.
Approved files alone are insufficient if references differ: existing-evidence
discovery uses INPUT_DIR/<subject>/<stage>; Pack/Recovery require the asserted set
to equal the registered set. Image workflows snapshot upload_inputs into context.

## Route and resume decision

Keep UNIT-0014 FBA/returned=true: Receiving -> Prep -> Returns -> Recovery; Pack
stays skipped. No different Pack registration is appropriate for this FBA flow.
An MFN Pack test needs a separate, legitimately registered MFN subject. Never
change business route simply to get a passing result.

Open WF-org_demo_alpha-UNIT-0014 instead of creating another image workflow.
Resume preserves route/context, skips completed/skipped stages, retries unfinished
stages with new request IDs and retains old evidence. It is not a reset or evidence
replacement operation. Before resuming inspect context.upload_inputs: if prior
image creation stored empty arrays for unconfigured stages, provisioning files
alone will not refresh that snapshot. In particular Recovery requires the full
registered input set; a stored empty Recovery input set remains a blocker. There
is no implemented UI operation to append a corrected snapshot. Do not edit stored
JSON or bypass the conflict guard; use another genuinely registered subject or a
separately reviewed, audited evidence-amendment feature if that condition applies.

## Operator deployment and verification sequence

1. Review these local changes and the intended branch/commit; this work did not
   stage, commit, switch, push or deploy. Have the authorized release process
   publish the reviewed revision and confirm Render's branch/commit selection.
2. Provision approved registrations and source files for every applicable stage,
   durable state, and selected credentials in Render. Restart/redeploy to load them.
3. Read /health. Confirm revision, standard-v1, manager configuration diagnostics
   and selected-key presence. This check never establishes successful inference.
4. Run a source preflight for UNIT-0014 using the actual server-side resolvers:
   verify tenant/client, source membership, physical lineage, hashes, required
   criteria/policies/reports, and existing workflow context. No inference yet.
5. Sign in as org_demo_alpha. Workflows -> Open by workflow ID ->
   WF-org_demo_alpha-UNIT-0014 -> Open workflow. Inspect the complete evidence
   records, including Receiving error.code, diagnostics and provider_attempts.
6. Only when prerequisites and stored inputs pass, authorize one bounded execution
   through Resume workflow. Do not repeat Validate & start or override failures
   to PASS. Expect Pack to remain skipped. Inspect new records, model/version,
   traceable check citations, hashes and outcome; genuine uncertainty remains valid.
7. Confirm evidence can be reopened after the deployment's normal persistence
   lifecycle. Remote model availability, quotas and real-world correctness remain
   unverified until the authorized execution succeeds.

## Validation performed

- Root suite: 752 passed, 1 existing skip, 3 dependency deprecation warnings,
  121.21 seconds. Command: `python -B -m pytest -o addopts='' -q
  -p no:cacheprovider --tb=short --basetemp=out/groq-managers-full-a`.
- Separate Receiving/Prep/Pack/Recovery suites: 420 passed, 1 dependency warning,
  46.42 seconds. These include tests outside root pytest.ini's testpaths.
- Final readiness/Groq selection: 45 passed, 1 dependency warning, 3.46 seconds.
  Includes four source/citation/cache/rule tests added after the full run.
- Tests used existing out/image-console-test-deps via PYTHONPATH. Initial attempts
  with default dependencies failed collection (missing google-genai); a sandboxed
  run stalled in SDK/subprocess tests and was stopped. Completed runs used isolated
  workspace temporary directories and local process permissions.
- Tests use explicitly synthetic registrations only in isolated test directories,
  mocked HTTP responses and real deterministic validation/rules. No live provider
  inference, Render dashboard login/change, source database edits or deployment.
- Existing frontend/app.js and docs/IMAGE-FIRST-CONSOLE.md edits were preserved.
  No branch switch, staging, commit, push or merge.
