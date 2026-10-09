# Recovery provenance

Deterministic policy functions in `rules.py` are retained from Recovery PR #8,
commit 739d95756f5170782b6d433204fa59506e59cd73. That PR attributes its Round 2
source to Sri-Satya-Bhamidipati/recovery-manager at 74e200f; this integration does
not independently certify that original port attribution.

The unsafe sample-fee ingestion, per-fee inference, subject-only IDs and implicit
override trust were replaced. The new adapter validates registered JSON reports
and upstream evidence before invoking those policies. Unknown policies stay
silent; unresolved eligible lines use one batched call. The common runtime
reuses integrated Prep validation primitives and durable replay infrastructure.
The model only interprets a registered fee policy; no new channel tariff rules
were invented. The changed boundaries and accepted report/measurement formats
are documented in README.md. There is no claim of 100% model-driven behavior:
deterministic eligibility, validation, money aggregation and failure handling
are deliberately authoritative. Offline tests do not certify live model accuracy.
