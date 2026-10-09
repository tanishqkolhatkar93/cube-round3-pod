# Decisions

Every non-obvious design choice gets one entry, so a reviewer can see **what you chose, why, and what you rejected.** Newest last. This is where *Decision quality* and *Orchestration* in the [rubric](../ROUND3-RUBRIC.md) are won or lost. It is not meant to become a long report: a few lines per decision.

Write an entry whenever you: change the flow or its policies; change how the orchestrator stores state or evidence; change the final-outcome or status rules; choose a communication mechanism; decide how retries and overrides work; pick a side on a **known finding** (below); add to the contract's `payload`; or choose a deployment shape.

## Template

```text
### D-NNN · Short title
- Date / Owner:
- Context: what forced a decision?
- Options considered: A, B, C
- Decision: what we chose
- Why: the evidence or reasoning
- Consequences: what gets easier / harder; what would make us revisit
```

## Questions your Pod's decisions should answer

- Why this orchestration approach, and who owns what in it?
- Why this communication mechanism (in-process, HTTP, queue)?
- How is workflow state stored, and how does it survive a restart?
- How are retries, timeouts and resume handled?
- How is evidence persisted, and how is its immutability enforced?
- How are overrides captured, referenced, and used downstream?
- What do we do about UNCERTAIN: continue or block, and who decides?
- How does the final outcome treat weak or uncertain evidence?

## Starter decisions (made by the organisers; change them with a new entry)

### D-000 · The default flow is routed, not strictly sequential
- Context: the Round 2 sample gives each unit a Prep record *or* a Pack record, never both, and Returns only for returned units.
- Decision: `flow.json` routes FBA units through Prep, merchant-fulfilled units through Pack, and runs Returns only when a return happened. A stage that does not apply is `skipped` with the reason recorded.
- Why: forcing every unit through all five stages would invent evidence. Units with neither route (F-12) skip both.

### D-001 · The orchestrator owns state; status and outcome are derived
- Decision: workflow status and final outcome are pure functions of the stored evidence and the overrides (`orchestration/rollup.py`). Agents return evidence and a recommendation; they never write state.
- Why: "the latest agent outcome" and "Recovery's reading of it" are not the source of truth; the traceable evidence chain is.

### D-002 · UNCERTAIN continues by default; blocking is a policy
- Decision: `on_uncertain: continue` by default; `block` halts only when the UNCERTAIN result asks for a person (`needs_human`). Either way the workflow is `BLOCKED` with outcome `NEEDS_REVIEW` until an override resolves it.
- Why: a warehouse line must not wait, and the evidence of later stages is not lost. Recovery's SILENT (UNCERTAIN, `needs_human: false`) must not halt anything.

### D-003 · Failures are recorded, never hidden; never success
- Decision: a failed stage gets a degraded evidence record (no checks, UNCERTAIN, the error) and the workflow ends `FAILED` / `INCOMPLETE` (`provisional`). `resume` retries it and keeps the failed attempt's evidence.

### D-004 · Overrides are workflow entries that reference evidence
- Decision: evidence is immutable. A person's override is appended to the workflow's `overrides` with actor, reason, timestamp, the record it supersedes, the previous effective verdict and the new one. The latest wins; downstream agents receive them in `context.overrides`.

### D-005 · Zero-amount reimbursements are not claimable (F-09)
- Decision: the Recovery stub treats a 0.00 line as SILENT. Why: claiming $0 is meaningless and the meaning of 0.00 is unresolved.

### D-006 · Field names (F-15)
- Decision: `check_key`, `detail`, `content_hash`, `latency_ms`, `client_id` follow the Round 2 Returns list; `org_id`, `operator_id`, `inputs`, `model.version` follow the CSVs. Mapping in [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md). Open for the organisers.

## Known findings carried over from Round 2

Round 2 participants raised these contradictions and gaps in the shared data and documents. They are **open**: the organisers will rule on them. Until then **do not silently pick a side**: add an entry above with your assumption, and design so that changing it is cheap. `F-07` to `F-12` match the issue numbers on the Round 2 Recovery repo.

| ID | Finding | Why it matters for integration | Source |
|---|---|---|---|
| **F-07** | 42 of 61 sample fee lines are `fulfilment_fee_weight_tier`, and no upstream sample records measured weight or dimensions. | Recovery can only mark these SILENT. Prep is the natural source: see `payload.measurements`. | [Recovery #7](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/7) |
| **F-08** | `unit_id` means a **PO line** in Receiving (RCV-0003: 48 ordered, 44 received) but a **single unit** in the fee report. UNIT-0003 is lost inbound, then charged a fulfilment fee, then returned: that cannot be one physical unit. | Joins on a bare id can be wrong. The contract adds `subject.unit_scope` and `subject.refs`. | [Recovery #8](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/8) |
| **F-09** | A `lost_inbound` adjustment is posted with `amount_usd` 0.00. "Not reimbursed" (a claim to raise) or "amount missing"? | The answer flips the verdict. See D-005. | [Recovery #9](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/9) |
| **F-10** | Receiving shortfalls are supplier-side and happen before goods reach the channel, so they cannot support a channel `lost_inbound` claim. | Keep supplier shortfall and channel loss separate in your decision logic. | [Recovery #10](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/10) |
| **F-11** | Returns records exist for FBA-routed units (UNIT-0003 has a Prep record **and** a seller-side Returns record). Do FBA returns come back to the seller or to the channel's warehouse? | Decides whether Returns evidence can contradict `refund_issued_item_not_returned`. | [Recovery #11](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/11) |
| **F-12** | 9 of the 100 sample units have neither a Prep nor a Pack record, although each unit is meant to take one route. | The starter marks these `route: "unknown"` and skips both stages. Recovery's SILENT rate depends on it. | [Recovery #12](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/12) |
| **F-13** | The Round 2 rules said the organisers would provide an official evidence contract. None was published, and one participant's v0 proposal was withdrawn pending it. | **Resolved for Round 3:** [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md) v1.0. | [Receiving #4](https://github.com/Cube-Build-A-Thon/cube-01-receiving-manager/issues/4), [Recovery #13](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/13) |
| **F-14** | The Round 2 repos do not all carry the same rules: Receiving, Prep and Recovery share one short `RULES.md`; Pack's differs in wording; Returns has a much longer one (field names, evaluation method, mandatory LinkedIn post) that also ends mid-sentence. | Round 3 carries over the **union**; the organisers should confirm which is authoritative and finish the truncated section (presumably how Round 2 counts towards the final result). | [Returns `RULES.md`](https://github.com/Cube-Build-A-Thon/cube-04-returns-manager/blob/main/RULES.md) |
| **F-15** | The only organiser-authored list of "official evidence contract" fields is in the Returns repo (`organization_id`, `operator_label`, `images`, …) and is "concepts such as", not a schema. The sample CSVs use `org_id`, `operator_id`. | v1.0 uses a mix; see D-006 and the note at the top of [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md). | [Returns README](https://github.com/Cube-Build-A-Thon/cube-04-returns-manager/blob/main/README.md) |

### Raising a new finding

A contradiction between documents or data is a **finding**, not a failure. Open an issue on your Pod's repo with the `finding` label: what contradicts what, an example row, and what you assumed (and add the assumption above). Good findings are credited under *Decision quality*.

## Your Pod's decisions

_Add entries below._

### Returns input boundary and replay

Returns uses pinned Round 2 domain/validation/inference/rules behind a thin Round 3
adapter. Explicit operator configuration selects either the unchanged organizer CSV
or a tenant/client-scoped existing SQLite capture binding. Stored replay requires an
exact attempt ID; live inspection requires an explicit local Ollama provider. There
is no latest-attempt selection, source fallback, invented attestation, physical
timestamp or label-to-observation conversion.

The required physical timestamp in the evidence contract prevents export of existing
CollectionLineage captures whose timestamp is explicitly ingestion time. These are
rejected pending a separately approved upstream lineage solution. Synthetic timestamps
remain explicitly synthetic. This is a production input blocker, not a reason to
fabricate captures or modify the contract.

A separate local SQLite ledger binds tenant/request ID, complete request fingerprint,
selected source snapshot and exact output. Durable reservations prevent duplicate
inference across workers/restarts; abandoned reservations require reconciliation and
are never automatically retried. Evidence IDs include tenant/request identity. Prior
evidence and overrides are retained as separate audit interpretations, not rewritten
automated findings or trusted catalogue evidence.

Missing organizer photos now produce pending/UNCERTAIN evidence instead of historic
CSV label replay. Existing orchestrator routing/error policy is unchanged, including
its FAILED/provisional workflow classification for a pending stage. No Prep record is
fabricated. Configuration, deployment trust assumptions and limitations are documented
in [the Returns README](../agents/returns/README.md).


### Shared orchestration P0 boundaries (2026-10-07)

- The resource API now requires a server-created `orchestration.api.Principal`
  in ASGI scope under `orchestration.principal`. Trusted authentication middleware
  must authenticate the caller and set its org and actor. The application never
  promotes an org/actor header, URL or request body into an identity. Missing
  context returns 401; cross-org workflow reads/mutations return 404. Creation
  with a different org or an impersonated override actor returns 403.
- This is an authorization integration point, not a new identity provider.
  Deployment must supply authentication middleware and protect direct service
  access. Unconfigured resource access is deliberately denied. `/health` remains
  public. The local CLI and unscoped MemoryStore/FileStore backends are privileged
  operator interfaces, not APIs for untrusted callers. Resource handlers always
  use `for_org(principal.org_id, actor=principal.actor)`; scoped handles cannot
  widen their scope. The wire schemas are unchanged.
- Output validation checks declared input/check membership, supplied upstream
  record membership, workflow/org/subject scope, hashes and client compatibility.
  In-process agents receive copies so they cannot mutate the validation context.
  Agents can still declare inputs resolved through their own trusted registrations
  (needed by Returns and the starter CSV adapters). The orchestrator checks
  citation membership and supplied hash consistency; it does not authenticate a
  dishonest agent's new media assertion or independently reopen its source files.
- A completed result carrying an error, or PASS contradicting its checks, is
  rejected. A separate degraded record retains the safe reported failure codes;
  rejected output is not silently repaired or saved as valid evidence. No schema
  extension or new status vocabulary is used.
- Non-Recovery UNCERTAIN requires review even when the producer says otherwise.
  The evidence remains unchanged; effective workflow review status enforces the
  policy. Explicit human overrides remain possible. Existing Recovery SILENT
  behavior is retained. No flow, retry count or provider behavior changes.
- Overrides validate types, verdict, actor, reason and current target before
  mutation. Changed upstream decisions invalidate completed consumers through
  their declared `upstream_refs`, transitively. Old records remain in the evidence
  history; current stage pointers are cleared and stages become pending. Final
  outcomes exclude stale pointers immediately. Resume assigns a fresh request ID
  and re-runs only invalidated/incomplete stages. Replacing a failed attempt also
  invalidates completed consumers of that attempt. Undeclared dependencies cannot
  be inferred: producers must declare everything they consume.
- The existing assertion that an upstream override immediately produces CLEAN
  despite completed downstream consumers was invalid under these requirements.
  The workflow regression now requires reassessment before CLEAN and continues
  to verify preservation of the original evidence and override chain.
- Stores copy records on ingress/egress, verify evidence hashes on reads/writes,
  refuse changed content under a record ID (including unhashed agent overrides),
  constrain file identifiers, and refuse workflow ownership changes. Local file
  publication uses unique temporary files and atomic replacement under a shared
  OS file lock. Workflow mutations serialize through that lock, including agent
  execution, favoring correctness over throughput. This is a single-host/local
  filesystem design, not distributed storage; lock contention can time out.
- Store corruption fails closed. Reused evidence IDs with changed agent content
  become degraded `invalid_output`, never an overwrite. A crash between separate
  evidence and workflow writes is not a multi-file transaction; reconciliation may
  still be needed. Host filesystem owners and privileged local code remain trusted.

### D-FE-01 · Same-origin console uses tenant-scoped server sessions

- Date / Owner: 2026-10-09 / Frontend integration
- Context: the integrated workflow API requires a trusted `Principal`, but the
  repository did not provide browser sign-in middleware.
- Options considered: expose workflow routes without authentication; trust a
  browser-supplied tenant header; or validate the existing per-tenant server
  environment tokens.
- Decision: keep workflow authorization fail-closed and add same-origin sign-in
  using `ORG_ALPHA_TOKEN` / `ORG_BRAVO_TOKEN`. The server validates the token and
  issues an eight-hour random, opaque HttpOnly, SameSite=Strict session cookie.
  The original tenant token is never returned to the browser. The actor is
  explicitly the shared tenant-token operator, not a verified individual.
- Why: the console needs tenant-scoped API access without weakening the
  orchestration/storage isolation boundary or putting credentials in browser
  storage.
- Consequences: configure unique tenant secrets and use HTTPS outside localhost.
  Sessions are process-local: restarts revoke them and multi-worker deployments
  require shared session storage.
  Per-agent registrations, source files, state directories and model credentials
  remain trusted server configuration; the UI does not provision them.

### Receiving findings and decisions

- D-R1: Stage fixtures against the owning unit's specification. Zain's original
  UNIT-0012 and UNIT-0039 images remain known PO mismatches; regeneration remains
  fixture work, not a reason to suppress adverse judgments.
- D-R2: DEGRADED photos are used and recorded. REJECTED photos cannot support
  PASS. Mixed usable/rejected required captures leave the inspection pending.
- D-R3: Contract references use canonical forward slashes. The authoritative
  registered resolver rejects backslash aliases, traversal, encoded paths,
  absolute/drive/UNC paths and symlinks/junctions; no basename fallback remains.
- D-R4: Generated fixture text/watermarks can confuse label extraction. These
  synthetic images must not be presented as physical receiving evidence.
- D-R5: Observation caching is content/model/prompt based and uses serialized
  SQLite publication. Cache hits retain model identity and count zero SDK calls;
  explicit retries/fallback calls are counted even when they fail.
- D-R6: Preserve Zain's RCV- plus 12 SHA256 hex characters of request_id on all
  paths. Scope the separate request ledger by tenant/workflow/subject/request.
  Globally scoped request IDs remain necessary for the shared immutable store.
- D-R7: An existing request cannot change because a missing capture arrived.
  Changed request/spec/capture content conflicts; reconcile with a new attempt ID.
- D-R8: All applicable checks affect the final verdict, including units_per_carton.
  Extraction errors cannot silently discard required evidence or produce PASS.


### D-POD-2026-10-09 � registered Pack and Recovery integration

- Preserve Test 911abdb and its Returns/orchestration hardening. Receiving e5dcbe4
  reconciles the two Receiving implementations and latest adversarial fixes;
  Prep 32d017c is merged, with explicit test fixture composition.
- Replace the actual Pack/Recovery stub entry points, not disconnected prototypes.
  Operator-owned registrations bind org, subject, workflow, input bytes and capture
  time. Requests assert the complete registered input set; no sample-data fallback.
- Reuse Prep's strict primitives, protected-file reader and RequestStore in the new
  agents/secure_runtime.py. This creates an explicit dependency on integrated Prep;
  no existing Prep, Returns, orchestration or shared-contract behavior is changed.
- Pack model responses contain facts only. Deterministic item/count/extra checks
  control SEAL. Incomplete/invalid/contradictory input cannot be a completed PASS.
- Recovery retains PR #8 deterministic rules. Financial claims require exact scope
  and references, complete registered fee reports and eligible evidence. Unknown
  policies stay silent. Explicitly complete zero-line reports can prove no fees.
  A request cannot authorize its own workflow override; registration and chain
  validation are required. Reassessment needs a new request ID.
- One batched provider call per unit is isolated in a killable worker. There are no
  retries. The deadline includes preprocessing budget; late judgments are discarded.
  Parent-owned attempted-call/model accounting survives timeout and cleanup failure.
- Protected internal invocation is a deployment requirement, consistent with the
  other modules. Content hashes and agent-ID allowlists are not digital signatures.
  Offline tests certify contracts and safety logic, not live model accuracy.
