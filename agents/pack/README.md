# Tanishq's Pack Manager — repaired Round 3 integration

The actual `agents.pack.app.handle` and `/run` use Tanishq's existing check/evidence
flow and Gemini SDK implementation. Images come from registered request inputs;
there is no organizer CSV fallback. The standalone Round 2 `/verify` route is
retired. Historical UI/design assets are preserved, not deployed as a second agent.

## Install and run

From the Pod root: `python -m pip install -r requirements.txt`. The root policy
includes google-genai >=2.29,<3 through the existing Receiving dependency list,
and Pillow. No Streamlit or SQLAlchemy is required for the production entry point.
`agents/pack/requirements.txt` delegates to this same policy.

Set `PACK_CONFIG` to protected operator-owned JSON and `PACK_STATE_DIR` to a
protected local persistent directory; then run `uvicorn agents.pack.app:app --port 8103`.
Keep service access authenticated by deployment. JSON tenant IDs and hashes do
not authenticate callers. `/health` is degraded if configuration is invalid.

## Trusted registration

Config: `version: 1`, `bindings: [...]`, optional `provider`.
Each binding requires org_id, subject_id, workflow_id, captured_at (actual physical
capture timestamp with timezone), files, trusted_agents, refs.order_id, and
order_lines (SKU -> positive integer count). Optional client_id binds client scope.
Each file requires ref, relative path, sha256 and kind=image. Paths are relative
to the config directory. Only protected registrations authorize image ownership;
requests cannot register their own captures. All registered views must be supplied.

Provider selection: model, api_key_env, deadline_s (maximum 20). The named key is
read from the environment; no key is embedded in registration or evidence. There
is no implicit model fallback. Model/version/usage are reported only when known.

Allowed images are PNG, JPEG or WEBP, at most 8 files, 10 MB and 20 megapixels each.
Bytes are decoded/verified and their SHA-256 must match both registration and
request. Foreign tenant/unit/workflow, conflicting hashes, aliases and untrusted
upstream evidence are rejected. Prior evidence requires schema, hash, agent,
workflow, scope and reference validation before inference.

## Decisions, failures and replay

One SDK call carries all validated image bytes using Part.from_bytes and correct
MIME types. Per-image SKU/count facts must be usable, complete and consistent.
Deterministic items_present, quantities_correct and no_extra_items checks decide
seal versus stop_and_fix. Model SEAL cannot override a failed check. Gemini
UNCERTAIN always yields three UNCERTAIN checks and pending_review. A negative
model advisory that contradicts an otherwise clean comparison also requires review.
Missing, invalid, partial or contradictory inputs cannot PASS.

Provider failures use the shared pending_output envelope, augmented with the
registered identity, real source hashes, three uncertain checks and retained
accounting before resealing. SDK retries and automatic function calling are
disabled. A killable process bounds inference and cleanup; all calls/attempts and
available token/cache usage survive failures. Unknown cost is omitted, not guessed.
Local filesystem I/O is not preemptible; late completed judgments are discarded.

The shared SQLite ledger reserves scoped request IDs durably. Exact replay returns
the original immutable assessment without another model call. Changed request,
source availability or registration conflicts (409); reassessment requires a new
request ID. Interrupted requests require reconciliation. SQLite is single-host
replay protection, not distributed exactly-once execution.

Direct handle and HTTP use the same boundary. The manifest retains Tanishq as
owner and uses pack-manager@2, compatible with Test's registered trusted agents.

## Validation and assets

Run `python -B -m pytest agents/pack/tests -o addopts='' -q -p no:cacheprovider`.
The existing integrated assertions are retained and exercise this entry point.
SDK tests replace network transport, not Pack decisions. Exact pushed-commit
results are recorded in PR #10; methodology and limitations: docs/evaluation.md.

Submission documents, source history and sample images are preserved. Their Round 2
metrics and deployment claims are historical and unverified for Round 3. No live
model benchmark is claimed; real capture coverage and provider accuracy need validation.
