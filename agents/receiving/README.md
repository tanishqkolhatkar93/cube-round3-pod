# Receiving Manager

Owner: @zainbuilds-dev. The Round 2 observation/check core is adapted to the
Round 3 agent contract. AI supplies typed observations; deterministic checks
make decisions. The Specialist order remains Receiving -> Pack -> Returns ->
Recovery, with the existing routing conditions.

## Install and run

Install `pip install -r requirements.txt`; it includes the Receiving dependency list.
Launch `uvicorn agents.receiving.app:app --port 8101`, or use the existing inproc
manifest. Both paths validate the request. Receiving rejects nonempty
previous_evidence because it is the first stage. /health reports process readiness
and provider_configured separately; it does not make a provider call.

Configure these server-side environment variables before starting:
- INPUT_DIR: trusted input root (default data/input).
- RECEIVING_CAPTURE_REGISTRY: trusted JSON file described below. Its default is
  fixtures/captures.json, registering the 23 staged synthetic demonstration captures.
- RECEIVING_UNIT_REGISTRY: trusted PO/specification registry in the same shape as
  fixtures/units.json. Defaults to that file; organizer sample PO specifications
  remain a demo fallback for known sample units. Observed labels/verdicts are
  never read from sample data.
- RECEIVING_STATE_DIR: durable local SQLite request ledger (default out/receiving).
- RECEIVING_CACHE_DIR: local observation cache (default out/receiving-cache).
- GEMINI_API_KEY: environment credential; never put credentials in source/config
  artifacts. No implicit repository .env loading.
- GEMINI_MODEL: primary model; GEMINI_FALLBACK_MODELS: optional comma-separated
  explicit fallback list. RECEIVING_TIMEOUT_S: total extraction deadline,
  default 20 seconds. SDK retries are disabled; explicit attempts are counted.

## Trust and capture registration

Authentication is supplied by the deployment and the hardened orchestrator,
not by an org_id string. Keep the direct agent endpoint private or behind trusted
authentication. The orchestrator's authenticated tenant context must determine
the request's org. A valid org/subject pair is checked against trusted PO data.

A trusted intake/operator process must register actual capture bytes, separately
from request input. Do not let callers write the registry, PO data, input files,
ledger or cache. Example registration shape (use the actual 64-character SHA256):

```json
{"captures":[{"org_id":"org_demo_alpha","subject_id":"UNIT-9001",
 "ref":"UNIT-9001/receiving/carton.jpg","sha256":"<actual lowercase SHA256>"}]}
```

All registrations for a tenant/subject are required for a complete inspection.
Register exactly one current capture set per subject; update it deliberately when
a new inspection is authorized. The supplied input list must contain that set.
Original forward-slash refs are preserved. Unsafe/duplicate/unregistered refs,
wrong tenant/subject, digest mismatches, symlinks/junctions and out-of-root paths
are refused. Filename fallback is removed. Every actual byte digest must match
the trusted registration, and any digest supplied by the request.

This is not protection against a hostile filesystem owner or a process able to
replace files during checks. Trust and protect the host and configured storage.
The default registry authorizes only the exact staged synthetic bytes for their
registered owner. Replace it with a trusted production registry before deployment.
Synthetic fixtures are not physical receiving evidence. UNIT-0012 and UNIT-0039
are known mismatches against their sample PO specifications; keep adverse or
uncertain judgments, and do not treat those fixtures as passing examples.

## Decisions and failures

Every applicable core check contributes to the exported verdict, including
units_per_carton. FAIL dominates UNCERTAIN, then PASS. Granular evidence remains
in payload. Label normalization is case/whitespace aware; number/unit spacing
is normalized for variants. Arbitrary substring matches are not identity proof;
contradictory image labels require review. Observation quantities are nonnegative.

Missing required inputs => pending/upstream_missing. Unauthorized or invalid
capture membership/hash => error/capture_rejected. Invalid image bytes and
provider initialization/timeout/response failures produce structured uncertain
results. Partial capture/extraction failure never exports PASS. All images
rejected by the deterministic quality gate produce completed/UNCERTAIN checks;
mixed accepted/rejected images produce pending review. Model setup happens only
after image validation, quality rejection and cache lookup. No credential is
required to reject an invalid/dark image or report missing captures.

Provider exception text is not exported. payload diagnostics and provider_attempts
contain safe codes and model identifiers. model.calls counts actual attempted
SDK calls, including retries/fallback; cached observations retain the real model
identity. Multiple models are represented by a comma-separated version plus the
per-image model list in payload.

Capture time comes from trusted PO/fixture metadata. If unavailable, the required
schema timestamp uses a clearly marked unavailable placeholder; it is not claimed
as the capture time. Request-supplied timestamps do not override trusted metadata.

## Replay and concurrency

The canonical record ID is `RCV-` plus the first 12 hexadecimal characters of
SHA256(request_id), preserving Zain's scheme on pending, error and completed paths.
The SQLite lookup key separately includes org, workflow, subject and request ID.
Identical raw request IDs across scopes therefore share a display record ID but
have independent replay entries. Use globally scoped request IDs, as the current
orchestrator does, when collecting records in a store keyed only by record ID.
The 48-bit identifier is not an authorization token or collision-proof identity.
Fingerprinting includes request content, trusted specifications/capture bindings,
actual capture bytes/availability, policy and model configuration. Identical
requests return the persisted output verbatim, including timestamps/errors.
Changed content under the same scoped ID is a 409 conflict (AgentRejected inproc).
Capture arrival after an earlier missing result is changed content: use a new
request attempt ID. The orchestrator already uses :r2, :r3, etc. on resume.

SQLite transactions serialize local processes through inference and publish only
complete results. A crash before commit rolls back; retry may repeat a provider
call. Exactly-once external inference and distributed/multi-host operation are
not promised. Keep the ledger across restart. Local lock contention is bounded
(60 seconds for the request ledger); it can return service unavailable.

The extraction cache is separate from replay, uses atomic SQLite publication,
and serializes misses. Its content-based key includes model/fallback configuration
and prompt content. Observations are PO-blind; cache sharing on identical bytes is
not capture authorization. Host filesystem owners remain trusted. Do not use
network filesystems or delete the ledger to bypass a conflict.

## Offline tests

`python -m pytest agents/receiving/tests tests -p no:cacheprovider`

Tests use temporary registries/state/cache and controlled observations/transports,
never live Gemini. Existing assertion changes are deliberate: unsafe captures
cannot be silently dropped, and changed capture content cannot replace a prior
result under the same request ID. Live provider quality and production capture
registration remain deployment validation tasks.

## Combined integration

Reconciled from Test 911abdb, Zain integrate/receiving-manager 48e63ce, and
fix/receiving-safety 2e16f37. See RECONCILIATION.md for every overlap and decision.
No Next.js/other agent or orchestration changes are included. Shared make_input
keeps discover_inputs; tests isolate input/state/cache/registration per test.
Explicit reconciliation tests opt into all 23 staged captures and exercise the
real quality/extraction/check pipeline with offline observations. Test isolation
does not grant automatic production authorization based on filenames or hashes.
