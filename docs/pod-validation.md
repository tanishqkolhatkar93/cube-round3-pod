# Pod integration validation method

The integration PR body records the exact final head SHA, commands, exit codes,
counts and CI URL. A test result from a different commit is not final validation.

## Preserved sources

- Test baseline: 911abdbd14a345dead627695825e6f6d36113ea3 (Returns and orchestration retained).
- Receiving: e5dcbe4d15d00ea0f53db4ccd14fb10b98d54768, preserving the combined worktree and both adversarial fixes.
- Prep: 32d017ca96e039996d8944d03dc6b404ab07a92a; merged into a8792c0.
- Recovery deterministic policy: PR #8, 739d95756f5170782b6d433204fa59506e59cd73.
- Pack PR #7 b61c5b0 was reviewed but its disconnected prototype is not deployed.

## Completed intermediate validation (not the final candidate)

- Receiving preservation: `python -B -m pytest agents/receiving/tests tests -o addopts='' -q -p no:cacheprovider`:
  exit 0; 425 passed, 1 existing skip.
- Candidate c6112d99402ccf1c827b08322daf8d73d3a69d05:
  - all four agent-owned directories: exit 0; 334 passed.
  - full default repository suite: exit 0; 551 passed, 1 existing skip.
  - 118 tracked Python files compiled in memory and 8 production imports passed.
  - existing assertions in seven adapted test files were retained by AST comparison.
  - Linux GitHub Actions test job passed.
- Further adversarial malformed-model tests initially failed (2 failures): overflow
  JSON and a nonfinite invalid observation prevented truthful pending publication.
  d8fb2f10223a2713426900048f75106f6163ffbb fixes both; focused Pack/Recovery: 93 passed.
- Explicit order/PO join-key validation was then added; focused Pack/Recovery:
  exit 0; 96 passed before its commit. Final suites must rerun after that commit.

## Final commands

Use the existing temporary Receiving validation venv (Python 3.13 on Windows),
with no live model keys/calls. No dependency installation was needed for this run.

```
python -B -m pytest agents/receiving/tests agents/prep/tests agents/pack/tests agents/recovery/tests -o addopts='' -q -p no:cacheprovider --tb=short
python -B -m pytest -o addopts='' -q -p no:cacheprovider --tb=short
git diff --check Test HEAD
```

Compile tracked Python sources with `compile(bytes, filename, 'exec')`, not by
writing pyc files. Import all five real entry points, common runtime/provider and
orchestrator. Verify the candidate contains no production changes to orchestration,
shared contracts or Returns. Inspect the actual PR file inventory and CI head.

Focused/default counts overlap: CI imports agent-owned suites through integration
shims. They are not additive claims of unique scenarios. The sole expected skip is
the original organizer-stub golden dataset, now inapplicable to real agents. All
real integration assertions remain, using explicit trusted synthetic registrations.
Two Windows uvicorn/websockets deprecation warnings are not hidden.

## Deployment limits

All five entry points are real implementations, but deployment still requires
protected registrations/state, authenticated internal routing and actual capture
sources. Offline provider doubles prove logic and contracts, not image-recognition
accuracy. Recovery requires authoritative registered fee policies for unknown fee
types; it stays SILENT otherwise. Local filesystem I/O is not hard-preemptible,
though late judgments are discarded and provider workers are hard-cancelled.
Returns' pre-existing production collection export still requires physical capture
time lineage. No capture timestamp or source completeness is invented to bypass it.

SQLite is single-host durable replay, not distributed exactly-once inference.
Interrupted reservations require reconciliation and a new request ID. Do not merge
older competing agent PRs blindly over this candidate.
