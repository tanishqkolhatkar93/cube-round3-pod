# Recovery Manager — trusted reports and evidence

The actual `agents.recovery.app.handle` and `/run` use the same secure boundary.
There is no sample fee CSV fallback. Set `RECOVERY_CONFIG` and
`RECOVERY_STATE_DIR` as described in the Pack registration documentation, with
`kind: document` entries pointing to CSV or JSON reports. Configuration/state/source
storage and internal service access must be protected by the deployment.

Provider kind defaults to gemini. Explicit groq uses model qwen/qwen3.8-27b,
api_key_env selecting GROQ_API_KEY/_2/_3/_4 and deadline_s at most 20. Only
unresolved eligible fee lines with registered policies reach the model;
deterministic decisions need no key. No rotation or fallback is used. See
[deployment readiness](../../docs/DEPLOYMENT-READINESS.md).

## Report input contract

Each registered JSON document has `org_id`, `subject_id`, `workflow_id`,
`complete` (boolean), `line_count` and `lines`. Every line has `line_id`,
`charge_type`, `amount_usd`, `currency: USD`, `unit_scope` and `refs`.
Order-scoped fees require `refs.order_id`; PO-line fees require `refs.po_number`
and `refs.po_line`. Amounts must be finite, nonnegative and exact cents (maximum 1,000,000 USD per
line); there are at most 200 lines per report. The same line ID cannot appear
in two reports. A trusted, complete report explicitly asserting zero lines can
prove no fees. Missing/partial reports cannot. Scope and references must match
the registered binding. These are source/adapter constraints, not fee eligibility
policy. Reports are actual request inputs whose bytes must match registration.

Upstream records require canonical hashes, exact org/subject/workflow/client,
registered agent IDs, valid unit scope and traceable input/upstream references.
Incomplete records cannot support financial positions. Fees only use records
with matching unit scope and all declared join keys. Agent-level unhashed
overrides are rejected. Workflow overrides require exact operator registration
in `trusted_overrides`, plus a valid decision chain; a reassessment must have a
new request ID. The original evidence is never rewritten. Hashes establish
integrity, not origin authentication: calls must come from trusted orchestration.

## Policy and inference

The PR #8 deterministic rules are retained: zero-dollar fees are nonclaimable;
Prep PASS contradicts an inbound-defect fee, Prep FAIL supports it; Receiving
shortfalls do not prove channel lost-inbound claims. Scope still must match.
Weight-tier inference requires finite positive `weight_g`, `length_cm`,
`width_cm`, `height_cm` values from eligible Prep evidence. The owner's equivalent millimetre fields are also accepted; mixed unit sets must be complete and agree. Invalid/absent
measurements never reach Gemini. These units define the adapter's accepted
measurement format; no tariff thresholds are invented.

Other fees require an operator-owned `fee_policies` mapping of charge type to
`{version, text}`. Without a registered policy or eligible evidence they remain
SILENT. All unresolved eligible lines are sent in ONE batched selected-provider call using
the owner REST interpreter inside the common killable transport (at most 20 seconds, no retries). Every response
must cover exactly those lines and cite eligible records. Invalid responses or
provider/cleanup failures produce pending evidence with zero claimable amount
and retained call/model/attempt accounting. Deterministic positions cannot be
overridden by model responses. Only CONTRADICTS positions contribute dollars.

SQLite reservations provide exact replay and changed-content conflicts across
threads/process restarts. Interrupted work is not automatically reinferred.
Provider accuracy and real channel-policy validity still require deployment
validation. Unit/integration tests use explicit synthetic reports and observations.

The processing budget suppresses late completed judgments and hard-cancels the
provider worker. Trusted local filesystem I/O itself is not preemptible.

## Owner CSV compatibility

The owner CSV ingestion, deterministic rules, claim aggregation and batched
interpreter remain the production implementation in app.py/gemini_client.py.
The former Test adapter has been removed; reports.py retains its typed JSON
parser for already-integrated workflows. rules.py only re-exports owner rules.

CSV reports require line_id, unit_id, org_id, charge_type, amount_usd,
workflow_id, complete, line_count, currency and unit_scope columns. Each row
must assert complete=true and the exact total row count; the operator must
register the complete source bytes, not a caller-selected subset. Scope join
keys use order_id or po_number/po_line columns. Headers must be unique.
A header-only CSV cannot prove zero fees; use the explicit registered JSON
zero-line report contract when no fees exist. Files are limited by the shared
resolver; at most 200 fees are accepted across the complete assessment.

Model metadata records configured selection and actual returned version
separately. Available token/cache usage survives cleanup failures; unknown
monetary costs are omitted. One call is allowed, with no automatic retries.
Production never imports offline fixtures. Service authentication, policy
correctness, source completeness and persistent local storage remain operator
responsibilities. The ledger is single-host, not distributed exactly-once.
