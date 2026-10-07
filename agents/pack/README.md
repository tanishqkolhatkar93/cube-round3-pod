# Cube Buildathon · 03 · Pack Manager

**Commerce Context stream · Round 2 · Individual Build**

> Five agents, one unit, one record that follows it.
> A physical product arrives, gets prepped, gets shipped, comes back. At every step a person makes a fast judgment that nobody records. **You build the agent that makes one of those judgments, and leaves proof.**

**New here? Read these first:**

1. [`GITHUB-GUIDE.md`](GITHUB-GUIDE.md) explains how to fork the repository, set it up, build and push your work.
2. [`RULES.md`](RULES.md) covers the repository and engineering rules.

---

## Your problem statement: Pack Manager

|                              |                                                                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------- |
| **Position in the chain**    | Step 3 of 5. Outbound to buyer.                                                                                 |
| **Customer**                 | Seller or 3PL packing outbound orders                                                                           |
| **What gets recorded**       | Contents at seal                                                                                                |
| **Who consumes your output** | Returns Manager (what was actually sent) and Recovery Manager (buyer disputes, empty-box and wrong-item claims) |

A picker assembles an order and closes the box. If the wrong item or quantity goes in, the customer gets a mis-ship: a refund, a return, a replacement shipment and often the review. Nobody checks, because checking every box by hand costs more than the mis-ships do.

**What the agent returns, from a photograph of the open box before it is sealed:**

* Every item present, matched against the order lines
* Quantities correct per line
* Nothing extra in the box
* A verdict: seal it, or stop and fix

> **Know your customer's limits.** This only exists for merchant-fulfilled and 3PL orders. If a seller is fully FBA, Amazon packs the box and there is nothing to verify. That narrows your customer more than the other statements.

> **Be honest about competition.** Three funded companies already sell pack verification into large distribution centers. You will not out-feature them in two weeks. Your question is whether it can work for a seller with no fixed station and no hardware budget, which is a customer they do not call on.

### The chain you are part of

```text
 Supplier delivery      Inbound to Amazon     Outbound to buyer     Customer return        Money back
 ┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
 │ 01 Receiving │ ───▶ │ 02 Prep      │ ───▶ │ 03 Pack      │ ───▶ │ 04 Returns   │      │ 05 Recovery  │
 │ condition on │      │ compliance   │      │ contents at  │      │ condition &  │      │ reads all    │
 │ arrival      │      │ proof        │      │ seal         │      │ disposition  │      │ four → claim │
 └──────┬───────┘      └──────┬───────┘      └──────┬───────┘      └──────┬───────┘      └──────▲───────┘
        └─────────────────────┴─────────────────────┴─────────────────────┴─────────────────────┘
```

The first four are the same machine: a camera, a model, and a decision bound to a record. What changes is the ruleset, the buyer and the moment. The fifth has no camera. It turns the other four's records into a claim.

Your output has to be usable by another pod. That's deliberate, and it's scored.

---

## Reference data

`data/` holds a **dummy** CSV for reference while you design and build. Its columns and meanings are listed in [`data/README.md`](data/README.md).

**The data is synthetic.** The SKUs, ASINs, FNSKUs, orders, suppliers, operators and amounts are all invented. The requirement flags and fee amounts are **not** Amazon's real rules or fees. Engineering rule 5 applies: look the authoritative rule up. The `photo_refs` paths are placeholders, and no images ship with this repo. Your fixtures and eval set are yours to capture.

All five buildathon repos share the same `unit_id` values (`UNIT-0001` … `UNIT-0100`). You can follow one unit from receiving through recovery, the same way the real records will be joined. In the sample, each unit takes one route: **FBA** (prep, then Amazon ships it and charges fees) or **merchant-fulfilled / 3PL** (the seller packs it). So a unit has a Prep record or a Pack record, never both.

---

## How this works

You have a defined problem statement and a repository to build from. Real products are built backwards from the customer and forwards through the evidence. You should understand the customer and the operational workflow before you write code, then build and measure whether the solution works.

Your goal is to turn the Pack Manager problem into a working, measurable agent.

### What you're given

* This problem statement
* A domain brief covering the real economics, fee structures and what a working day in a warehouse looks like *(shared by the organisers)*
* The engineering rules in [`RULES.md`](RULES.md)
* Repository sample data and supporting resources
* Any additional build resources shared by the organisers

### What you produce

Build your solution in **your own GitHub fork**.

Your final Round 2 submission should include:

* A working Pack Manager
* An `README.md` explaining your solution, setup, assumptions and limitations
* An `ARCHITECTURE.md`
* An eval report/results with numbers and named failure modes
* A demo video
* A deployment URL, where applicable
* Your mandatory LinkedIn post URL

## Build and submission flow

```text
Understand
    ↓
Build
    ↓
Test
    ↓
Evaluate
    ↓
Document
    ↓
Demo / Deploy
    ↓
Submit
```

Round 2 is an **individual build**.

The official build phase begins on **25 September 2026 at 9:00 AM IST**.

Submissions open from **27 September 2026**.

The final submission deadline is **1 October 2026 at 6:00 PM IST**.

The submission form closes permanently at the deadline. **There is no resubmission.**

All code commits forming your Round 2 submission must be made during the authorised build phase. Do not continue making Round 2 code changes after the build phase ends.

## What we're being straight with you about

* **The core assumption is untested.** Nobody knows yet whether vision models can identify products and verify box contents reliably across long-tail catalogues without per-SKU training. Finding out that it doesn't hold, and documenting that clearly, counts as a useful outcome.
* **Nobody has spoken to a customer yet.** If you can get a real prep center or seller on a call, ask them to rank the five problems by urgency. Don't ask whether they'd buy what you're building.
* **The background documents disagree in places.** A contradiction is a finding. Raise it as an Issue labelled `finding`.

---

## Evaluation

Your Round 2 submission is evaluated out of **100 points**:

| Criterion                                    |  Points |
| -------------------------------------------- | ------: |
| Problem Understanding & Solution Relevance   |  **15** |
| Agent Functionality & Decision Quality       |  **25** |
| Evaluation, Accuracy & Uncertainty Handling  |  **25** |
| Evidence, Traceability & Engineering Quality |  **20** |
| UX, Demo & Documentation                     |  **15** |
| **TOTAL**                                    | **100** |

For the vision-based portions of the Pack Manager, use an appropriate unseen/held-out evaluation set and report your methodology, results, false positives, false negatives, `UNCERTAIN` cases and failure modes.

---

## Evidence and decision traceability

Your Pack Manager should leave evidence behind for its decisions.

At minimum, the workflow should make it possible to understand:

```text
What should be in the box?
        ↓
What was actually found?
        ↓
What checks were performed?
        ↓
What verdict was produced?
        ↓
Why?
```

Use the official evidence contract provided by the organisers as the baseline for interoperability with the other Managers.

---

## PASS · FAIL · UNCERTAIN

For individual checks:

* **PASS** — the evidence supports the condition.
* **FAIL** — the evidence shows the condition is not met.
* **UNCERTAIN** — the evidence is insufficient for a reliable judgment.

`UNCERTAIN` is not simply a low-confidence PASS.

---

*CUBE Buildathon · Commerce Context*
