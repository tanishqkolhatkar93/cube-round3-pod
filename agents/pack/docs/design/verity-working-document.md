# Working Document

**Vision verification platform — live tracker**
Last updated: 13 August 2026 · Rev 1

> **How to use this.** This is the only document that changes weekly. Everything else in the register is a snapshot of thinking at a point in time; this is the record of what is actually happening. Update it in place, add a line to the update log at the bottom, and do not create a second copy. If an action item has no owner it is not going to happen — the unassigned lines below are the honest state, not an oversight.
>
> **Owners are proposed, not agreed.** Confirm or reassign before 15 August.

---

## 1. Where we are

Nine planning artifacts exist. Zero customer conversations have happened and the core technical assumption is untested.

The build window opens 22 August and runs five weeks, returning late September. The Strategy Memo recommends converting that from a build commitment into a conditional one: two pieces of evidence gathered in the next nine days determine which product gets built inside the window.

**Critical path right now:** the accuracy test and ten customer calls. Both must complete by 21 August. Neither has started.

---

## 2. Document register

| Document | Purpose | Reader | Owner | Status |
|---|---|---|---|---|
| Business case | Why vision before manipulation; three-product thesis | Internal | Murali | v1, stable |
| BRD | What the system must do; numbered requirements | Engineering | Murali | v1, stable |
| Tech spec v2 | How it gets built; architecture, ML pipeline, API contracts | Engineering | Murali | v2, missing §1.4 data flow |
| One-Pager | Problem, solution, benefits, metrics on one page | Stakeholders | Murali | v1 |
| 6-Pager | Narrative case for the product | Stakeholders, Sid | Murali | v1 |
| PR/FAQ | Working Backwards; customer-first framing plus hard questions | Internal | Murali | v1 |
| Customer Letter | Prep-center owner's voice; hypothesis to falsify | Internal | Sid to validate | v1, **untested** |
| Strategy Memo | Investment rationale and recommendation | Vamsi, investors | Murali | v1 |
| This document | Actions, owners, decisions, progress | Everyone | **Unassigned** | Rev 1 |

Note the last row. A working document without a named owner stops being updated within two weeks.

---

## 3. Action items — pre-commitment, due before 22 August

| # | Action | Owner | Due | Status |
|---|---|---|---|---|
| A-01 | Accuracy test: scrape 500 listing images across 5 categories, build 3-image reference sets, embed, measure identification accuracy and grader agreement against 2 human graders | Murali (proposed) | 21 Aug | Not started |
| A-02 | Ten prep-center conversations. Ask them to **rank** prep, returns and pack by urgency — not whether they'd buy returns grading | Sid (proposed) | 21 Aug | Not started |
| A-03 | For each of the ten: establish the annual dollar cost of fee disputes, in absorbed charges and lost accounts | Sid (proposed) | 21 Aug | Not started |
| A-03a | Ask at least three of the ten for a quarter of Amazon fee and reimbursement report data. This replaces opinion with counts on which defect types actually get charged, and sets the check build order | Sid (proposed) | 21 Aug | Not started |
| A-04 | Test the "evidence not accuracy" hypothesis in those calls — would they pay for something they cannot show a client? | Sid (proposed) | 21 Aug | Not started |
| A-05 | Draft training-rights clause: grant by default, prospective-only tenant exclusion. Needs a lawyer | **Unassigned** | 21 Aug | Not started |
| A-06 | Decide TEC-001, imagery residency: revise DATA-003 or split compute and storage across providers | Murali (proposed) | 20 Aug | Not started |
| A-07 | Name an owner for database operations on self-managed infrastructure | **Unassigned** | 20 Aug | Not started |
| A-08 | Confirm engineering headcount and start dates for the India window | Sid (proposed) | 18 Aug | Not started |
| A-09 | Check "Verity" name availability, or replace it | **Unassigned** | 21 Aug | Not started |
| A-10 | Start SP-API developer registration — long pole with external review | Murali (proposed) | 18 Aug | Not started |
| A-11 | Architecture brief for Sid: two diagrams plus one page, so he can challenge the prep and returns logic before the build | Murali (proposed) | 20 Aug | Not started |

**Decision point, 21 August.** A-01 and A-02 together determine the lead product. If A-01 fails its threshold, the programme stops and the window is not used for this.

---

## 4. Action items — Phase 0, 22 August to 17 October

Sequenced so the irreversible work lands first. Detail is deliberately thin until the 21 August decision names the product.

| # | Action | Owner | Week | Status |
|---|---|---|---|---|
| B-01 | Terraform, Kamal, CI pipeline, Hetzner nodes | Unassigned | 1 | Blocked on A-06 |
| B-02 | PostgreSQL with pgvector, replication, **tested** PITR restore | Unassigned | 1 | Blocked on A-07 |
| B-03 | PropelAuth wiring, tenancy schema, RLS policies | Unassigned | 1 | |
| B-04 | Tenancy isolation test suite green **before any product feature** | Unassigned | 1–2 | |
| B-05 | packages/schemas, capture pipeline, browser quality gate | Unassigned | 2 | |
| B-06 | Offline queue, presigned direct upload | Unassigned | 2–3 | |
| B-07 | Rules engine, decision orchestration, LiteLLM inference service | Unassigned | 3 | |
| B-08 | Lead product rules, override vocabulary, evidence hash chain | Unassigned | 4 | Blocked on 21 Aug decision |
| B-09 | Console shell, design-partner onboarding, catalogue setup | Unassigned | 5 | |
| B-10 | ClickHouse and Cube ingestion, basic failure-rate reporting | Unassigned | 5–6 | |
| B-11 | Ten design partners onboarded | Sid (proposed) | 5–7 | |
| B-12 | 500 real units measured against error targets | Unassigned | 7–8 | |

B-04 is a hard gate. Tenancy is the one architectural decision that cannot be retrofitted once customer data exists.

---

## 5. Decisions log

### Closed

| ID | Decision | Resolution | Date |
|---|---|---|---|
| DEC-003 | Tenancy isolation | Shared schema, row-level isolation, default-deny at the data layer, covering object storage | 13 Aug |
| DEP-004 | Training rights | Granted by default; tenant opt-out prospective only; per-capture consent stamping | 13 Aug |
| — | Vision before manipulation | Vision platform first; robotic cell deferred pending corpus and field data | 13 Aug |
| — | Deployment model | BYOD first, fixed station second, single capture abstraction | 13 Aug |
| — | Scope | All three products on one platform, phased | 13 Aug |
| — | Tenancy scope | Sellers and prep centers both, multi-tenant from day one | 13 Aug |

### Open

| ID | Decision | Owner | Forcing event | Due |
|---|---|---|---|---|
| **Lead product** | Returns grading or prep verification | Murali + Sid | A-01 and A-02 evidence | 21 Aug |
| TEC-001 | Imagery residency | Murali | Phase 0 week 1 | 20 Aug |
| TEC-003 | Database operations owner | Unassigned | Phase 0 week 1 | 20 Aug |
| DEC-001 | Edge or cloud inference per product | Unassigned | First prep pilot | Phase 1 |
| DEC-002 | Model strategy | Unassigned | After accuracy test | Sept |
| DEC-004 | Evidence anchoring mechanism | Unassigned | First dispute filed | Phase 1 |
| DEC-005 | Grading rubric ownership | Unassigned | First paying customer | Phase 1 |
| DEC-006 | Metering and billing architecture | Unassigned | First metered contract | Phase 1 |
| DEC-007 | Station hardware: build, white-label or specify | Unassigned | Phase 1 station requirement | Phase 1 |
| DEC-008 | Non-Amazon channel priority | Unassigned | Phase 2 planning | Phase 2 |
| TEC-002 | Station client: PWA on fixed hardware or native | Unassigned | Phase 1 | Phase 1 |
| TEC-004 | Who provisions client-viewer logins | Unassigned | First prep-center customer | Phase 1 |
| — | Pricing: confirm metered rate against a real prep center's margin | Sid | First prep quote | Sept |
| — | Amazon Appstore listing: pursue or not | Unassigned | — | Sept |

---

## 6. Risk register

| Risk | Impact | Owner | Mitigation | Status |
|---|---|---|---|---|
| Vision models cannot grade long-tail catalogues without per-SKU training | Programme fails | Murali | A-01, two weeks, kill condition | Untested |
| Customers will not pay for consistency | Programme fails commercially | Sid | A-02 through A-04 | Untested |
| Inference cost exceeds $0.008/decision | Margin gone | Unassigned | Batch checks, resolution discipline, content cache, alert at 80% | Design in place |
| Training rights not secured before first signature | Strategic asset never accrues, unfixable | Unassigned | A-05 | Not started |
| Amazon builds prep verification first-party | Loses one of three products | Sid | Lead with returns; returns most insulated | Monitored |
| Enterprise vendors move down-market | Compressed window | Sid | Speed to seller tier, channel depth | Monitored |
| No named owner for self-managed database ops | Outage on a Friday, no recovery | Unassigned | A-07 | Not started |
| Lead product chosen without customer evidence | Five weeks builds the wrong thing | Murali + Sid | 21 Aug decision gate | Active |

---

## 7. Parking lot

Ideas raised and deliberately not acted on. Kept so they are not re-litigated from scratch.

**Evidence as the product, not the feature.** The Customer Letter suggests customers want proof rather than accuracy. If A-04 confirms it, this reframes positioning, pricing and possibly the lead product. Revisit 21 August.

**Near-duplicate detection for return fraud rings.** Embedding every capture enables cross-tenant pattern detection. Technically specced, no requirement behind it yet. Phase 2 at the earliest.

**Client-facing accuracy report the prep center can sell with.** Retention mechanic — a customer who wins business using our report does not churn. Phase 2.

**Fee reconciliation and ROI view.** Ingest channel fee reports, match charges to unit evidence, show dollars recovered. Strongest renewal mechanic identified. Phase 2, do not let it slip further.

**Robotic cell.** Full cost model exists. Revisit only on field data, with corpus and customers in place.

**Dispute precedent retrieval.** Retrieve similar past disputes and outcomes to advise on disputability. Interesting, unvalidated.

---

## 8. Update log

| Date | Rev | Change | By |
|---|---|---|---|
| 13 Aug 2026 | 1 | Created. Register, pre-commitment actions, decisions log, risks, parking lot established. | Murali |

---

*Add a row above for every material change. If two weeks pass with no new row, this document has stopped being the source of truth and someone should say so.*
