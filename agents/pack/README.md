# Pack Manager — registered captures and deterministic decisions

The actual `agents.pack.app.handle` and `/run` execute `adapter.py`; no organizer
CSV is read in production and no disconnected Round 2 prototype is deployed.

Set `PACK_CONFIG` to an operator-owned JSON registration and `PACK_STATE_DIR` to
a protected durable directory. Registrations must be outside state. The service
is an internal orchestrator capability: protect `/run` with deployment authentication.
JSON organization fields and canonical hashes are not authentication/signatures.
`/health` is degraded without valid configuration. Direct and HTTP requests use
the same validation; wrong ownership is 404, invalid inputs 422, reused request
content conflicts 409. Nothing auto-registers a request's captures.

## Registration (version 1)

The config has `version: 1`, `bindings: [...]` and optional `provider`.
Each binding requires `org_id`, `subject_id`, `workflow_id`, a physical
`captured_at` timestamp with timezone, `files`, `trusted_agents`, and for Pack,
`order_lines` mapping SKU to positive integer quantity. Optional `refs` contains
order join keys. Each file has `ref`, relative `path`, SHA-256 `sha256`, and
`kind: image`. Paths are relative to the config directory. Register all required
views. Requests MUST submit the complete registered set with matching hashes.
Only PNG/JPEG/WEBP images up to 10 MB and 20 million pixels are accepted (8 files
maximum). Links, path aliases and cross-owner refs are rejected.

`trusted_agents` maps allowed upstream stage names to exact agent IDs. Pack
accepts Receiving audit context only; it never treats earlier PASS as proof that
this order was packed. Upstream schema, hash, scope and references are validated.
Use `client_id` when deployment requires a client boundary.

Provider example (inside config):
```json
{"model":"gemini-3-flash-preview","api_key_env":"GEMINI_API_KEY","deadline_s":20}
```
The key is read from the environment, never stored in config/evidence. There is
one batched REST Gemini invocation with inline image bytes, no retries, and a
killable worker deadline including response and cleanup. Attempt/model accounting
is received before work completes and retained on failure. Unknown actual model
versions remain `unknown`; errors never expose raw provider messages.

The model reports per-image SKU/count observations, visibility and completeness.
It cannot grant SEAL. Every view must be usable, complete and consistent. Missing,
partial, contradictory or malformed observations yield pending/UNCERTAIN.
The three organizer checks (items present, exact quantities, no extra items)
are deterministic; any FAIL produces stop_and_fix. Canonical evidence uses a
scoped SHA-256 identity and durable SQLite replay. Changed request/source/config
content requires a new request ID; interrupted reservations require reconciliation.

Tests use generated images and explicitly injected observations. They do not
certify real model accuracy. Deployments must validate capture coverage and live
provider behavior. Production does not import test fixtures.
