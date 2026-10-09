# Recovery Manager — Provenance

## Origin

This Recovery Manager is the Round 2 Recovery Manager implementation ported into the CUBE Buildathon 2026 Round 3 agent framework.

- **Original repository:** `Sri-Satya-Bhamidipati/recovery-manager`
- **Source commit used for the port:** `74e200f`
- **Original implementation:** Round 2 Recovery Manager
- **Round 3 agent:** `recovery-manager@1.0.0`

## Round 2 Implementation

The original Recovery Manager evaluated financial recovery opportunities by interpreting fee/charge reports against upstream operational evidence.

For each charge, the Recovery Manager determined whether the available evidence:

- supported the charge,
- contradicted the charge, or
- was insufficient/silent.

The original implementation also maintained an evidence trace from the charge through the available upstream evidence to the resulting recovery decision.

## Round 3 Adaptation

The Round 2 implementation was adapted to the Round 3 CUBE agent contract.

The main adaptations are:

1. The agent now exposes the standard `handle(agent_input) -> agent_output` entry point.
2. Recovery outputs are represented using the shared CUBE Agent Output and Evidence Record contracts.
3. Upstream evidence is consumed through the Round 3 `previous_evidence` contract.
4. Recovery validates evidence references before using them in a decision.
5. Tenant/organization isolation is enforced using the request subject organization.
6. Previous evidence remains read-only; Recovery produces a new Evidence Record rather than rewriting upstream records.
7. Recovery supports the Round 3 append-only override mechanism when evaluating previous evidence.
8. Recovery follows the Round 3 Recovery semantics:
   - `PASS` evidence verdict means the charge is supported and should not be claimed.
   - `FAIL` evidence verdict means the charge is contradicted and a claim may be recommended.
   - `UNCERTAIN` means the evidence is silent or insufficient and the charge must not be claimed.
9. Zero-dollar charges are handled deterministically as non-claimable.
10. Specialist-flow behavior does not fabricate Prep evidence when Prep is not part of the Specialist flow.

## Behavioral Differences from Round 2

The Round 3 implementation preserves the core Recovery decision model while adapting its behavior to the shared orchestration and evidence contract.

Notable differences include:

- Round 3 uses structured Evidence Records and Agent Outputs instead of relying on the original application's standalone output representation.
- Deterministic Round 3 policy rules are applied before invoking the language model where the contract requires deterministic handling.
- Gemini is used for evidence interpretation where deterministic policy rules do not resolve the charge.
- Gemini responses are restricted to the supported `SUPPORTS`, `CONTRADICTS`, and `SILENT` positions.
- Evidence references returned by Gemini are checked against the supplied upstream evidence. Unsupported references are not accepted as valid traceability.
- A non-silent Gemini judgment without a valid traceable evidence reference is demoted to a silent/uncertain result.
- Gemini/API failures are represented as pending/retryable failures rather than being converted into a successful Recovery decision.

## Deterministic Policy Handling

The Round 3 Recovery implementation keeps the following policy decisions deterministic:

- **Zero-dollar charges:** treated as silent/non-claimable.
- **Inbound-defect fees:** depend on available Prep evidence when Prep is part of the evaluated flow.
- **Lost-inbound charges:** supplier shortfall evidence is not treated as proof of a channel-side lost-inbound claim.
- **Weight-tier fees:** without the required upstream measurement evidence, the result remains silent/insufficient rather than being invented by the model.

## Gemini Integration

Gemini is used only for Recovery interpretations that are not resolved by the deterministic policy rules.

The model is configured through the `GEMINI_MODEL` environment variable, with the Recovery Gemini client defaulting to:

`gemini-3-flash-preview`

The resolved model name used for the API request is also recorded in the generated Evidence Record model metadata.

The Gemini prompt version is:

`recovery-v1`

The prompt requests a structured JSON response containing:

- `position`
- `confidence`
- `reason`
- `evidence_record_ids`

The implementation does not require a live Gemini API call for its automated test suite; Gemini API behavior is mocked in Recovery-specific tests.

## Current hardened integration

Owner history b2721589, c696b81d, 739d9575 and e5bf03e7 is preserved.
The original source anchor resolves to 74e200f0c8583df777103472a86b54c4a25f3433.
Test 2d65e088fb74e8057f3831b9ea3356bab1fea6e7 is merged into this branch.
The owner's CSV loader, deterministic policy, per-fee position/claim construction,
batch reconciliation and REST prompt/client are repaired in place. They are not
replaced by Test's Recovery adapter. Shared registration, upstream validation,
Prep SQLite ledger and bounded process supervisor are reused with attribution.
Test's JSON report parser remains for compatibility with integrated callers.

Earlier descriptions of override support now mean exact operator-authorized
chains only. Hashes alone do not establish origin. The actual agent identity is
recovery-manager@2, matching integrated registrations. Model versions come from
provider responses, not a copy of configured selection. Tests use synthetic data
and mocked network transport; no live-model accuracy or monetary-cost guarantee
is claimed. Exact final commit/test/CI evidence is recorded in PR #11.
