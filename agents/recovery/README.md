# Recovery Manager — trusted reports and evidence

The actual `agents.recovery.app.handle` and `/run` use the same secure boundary.
There is no sample fee CSV fallback. Set `RECOVERY_CONFIG` and
`RECOVERY_STATE_DIR` as described in the Pack registration documentation, with
`kind: document` entries pointing to JSON reports. Configuration/state/source
storage and internal service access must be protected by the deployment.

## Report input contract

Each registered JSON document has `org_id`, `subject_id`, `workflow_id`,
`complete` (boolean), `line_count` and `lines`. Every line has `line_id`,
`charge_type`, `amount_usd`, `currency: USD`, `unit_scope` and `refs`.
Amounts must be finite, nonnegative and exact cents (maximum 1,000,000 USD per
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
`width_cm`, `height_cm` values from eligible Prep evidence. Invalid/absent
measurements never reach Gemini. These units define the adapter's accepted
measurement format; no tariff thresholds are invented.

Other fees require an operator-owned `fee_policies` mapping of charge type to
`{version, text}`. Without a registered policy or eligible evidence they remain
SILENT. All unresolved eligible lines are sent in ONE batched Gemini call using
the common killable transport (at most 20 seconds, no retries). Every response
must cover exactly those lines and cite eligible records. Invalid responses or
provider/cleanup failures produce pending evidence with zero claimable amount
and retained call/model/attempt accounting. Deterministic positions cannot be
overridden by model responses. Only CONTRADICTS positions contribute dollars.

SQLite reservations provide exact replay and changed-content conflicts across
threads/process restarts. Interrupted work is not automatically reinferred.
Provider accuracy and real channel-policy validity still require deployment
validation. Unit/integration tests use explicit synthetic reports and observations.
