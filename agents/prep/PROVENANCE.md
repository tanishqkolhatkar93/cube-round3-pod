# Prep source lineage and adaptations

Organizer-provided repository: https://github.com/Manvith111/cube26-prp-0319-manvith111

Exact reviewed source: `f5f8ad98fa8085a092c796b0681689d52ffc871e`.
Pod integration baseline: `911abdbd14a345dead627695825e6f6d36113ea3`.
Adaptation identity: `pod14-prep-manager@1`; rule pack `organizer-fba@1-pod14.1`.
Exact upstream file-byte hashes are recorded in `core/provenance.json`.

## Organizer source logic retained

- `src/lib/prepRequirements.ts`: polybag presence/seal; suffocation-warning
  presence/legibility; FNSKU presence/placement/text; original barcode coverage;
  expiry visibility; named handling requirements; nonvisual bag material.
- `src/lib/rulePacks/fba-v1.ts`, `index.ts`, `types.ts`: named/versioned rule
  identity, explicit applicability, clause references, unknown-pack rejection.
- `src/lib/rules.ts`: application-owned verdict calculation; missing facts,
  low confidence and poor quality mean uncertainty; applicable failure takes
  precedence, then uncertainty, then pass. No checks means uncertainty.
- `src/lib/vision.ts` and `types.ts`: a distinct observation stage, indexed
  photo quality, literal label transcription, and evidence-linked findings.

This is an attributed Python port of the focused domain concepts, not a claim
that the Next.js application was integrated byte-for-byte.

## Exact corrections

1. Replaced model `met/not_met` compliance claims with typed factual fields.
   The provider cannot emit a business verdict. Unknown fields/values, duplicate
   JSON keys, invalid confidence and invalid or duplicate citations are rejected.
2. Required citation membership in the registered capture set. Photo indices
   must be real positive integers; booleans, fractions, null and out-of-range
   values fail. Every cited photo needs explicit usable quality to support PASS.
   The label-transcription branch obeys the same quality/confidence rules.
3. Replaced last-value-wins with rejection of duplicate field/photo observations
   and uncertainty for disagreement between distinct authorized photos.
4. Replaced permissive FNSKU punctuation removal with surrounding-whitespace
   trimming and uppercase conversion only. Partial tokens cannot establish
   identity; full wrong identifiers fail; ambiguous formatting needs review.
5. Each required handling mark has a separate observation and canonical check.
   It is named explicitly in the prompt. No generic handling-marks PASS hides a
   missing named marking.
6. Nonapplicable requirements are separately retained as NOT_APPLICABLE payload
   annotations. They are not fabricated passing checks. Applicable material is
   UNCERTAIN/NOT_VERIFIABLE without an authorized physical attestation. The
   retained source threshold is 1.5 mil plus durable material.
7. Suffocation-warning applicability is an explicit trusted criteria field.
   The source's 5-inch threshold is not visually inferred from a photograph.
8. Replaced caller-controlled criteria with strict, hashed, versioned documents
   selected by trusted registration. Unknown applicability never becomes false.
9. Replaced silent six-photo slicing with rejection above six images. All
   registered images are verified; missing/invalid images prevent inference.
10. Replaced public uploads/record paths with scoped registration; reference
    assertions, safe relative paths, link rejection, size/format checks, byte
    hashing, and read-time file identity checks precede provider construction.
11. Replaced random IDs and mutable JSON storage with scoped PRP IDs and a
    transactional SQLite reservation/exact-output ledger. Conflicts and
    interrupted executions cannot silently re-infer or overwrite prior output.
12. Replaced framework-specific records with the existing Round 3 builders,
    validators and hashing. A known physical capture time is mandatory; no
    created/produced time is relabeled as captured time.
13. Replaced provider pooling/fallback with one opt-in Gemini attempt and a
    bounded worker. Error messages are fixed categories, not raw exceptions.
    Requested model, returned model version (or unknown), prompt version/hash,
    and response hash are retained. No claim of a resolved version is invented.

## Independently verified requirements versus unverified policy

Verified against Test: request/output schemas, evidence field vocabulary, hash
algorithm, stage/subject/workflow consistency, upstream citation membership,
non-Recovery uncertainty review, immutable record handling, and inproc/HTTP
entry points. These are integration requirements, not marketplace policy.

No authoritative challenge policy document was available during this port.
The upstream quotes expressly model marketplace rules. We retain source clause
IDs as organizer implementation lineage; we do not present them as verified
Amazon quotations. Operator criteria and physical attestations are trusted
registrations, not independently established facts or marketplace approval.
Every output labels this distinction in `payload.policy_authority`.

## Excluded components and unchanged ownership

No Next.js UI, settings/credential administration, Cloudflare storage, fuzzy
Find matching, untrusted catalog writes, public photo/record APIs, or supplied
Recovery code was ported. No Receiving, Pack, Returns, Recovery, shared schema,
production orchestration, pod configuration, or flow file was changed.

The registration and ledger approach follows the existing Returns architecture
as a pattern. Prep owns its implementation and does not import Returns internals.

## Limitations

- Registration files, criteria, physical attestations and host filesystem
  administration are trusted. A digest proves content equality, not authority.
- `/run` is an internal service, not an identity provider. Deployment must
  authenticate at the orchestrator and prevent untrusted direct access. One
  configured adapter serves one org/client scope; use separate instances or a
  trusted router for multiple orgs. An org header/body never authenticates a user.
- Link checks and file identity checks do not defend against a privileged host
  attacker racing arbitrary filesystem operations; protect source directories.
- Vision reliability and official policy compliance need separate evaluation.
  Offline tests prove rules/boundaries, not Gemini accuracy on warehouse photos.
- The ledger is single-host SQLite, not distributed exactly-once execution. A
  remote provider may receive a request before timeout/crash; the same request
  is never automatically sent again. Reconcile before a new request ID.
- The source defines no measured weight/dimensions; `measurements` remains null.
  Recovery must not infer a weight-tier claim from Prep photographs.
- Flow activation and any existing downstream replay/ID issues are separate
  coordinated work. Prep does not relax orchestration protections to hide them.
