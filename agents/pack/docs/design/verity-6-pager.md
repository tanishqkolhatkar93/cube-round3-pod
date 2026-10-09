# Verity — 6-Pager

**A vision service for grading ecommerce returns**
August 2026 · Internal · For review and decision
*Working name. Narrative document; appendices do not count toward the six pages.*

---

## Page 1 — Problem statement

One in five ecommerce orders comes back. Processing each return costs between ten and sixty-five dollars, and fewer than half of returned goods are ever resold at full price. Those figures describe a cost pool measured in the hundreds of billions of dollars annually, and almost all of the industry's attention has gone to the logistics of moving returns around rather than to the single decision that determines their value.

That decision is a judgment, and it takes about four seconds. Someone opens a parcel and decides whether the item inside is the item that was sold, whether it is complete, what condition it is in, and therefore whether it goes back to sellable stock or gets written down. Everything downstream — the recovery rate, the customer complaint, the reimbursement claim — follows from that four-second judgment, and it is currently made by the lowest-paid and least-informed person in the building with no reference and no record.

The consequences compound in three directions. First, inconsistency: two operators grade the same scuffed item differently, and the same operator grades it differently on a Friday afternoon than on a Tuesday morning. High-value items get under-graded and written down unnecessarily; damaged items get over-graded, go back on sale, and generate a second complaint from a second customer. Second, undetected fraud: nobody systematically compares the returned item against what was ordered, so substitution — the customer who returns a rock in a laptop box, or last year's model in this year's packaging — passes through unremarked. Third, and most expensively, no evidence: when a buyer disputes a refund, or a seller questions whether their prep center handled a unit correctly, or Amazon levies a fee weeks after the fact, there is no record of what arrived or in what state. The dispute is settled by whoever argues hardest rather than by what happened.

This became sharper in the last eight months. On the first of January 2026, Amazon stopped prepping and labelling inbound seller inventory, transferring that work and its liability to roughly two million sellers and to a fragmented, low-technology prep-center industry. Defect fees rose steeply over the same period. The effect is that sellers are now financially accountable for physical handling they have no instrumentation for whatsoever. They can see every click on their listing and every cent of their advertising spend, and they cannot see what happened to a unit in their own warehouse.

The obvious reading of this problem is that it is a labour problem, and that the answer is automation that moves things. We think that reading is wrong, and the next page explains why.

---

## Page 2 — Solution approach: why vision rather than manipulation

We considered building a robot. A robotic cell that picks, packs and labels a parcel inside a seller's own warehouse has an appealing story: sellers escape Amazon's fulfilment fees without hiring people. We modelled it in detail, and the numbers argue against starting there.

Such a cell lands at roughly twenty-four thousand dollars per unit at hundred-unit volumes, or about two and a half million dollars for a hundred units, plus somewhere between a quarter and six hundred thousand dollars of engineering that does not scale with quantity. Nearly all of that cost traces to a single design property: the machine moves. The arm itself, the twenty-five percent tariff on importing it, the safety scanner, the physical guarding, the risk assessment, the machine safety certification — every one of those line items exists because something in the cell has mass and velocity. Remove the moving parts and the same underlying technology bet costs under fifteen hundred dollars per unit, frequently nothing at all when the customer's existing phone is the camera, and carries no machine safety certification burden.

There is also an honest problem with the robot's value proposition that we should state plainly: a trained human packs a mixed order for roughly thirty-five to sixty-five cents in loaded labour. A robot cell does not beat that at any realistic throughput. Its case rests on covering nights and weekends and Q4 peaks without hiring, which is real but narrower than the pitch suggests.

What makes the vision approach possible now, and not three years ago, is that vision-language models crossed a capability threshold for exactly the workload that defeated conventional machine vision. Traditional automated inspection requires uniform items, fixtures, known geometry, and per-SKU programming. A small seller's catalogue is the opposite of that: three hundred mismatched products, no two presented the same way, changing every season. Current models identify and assess such goods from photographs with no per-SKU training, which means a new product is onboarded with three reference images and a sentence rather than an engineering project.

So the approach is to sell judgment rather than motion. We put a camera and a model at the moment the judgment is made, keep the photograph, and let the human stay in the loop as the decision-maker rather than replacing them.

There is a second, strategic reason to sequence it this way. Every unit that passes under one of these cameras produces a labelled image of a real seller's real product being handled in a real warehouse. That corpus is the single hardest asset to acquire in machine manipulation and it cannot be bought. Built this way, the cheap business funds itself and accumulates the asset that would make the expensive business feasible later. Built the other way round, we would spend two and a half million dollars to discover whether anyone wanted it.

---

## Page 3 — Solution approach: how it works

An operator scans the return label, takes two or three guided photographs, and receives an answer in under five seconds. Four things happen in that interval.

The photographs are gated for quality before anything else, in the browser, before they are ever uploaded. Blur, glare, exposure and framing are checked locally, and a frame that fails is rejected with a specific prompt rather than graded. This ordering is deliberate and it is the most important design decision in the capture path: a confident grade derived from an unusable photograph is worse than no grade at all, because it enters the evidence record and will eventually be relied upon in a dispute.

Identity is then established by retrieval rather than by classification. Reference images for each product are embedded once at onboarding; the capture is embedded and compared against them, and the closest candidates are handed to the model as a comparison problem rather than an open-ended identification problem. This is why a new product needs no model work, and it is what makes substitution fraud detectable, because the returned item's nearest match is simply a different product than the one that was ordered.

Condition is graded against Amazon's own published condition scale rather than a scale we invented, so the output is directly actionable in the customer's existing workflow. Crucially, the model grades against retrieved precedent — previously graded items from the same category, each confirmed by a supervisor — rather than against a prose rubric. A written rubric cannot stop two people interpreting "very good" differently. Comparable examples can. Completeness is checked against a per-product parts list covering accessories, manuals, tags and packaging.

Finally, a disposition is recommended under the customer's own rules, and every answer is written to an append-only record alongside the photographs, the version of the ruleset applied, and the version of the model that produced it. That record is what turns a disagreement into a lookup.

Two properties of the delivery matter as much as the grading. The first is that any answer can be overridden in one tap, and the override is recorded with a structured reason code. We designed for disagreement rather than against it, for two reasons: an operator who cannot override a wrong answer stops using the tool, and an override is the most valuable training signal available — a human looking at the same pixels the model saw, disagreeing, and saying why. Supervisor-confirmed overrides become the precedent that anchors later grades, so the system's consistency improves with volume in production, not merely in some future retrained model.

The second is that the service is multi-tenant from the outset. A prep center grades on behalf of its seller clients, and each client can see a record of their own units and nothing belonging to any other client. This is the one architectural property that cannot be retrofitted once customer data exists, which is why it is built before any product feature.

---

## Page 4 — Customer benefits

The primary benefit is value recovery, and it is arithmetic rather than aspiration. Fewer than half of returned goods are resold at full price, and the grading judgment is what allocates an item between resale and write-down. A customer who moves even a small fraction of returns from liquidation to restock captures that difference directly, and the effect is largest on exactly the high-value items where a cautious operator's instinct is to under-grade.

Consistency is the benefit customers will feel before they can measure it. One standard, applied identically across operators, shifts and sites, anchored to precedent rather than to interpretation. For a prep center this is saleable: an accuracy claim they can put in front of prospective clients and support with records. For a seller it removes a source of variance they currently cannot even observe.

Evidence is the benefit that changes the customer's relationship with everyone else in the chain. A timestamped photographic record per unit, exportable as a dispute pack, converts three arguments into lookups: the buyer disputing a refund, the seller questioning their prep center's handling, and Amazon levying a fee that may or may not be justified. It is worth noting that the third of those cuts both ways, because Amazon's charges are not always correct, and until now there has been no basis on which to contest one.

Fraud detection surfaces losses customers currently absorb without seeing them. Substituted items, missing high-value components and underweight parcels are identified at the point of receipt rather than discovered at resale, and repeat patterns across a customer's return population become visible for the first time.

Visibility is a benefit specific to the two-sided nature of this market, and it is why the same product sells to both sides. A seller who uses a prep center currently has no idea what happens to their units; they receive an invoice and a fee. Give them a record and they will pay for it. A prep center currently has no way to prove they did the work correctly; give them a record and they will pay for that too. The same evidence serves both, which means the product does not have to pick a side.

Pricing follows from the shape of the workload. Because only about one order in five becomes a return, a customer processing four thousand orders a month generates roughly eight hundred grading events, which supports a flat monthly subscription rather than a per-unit fee. We would rather customers use the service on every return than ration it, and flat pricing at above ninety percent gross margin lets us mean that.

---

## Page 5 — Key considerations

The assumption everything rests on is that vision models can identify products and assess condition across real long-tail catalogues without per-product training. If that is false, nothing else in this document matters. It is testable in about two weeks with scraped listing images, one engineer, and no infrastructure beyond a notebook, and we propose to do exactly that before writing any product code. Identification below ninety percent, or agreement with human graders below 0.7 Cohen's kappa, means we stop and reconsider rather than proceed. Making the first task a kill condition is the point; discovering the same result in month five, with a product built around it, costs an order of magnitude more and is far harder to walk away from.

The sharpest strategic tension is one of sequencing, and it deserves stating rather than burying. Our distribution strength is with small and mid-sized prep centers, and the product that points most directly at them is prep verification, not returns grading. But prep verification touches every unit rather than one in five, so its inference cost scales with throughput, it must be priced per unit, and it sits in a permanent squeeze between our model costs and a customer's willingness to pay pennies. Returns grading has materially better economics and thinner competition. Our resolution is to lead with returns while selling through prep-center relationships, since many prep centers already process returns for their clients — and to reverse the order if the first ten conversations show that prep centers will not buy returns grading. That is a decision we make on evidence within a month, not a position we defend.

Competition arrives from two directions and we should not pretend otherwise. Amazon could build prep verification itself; it sits closest to their own compliance surface, which is a further argument for leading with returns, the most insulated and least channel-dependent of our three products. Separately, the enterprise vision vendors have every incentive to move down-market: Rabot deployed with Yusen Logistics in March 2026, and iFactory, AbeTech and Packcam are all selling pack verification into distribution centers. Our defence is not technology. It is speed to a customer tier they do not currently call on, and depth of channel integration. If we are not meaningfully ahead within eighteen months, we will not win on features.

Inference cost per decision, not hardware, is the binding constraint on the business. We treat it as a hard budget of under eight tenths of a cent per decision with an alert at eighty percent, because the difference between batching all checks into one model call and issuing one call per check is the difference between ninety percent gross margin and no margin at all.

One contractual matter cannot wait. The customer agreement must grant rights to use captured imagery for model training, with a tenant-level exclusion that applies prospectively. Without the grant, the strategic asset never accrues; without the exclusion, larger prep centers will refuse to sign. And it cannot be obtained retroactively from design partners who have already signed something silent on the subject. The forcing event is the first signature, which is weeks away.

Finally, what we are deliberately not doing. We are not moving anything physically. We are not replacing anyone's warehouse system. We are not operating a liquidation marketplace. We are not building pack verification first, where three funded competitors already are. And where an authoritative answer is published — Amazon's prep requirements, for instance — we look it up rather than infer it, because in a compliance check backed by an evidence record, "we retrieved something similar" is not a defensible answer.

---

## Page 6 — Goals, plan, and decision requested

Our goal for the first phase is not revenue. It is to establish, cheaply and quickly, whether the core assumption holds and whether customers will pay for consistency. Those are different questions and both can be wrong.

Phase zero runs eight weeks. The first two are the accuracy test, alone, with no application code. Weeks three through eight build returns grading on customers' own devices, with the tenancy model and its isolation tests in place before any feature, ten design partners onboarded, and human confirmation on every decision. The gate to proceed is the accuracy assumption proven on real catalogues, five hundred real returns measured against our error targets, and design partners using the service without being chased.

Phase one runs to roughly week twenty and adds the client portal, per-client configuration, metering, and prep verification for three to five paying prep centers. The gate is customers paying on metered pricing and at least one dispute won using our evidence.

Phase two, to roughly week thirty-six, adds pack verification, a non-Amazon channel, and the return-on-investment view that reconciles channel fee reports against unit evidence — the feature that tells a customer in dollars what the subscription earned back, and the strongest renewal mechanic in the product.

Success at three months looks like a proven assumption and ten engaged design partners. At twelve months, paying prep centers on metered pricing alongside subscription returns customers. At twenty-four months, renewals driven by a demonstrable return on investment, and a corpus of handled-goods imagery that a better-funded competitor cannot buy.

The thing we are most likely to be wrong about is not the technology. It is that customers may not pay for consistency. Prep centers already advertise very high accuracy; sellers may believe their returns process is adequate. The value we are selling is real but invisible until something goes wrong, and no amount of model quality rescues a product nobody feels they need. If that is the answer, we should hear it in month one from ten conversations rather than in month nine from a sales pipeline.

We are asking for approval to run the two-week accuracy test, and for three decisions that cannot wait for its result: the training-rights language in the customer agreement, where customer imagery is hosted, and a named owner for database operations on self-managed infrastructure.

---
---

# Appendix A — Cost comparison, robotic cell versus vision service

Per unit at hundred-unit volumes, landed, including assembly and reserve.

| Configuration | Per unit | ×100 | Non-recurring engineering | Total |
|---|---|---|---|---|
| Returns grading, customer's own device | $0 | $0 | $40–70k | $40–70k |
| Returns grading, optional accuracy kit | $62 | $6,200 | $40–70k | $46–76k |
| Prep or pack verification bench | $1,270 | $127k | $60–110k | $187–237k |
| Robotic pick-pack-label cell | $23,800 | $2.38M | $250–600k | $2.6–3.0M |

The accuracy kit is a diffused light bar, a phone mount, and a neutral grey mat with printed markers. No moving parts means no machine safety certification; regulatory burden is electronic device compliance only, roughly $8–15k.

# Appendix B — Target metrics

| Measure | Target | When |
|---|---|---|
| Product identification accuracy, long-tail | ≥90% | Week 2, kill condition |
| Grader agreement, model versus two humans | ≥0.7 kappa | Week 2, kill condition |
| False positive rate, per check | <2% | Week 8 |
| False negative rate, per check | <1% | Week 8 |
| Decision latency, p95 | ≤5s | Week 8 |
| Real returns measured | 500 | Week 8 |
| Design partners using unprompted | 10 | Week 8 |
| Onboarding to first graded return | <15 min | Week 8 |
| Inference cost per decision | ≤$0.008 | Ongoing, hard budget |
| Gross margin at 4,000 orders/month | >90% | Month 6 |

Error rates are reported per check and never blended into a single figure, because the two failure modes have opposite operational consequences: a false positive stops a good unit and costs throughput, a false negative passes a defect and costs the value proposition. A blended number conceals which one is failing.

# Appendix C — Sources for figures cited

Return rates and per-return processing costs, and the share of returns resold at full price, are drawn from published industry reporting through mid-2026. Amazon's exit from inbound prep on 1 January 2026, the associated defect fee changes, and the 2026 fulfilment fee and surcharge revisions are from Amazon's published seller documentation and contemporaneous trade reporting. Robotic component pricing, tariff rates on imported industrial robots, and edge compute pricing are from vendor list prices and published tariff schedules as at August 2026. All figures should be re-verified before external use.
