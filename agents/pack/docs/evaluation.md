# Round 3 Pack validation — method and measured scope

This is a deterministic integration/security evaluation, not a vision-accuracy
benchmark. No real Gemini call or customer capture was used. The original Round 2
50-unit / 94% / kappa claims are historical, unverified here and not reused.

## Candidate and reproducibility

The exact final pushed SHA, exit codes, full counts and CI URL are recorded in
PR #10 to avoid a self-referential source commit. Tests run after the commit and
before pushing; a later source change invalidates that final result.

Clean Python 3.13 environment: created a fresh venv without system site packages;
installed ONLY `python -m pip install -r requirements.txt`. Pack imports with
`site.ENABLE_USER_SITE=False`; `pip check` passes. SDK version tested: 2.29.0.

Commands (from repository root):

```
python -B -m pytest agents/pack/tests -o addopts='' -q -p no:cacheprovider --tb=short
python -B -m pytest tests/integration tests/e2e -o addopts='' -q -p no:cacheprovider --tb=short
python -B -m pytest -o addopts='' -q -p no:cacheprovider --tb=short
```

All inherited Pack assertions are preserved. The only test-import adaptation
selects Tanishq's actual app instead of Test's separate adapter. The late-result
test adds a cache-usage assertion. No skips/xfails were added to hide failures.

## Measured observations before final commit

- Initial inherited suite: 18 failures, 29 passes. These exposed invalid
  uncertain_reason enum values in pending records. Mapping to the authoritative
  schema fixed them; rerun: 47 passed.
- New SDK/decision/security regressions: initial 26 passes and one deadline-test
  failure, because SDK imports exhausted a three-second test process budget before
  its first event. The test now uses a lightweight spawned target to isolate a
  cleanup hang from import time, retaining the same deadline and accounting
  assertions. Rerun: 27 passed.
- A further 16-case declared-truth grid exercises quantities 0/1/2/3, extra SKU
  absent/present, and visibility complete/incomplete against expected SKU-A x2.
  It asserts each of the three check verdicts and the aggregate result. Expected
  outcomes: one PASS, seven FAIL, eight UNCERTAIN. Final measured results are in
  the exact-commit PR validation, not assumed here before execution.

The grid uses synthetic observations injected after image/ownership validation.
It measures decision logic, not recognition. SDK tests independently exercise the
real Part.from_bytes path, strict response models and cleanup, replacing only the
network client. They verify successful and failed call counts, attribution, token
and cached-token accounting, malformed/truncated/blocked responses, initialization
failure, timeout and cleanup failure. Provider costs remain absent because no
verified pricing/accounting source is configured.

## Remaining limits

A live labeled image dataset, independently established labels and real-provider
runs are required before reporting per-check visual false-positive/negative rates,
latency or accuracy. Production capture completeness must be established physically;
model assertions alone are not proof. All routes require protected registrations,
state storage and authenticated internal callers. Canonical hashes are integrity
checks, not origin authentication. SQLite is single-host durable replay. Local
filesystem I/O is not preemptible; the provider process is hard-cancelled and late
completed results are discarded with their recorded accounting retained.
