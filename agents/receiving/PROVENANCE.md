# Receiving provenance

Round 2 source: https://github.com/zainbuilds-dev/cube-01-receiving-manager
Exact source commit: `e223d931980ad99007ddb4950a99a997e0172d5d`.

Combined integration inputs:
- Test: `911abdbd14a345dead627695825e6f6d36113ea3`.
- Zain integrate/receiving-manager: `48e63ce8007b7db0831ec1bfedabbff1b9fb9a91`.
- fix/receiving-safety: `2e16f37d3d333b9a38b42ffbc7b3ebb57ef8b2a9`.

The port retains the deterministic PIL quality gate, blind typed VLM extraction,
OpenCV QR tier, ten deterministic domain checks, and Receiving summary. UI,
legacy organization-token administration and override endpoints remain excluded.

Zain's newer integration supplies organization-scoped lookup, explicit JPEG
Part.from_bytes provider input, unified RCV-hash(request_id) identity, 23 staged
synthetic fixtures, capture discovery in the shared test helper, and the source
lineage/fixture caveats. The ID is RCV- plus the first 12 SHA256 hex characters.

The safety implementation supplies the authoritative capture registration and
path resolver, exact ownership/hash checks, full required-capture membership,
partial-failure preservation, units_per_carton export plus aggregate safeguard,
strict label comparisons, lazy provider lifecycle with bounded attempts/deadline,
sanitized diagnostic categories, first-stage upstream rejection for HTTP/inproc,
SQLite request replay, and serialized SQLite model/cache accounting.

The ledger retains a tenant/workflow/subject/request key independent of the
canonical display record ID. Crash before commit rolls back; inference may repeat
on retry after a crash. This is not distributed exactly-once execution. Request
content changes remain conflicts. There is no same-request pending-to-completed
rewrite when captures arrive later: a new request attempt is required.

Contract adaptations include canonical evidence builders/hashes, recommended
check mappings with granular detail, an additional applicable units_per_carton
check, damage vocabulary conversion, and truthful calls/model/cache accounting.
Capture timestamps use trusted specifications or an explicitly labeled unknown
placeholder required by the schema, never caller assertions masquerading as facts.

All 23 staged JPEG files retain Zain's exact bytes. They are generated fixtures,
not observations of physical deliveries. The new capture registry records their
trusted demonstration ownership and byte hashes; it does not certify their
visual correctness. UNIT-0012 and UNIT-0039 retain known PO/fixture mismatches.
Offline provider doubles do not establish real-model accuracy or fixture accuracy.

No Prep, Pack, Returns, Recovery, production orchestration, schemas or flow
changes are included. No live provider calls are used for validation. See
README.md for deployment assumptions and RECONCILIATION.md for overlap decisions.
