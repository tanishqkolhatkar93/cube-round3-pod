# Pack Manager — design review

**Reply to the pod's questions on UNCERTAIN handling and fail-open**

Both of your calls are right. Sharpening each below, then three things your approach has not accounted for yet.

---

## 1. Box-level UNCERTAIN

**Keep it. Three outcomes in the record, two in the interface.**

The operator sees STOP either way, because at the moment of action the distinction is meaningless to them. The record keeps which one it was, because the distinction is the whole signal.

Collapse them and your false-STOP rate merges two different things: correctly catching a problem, and being unable to see. Those have opposite implications.

- High false-STOP with low uncertain → your checks are miscalibrated
- High uncertain → your capture is inadequate

Different fixes. One number cannot tell you which.

**Add uncertain rate as a first-class metric with a target,** not just a number you report at the end. Every uncertain is a human interruption, so a product with perfect accuracy and a 20% uncertain rate fails commercially even though it is technically correct.

That threshold is a legitimate kill condition for your one-pager. Decide now what uncertain rate makes the product unusable, and write it down before you know your result.

---

## 2. Fail-open versus the seal gate

**Your resolution matches the intent.** It is the clearest statement of this any pod has given.

One correction to the framing. Fail-open does not mean the box auto-seals. It means the failure state is the **status quo ante**: the operator sealing on their own judgment, exactly as they do today with no agent at all. The agent's absence must never leave the operator worse off than if the agent had never existed. That is the whole rule.

**Be honest about what the async re-run buys you.** If the box has already shipped, a flagged disagreement twenty minutes later does not catch that mis-ship. Its value is eval signal, plus a real catch in operations where dispatch is slower than your re-run. Say which in your PR/FAQ rather than implying the async path is a safety net it is not.

**Measure your pending rate.** Above a few percent, operators learn the system is unreliable and start ignoring it even when it works. That is how good products die on a warehouse floor, and it will not show up in any accuracy metric.

---

## 3. Occlusion is your real failure mode

Items in a packed box overlap. A single photograph of an open box physically cannot see an item underneath another item. Closed-set verification with bounding boxes assumes visibility, and we expect your false-SEAL rate to be dominated by occlusion rather than by recognition.

Two responses. Pick one and state it in your one-pager:

- **Capture as packed.** One shot per layer, as items go in. Catches everything, costs throughput, and throughput is the thing operators are measured on.
- **Accept single-shot** and report occlusion-caused failures as a separate category from recognition failures.

Either is defensible. Not distinguishing them is not, because you will otherwise spend a week improving recognition on a problem that is geometric.

---

## 4. Decoys in eval but not in production

You tell the model the order's SKUs plus look-alike decoys. Good anti-anchoring design for eval. The question is whether the candidate set still includes decoys in production.

**If not,** your eval measures a harder task than the one you ship, and your production numbers will drift upward for reasons unrelated to quality.

**If yes,** that is a real design choice worth stating explicitly: always include the seller's other SKUs as candidates, so the model must discriminate rather than confirm. This is the better answer and it costs you nothing.

---

## 5. Split identity errors from count errors

Recognising that a SKU is present is much easier than counting three of them under partial occlusion. A blended per-check number hides which one is broken, and count is almost certainly where you are losing.

Your metric table wants `all_items_present` and `quantities_correct` as separate rows. Expect a large gap between them, and report it.

---

## 6. One note on bounding boxes

Boxes are for the evidence record, not the decision. If your rules layer only needs presence and count, say so explicitly in your build brief, so nobody later assumes localisation accuracy is load-bearing when it is there for explainability.

---

## What we would like back

- Your uncertain-rate target, before you know your result
- Which occlusion response you picked, and why
- Whether decoys survive into production
- `all_items_present` and `quantities_correct` as separate metric rows

The approach you described is ahead of where most pods are. These are refinements, not corrections.
