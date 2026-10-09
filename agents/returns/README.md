# Returns Manager — Round 3 adapter

Owner: @Karthikk-2003. Agent ID: `returns-manager@1`.

The adapter wraps nine unchanged, pinned Round 2 modules. The orchestrator still owns routing, workflow state, retries, overrides and final outcomes. No Prep record is required. See [PROVENANCE.md](PROVENANCE.md).

## Run the synthetic demonstration explicitly

Install root `requirements.txt` (Pillow is the only added dependency). From the repository root, create an ignored runtime directory, copy the unchanged organizer CSV, and write trusted configuration:

```powershell
New-Item -ItemType Directory -Force out/returns | Out-Null
Copy-Item data/sample/returns_sample.csv out/returns/returns_sample.csv
@{
  mode = 'synthetic'
  csv = 'returns_sample.csv'
  tenants = @(
    @{ organization_id = 'org_demo_alpha'; client_id = $null },
    @{ organization_id = 'org_demo_bravo'; client_id = $null }
  )
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 out/returns/config.json
$env:RETURNS_CONFIG = (Resolve-Path out/returns/config.json).Path
$env:RETURNS_STATE_DIR = Join-Path (Get-Location) 'out/returns/state'
python -m uvicorn agents.returns.app:app --host 127.0.0.1 --port 8104
```

The same environment configures the in-process `handle` entry point. Without both variables, HTTP health is degraded and `/run` returns a sanitized 503. Health checks configuration/storage access, not provider readiness; it never invokes a model.

Synthetic mode accepts only the organizer CSV digest `0cca916d25c9db57495420e4c02cebd1ac298de9fa3f9f148fe3e9289e9b3103`. All 24 rows use the original reader/parser. Their labels remain in `payload.capture.raw_fields` as annotations. No observations are manufactured. All 72 referenced photographs are unavailable: output is pending/UNCERTAIN, `missing_image`, `pending_review`, with the original fixture timestamp and source hash/row. Supplying a provider in this mode is rejected.

## Trusted existing-capture registration

A service operator supplies a JSON configuration with `mode: "existing"`, `tenants` and `bindings`. Paths resolve underneath the configuration file's directory, including symlink resolution. Put the file in the approved source root. This is local trusted configuration, never a request/header field. Restrict filesystem access to configuration, source files and runtime state.

Each tenant has an explicit `organization_id` and non-null `client_id`. One client per organization per service is supported: the existing wire request cannot disambiguate clients. Deploy separate scoped services for different clients. The starter has no authentication; expose this service only behind a trusted, authenticated caller/network boundary. An organization allowlist is not authentication.

Each binding must provide:

- `organization_id`, `unit_id`, `record_id`, `database` (relative existing Round 2 SQLite path).
- `capture_sha256`: SHA-256 of the canonical decoded capture JSON, using `request_store.digest`. The operator anchors this after reviewing the existing source; it is not calculated from submitted request content.
- `inspection: "stored"` plus a positive integer `attempt_id` and `attempt_sha256` (digest of `{"run": <decoded stored run>, "assessment": <decoded stored assessment>}`); or `inspection: "live"` without an attempt ID. There is no automatic/latest choice and no fallback.
- `reference`: optional exact persisted `DecisionReference` dictionary, including its existing source hash, scope, components, source document and verification metadata. Stored replay must match the original assessment's reference. No CSV-to-attestation conversion occurs.
- `images`: explicit registrations with `ref` (exact capture membership), `image_id`, `evidence_id`, `role` (`returned_product` or `returned_packaging`), `kind: "genuine"`, relative `path`, and actual lowercase `sha256`. No basename matching, URL fetches or request-directed file reads.

Stored replay reads the source database with SQLite `mode=ro`, `query_only` and a snapshot transaction. It reconstructs the capture, validates the run/raw response/image descriptors, and recomputes the assessment with the pinned rules. Registered image bytes/roles must match the selected attempt. A missing or changed stored image binding is rejected, never used as verified historic evidence. The original database is never modified.

**Timestamp blocker:** the engine recognizes synthetic `SourceLineage` and ingestion-only `CollectionLineage`. Round 3 defines `captured_at` as physical capture time. Collection captures are therefore rejected with `physical_capture_timestamp_unavailable`; an ingestion timestamp is never exported as a physical timestamp. Existing-capture mode currently supports registered, persisted synthetic lineage for integration/testing, including explicitly supplied real-provider inspection of registered images. It does not claim those captures are genuine physical capture records. Production collection export requires a separately approved upstream timestamp/lineage solution. This task does not invent that solution or change either schema.

## Real inference and fixture separation

Live inspection additionally requires this explicit provider configuration:

```json
{"provider": {"name": "ollama", "settings": {
  "base_url": "http://localhost:11434",
  "model": "qwen2.5vl:3b",
  "timeout_seconds": 20
}}}
```

The adapter constructs the unchanged local Ollama provider, batches the registered images, validates its response and applies the unchanged deterministic rules. No paid API or SDK is required for Ollama. The service/model must already be installed by the operator; the adapter never installs or starts it. Loopback-only, redirect/proxy restrictions come from the original provider. Its timeout bounds socket operations, not a hard total wall-clock deadline; the starter also does not enforce in-process timeouts. Validate deployment latency before using the 30-second stage budget.

Explicit `gemini` and `groq` selection is also supported through their unchanged
Round 2 REST providers. Credentials are environment-only, never JSON settings.
See [PROVIDERS.md](PROVIDERS.md) for configuration, safe diagnostics, offline
validation and the separate live-test prerequisites. There is no provider fallback.

Missing live images and provider failures produce contract-valid pending/UNCERTAIN evidence with the engine's actual error category. Invalid/foreign provider responses are discarded. Live mode requires a real provider and refuses fixture mode. Only explicitly selected stored fixture attempts may be replayed with `allow_fixture: true`; they retain `provider_mode: "fixture"` and cannot create decisive findings. No HTTP/environment fixture-response provider exists.

The real Ollama transport boundary is tested with a mock transport, not with a live model. All generated test pixels and responses are explicitly test fixtures. No live inference success is claimed.

## Evidence and immutable history

`RTN-` record IDs are SHA-256 identifiers bound to tenant and request ID, avoiding global evidence-store collisions between workflows/attempts. The source RTN ID is preserved in payload. Output preserves capture source/hash, original timestamp, canonical assessment, validated run/metadata, source/attempt IDs and traceable input citations. No condition grade/disposition policy is added; `pending_review` remains the engine's disposition. Successful validated observations can yield completed evidence while condition/disposition still need human review.

Previous evidence must have valid hashes and matching workflow, organization and unit scope; an explicitly foreign client is rejected. Original findings are immutable. Latest workflow decision overrides appear separately as effective audit context, never as visual observations or order attestations. Prior evidence is not used to invent a trusted reference. Human review remains separate from automated assessment; no review endpoint or automatic override-write mechanism is introduced.

The unchanged orchestrator treats a pending agent result as an errored stage and may mark the workflow FAILED/provisional. That existing policy is deliberately preserved. Static organizer examples still describe their original stubs; integration tests explicitly assert the new missing-photo behavior.

## Durable replay and recovery

`RETURNS_STATE_DIR` holds `requests.sqlite3` and the existing engine's tenant-scoped `engine.sqlite3`. Retain this directory across service restarts; all workers for the service must share the same local SQLite files. Network filesystems and multi-host coordination are not supported.

Before invoking a provider, SQLite atomically reserves `(tenant, request_id)` with the entire request fingerprint and resolved source snapshot (including selected attempt/images/reference/provider configuration). The exact output and its checksum are durably stored. Identical replay returns that JSON without another inference call. Changed request content, overrides, source snapshot or provider configuration under the same key returns 409. Sources are revalidated on replay; missing/tampered sources are not silently accepted. Configuration and file owners remain part of the trust boundary; hashes alone do not authenticate them.

Concurrent duplicates wait up to five seconds for completion, then return `request_in_progress_or_interrupted` (409). They may resubmit the identical request after the original completes. A caught interruption is marked interrupted; a killed worker leaves a running reservation. Neither is automatically reclaimed: the provider may already have received the request. An operator must reconcile persisted attempts/provider activity before intentionally issuing a **new** request ID. There is no exactly-once external API guarantee across crashes and no automatic destructive reset. Pending results are replayed exactly; a deliberate new inspection needs a new request ID.

HTTP preserves `/health` and `/run`: 404 for unknown/wrong scope, 422 for invalid sources/requests, 409 for replay conflicts, 200 for valid pending evidence, sanitized 503 if no truthful output can be constructed. The in-process rejection subclasses LookupError for the existing client. No schemas or orchestrator changes are required.

## Verification

Run `python -m pytest tests/integration/test_returns_adapter.py tests/e2e/test_returns_specialist.py` and the full root suite. Tests configure the synthetic mode explicitly and isolate durable state per independent test. They cover all 24 rows, source/reference/image validation, failure categories, replay after an actual process restart, concurrent threads/processes, interrupted reservations, provider boundary, fixture separation, immutable upstream evidence and Specialist flow without Prep.

See [VALIDATION.md](VALIDATION.md) for the recorded results and remaining baseline failures.
