# Pack provenance

Author: Tanishq Kolhatkar. Verified source repository:
https://github.com/tanishqkolhatkar93/cube-round3-pod

- `b61c5b0ab1334d6bda5058e83afb0d5d0d093ae3` moved Tanishq's Round 2 work into `agents/pack`.
- `29ecec649933fa9a9426a030fc727415237cd97b` added the Round 3 handler and Gemini SDK bridge.
- This repair preserves that branch history, handler/check construction, SDK
  `Part.from_bytes` path, and typed AIAnalysisResult/CheckResults models. The
  models now require actual per-image facts. Permission is computed from facts,
  not the model's advisory booleans or verdict.
- Test `c5fcdca94fa2f84c1e79781fcbbd956ef49a4e08` is merged INTO Pack-Manager
  solely as its integration baseline. Its registration/upstream validator,
  Prep-backed SQLite ledger and process supervisor are reused with attribution.
  The separate Test Pack adapter is not this branch's runtime. Test itself has
  not been modified by this repair.

No separate original Round 2 repository/commit was independently verified.
The two source commits above are the verified provenance anchors; no stronger
original-source claim is made.

## Preserved history and cleanup

Concurrent author commit `03451c156bfea58b11095aab025265cd1e8f875f`
added demo fixes and removed unused Round 2 assets. Its history and cleanup are
preserved. Original submission documents, photographs, UI and design work remain
retrievable at the verified source commits above, not as competing runtime code.
Historical claims in those assets are not certified Round 3 results.
See `docs/evaluation.md`.

Removed duplicate `submissions/.../agent` code, unused SQLAlchemy DAO, two runtime
DBs, seven generated runtime contracts, empty scripts and nested Round 2 GitHub
configuration. These remain retrievable at the source commit. The legacy /verify
endpoint was removed rather than leaving an alternate untrusted decision path.
The authoritative Round 3 endpoints are /run and /health from agents.pack.app.

The new commit's uncertainty, request-capture and pending-output goals are
subsumed by the stricter registered-input, shared pending-envelope and deterministic
checks in this repair. Its unpinned SDK dependency is satisfied through the single
root dependency policy. Its placeholder source hash and unsupported 95%/cost/latency
claims were not accepted as provenance or measurements.

Synthetic/offline tests do not establish live model accuracy, production data
ownership, image coverage or historical evaluation claims.
