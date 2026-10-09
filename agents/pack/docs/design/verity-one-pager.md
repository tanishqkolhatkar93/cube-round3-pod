# Verity — One-Pager

**Returns grading from a photograph** · August 2026 · Internal
*Working name. For alignment and feedback ahead of the Phase 0 decision.*

---

## Problem statement

One in five ecommerce orders comes back. Each return costs between $10 and $65 to process, and fewer than half are resold at full price. What determines which side of that line an item lands on is a single judgment — is this the item we sold, is it complete, what condition is it in — made in a few seconds by whoever opened the box.

That judgment is inconsistent and unrecorded. Two operators grade the same scuffed item differently; the same operator grades it differently on a Friday. Items that could return to sellable stock get written down. Items that should have been written down go back on sale and generate a complaint. Substitution fraud goes undetected because nobody compares the returned item to what was ordered. And when a buyer disputes a refund or a seller questions their prep center's work, there is no evidence of what arrived or in what state.

The pain sharpened this year. Amazon stopped prepping seller inventory on 1 January 2026, moving compliance and handling liability onto roughly two million sellers and a fragmented prep-center industry, with defect fees rising steeply. Sellers are now accountable for physical handling they have no instrumentation for.

## Solution overview

Verity grades returns from photographs taken on a phone the customer already owns. There is no hardware to buy and no application to install.

An operator scans the return, takes two or three guided photographs, and receives four answers in under five seconds: item identity against the seller's own catalogue, completeness against a parts list, condition graded on Amazon's published condition scale rather than an invented one, and a recommended disposition under the customer's own rules. Every answer is retained with the photographs that produced it.

Prep centers can grade on behalf of their seller clients, with each client seeing a record of their own units and nothing else. Any grade can be overridden in one tap; supervisor-confirmed overrides become reference points against which later similar items are compared, so consistency improves with volume.

Delivery is browser-based and multi-tenant from day one. Pricing is a flat monthly subscription by order volume, not a fee per return.

## Customer benefits

**Value recovery.** Moving even a few percent of returns from liquidation to restock is direct margin, and the grading judgment is what decides it.

**Consistency.** One standard across operators, shifts and sites, anchored to precedent rather than to a prose rubric.

**Evidence.** A timestamped photographic record per unit, exportable for chargeback, A-to-z and reimbursement claims. The argument between seller and prep center becomes a lookup.

**Fraud detection.** Substituted items, missing high-value components and underweight parcels surfaced at the point of receipt rather than discovered at resale.

**Visibility.** Sellers using a prep center see what was done to their units for the first time. Prep centers get a defensible accuracy claim to sell with.

## Key metrics

| Measure | Target | When |
|---|---|---|
| SKU identification accuracy, long-tail catalogue | ≥90% | Week 2, before any product code |
| Grader agreement, model against two humans | ≥0.7 Cohen's kappa | Week 2 |
| False positive rate, per check | <2% | Week 8 |
| False negative rate, per check | <1% | Week 8 |
| Decision latency, p95 | ≤5s | Week 8 |
| Real returns measured against targets | 500 | Week 8 |
| Design partners using it unprompted | 10 | Week 8 |
| Onboarding to first graded return | <15 min | Week 8 |
| Gross margin at 4,000 orders/month | >90% | Month 6 |
| Inference cost per decision | ≤$0.008 | Ongoing, hard budget |

The first two are a kill condition, not a milestone. They are testable in two weeks with scraped listing images, one engineer and no infrastructure. If either misses, we stop rather than build.

## Decision requested

Approval to run the two-week accuracy test, and three decisions that cannot wait for its result: the training-rights clause in the customer agreement, imagery residency, and a named owner for database operations.
