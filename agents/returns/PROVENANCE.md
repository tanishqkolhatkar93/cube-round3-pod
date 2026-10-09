# Returns engine provenance

Source: https://github.com/Karthikk-2003/cube26-rtn-0227-karthikk-2003

Pinned commit: `eb555a998d005345c167dacbdcb1dbe035c7c2ad`.
Source directory: `submissions/karthikk-2003/agent/returns_manager/`.
Destination: `agents/returns/core/returns_manager/`.

Nine modules are copied unchanged: __init__, domain, validation, observations,
vision, rules, storage, service and ollama. Original and copied file bytes were
compared locally. [core/provenance.json](core/provenance.json) records each SHA-256
with LF-normalized UTF-8 text for portable Git checkout verification.

Provider wiring additionally imports `gemini.py`, `groq.py` and
`observation_diagnostics.py` unchanged from the same pinned commit. Their hashes
are included in the same manifest. The Round 3 selector and safe diagnostic wrapper
live in `agents/returns/providers.py`; none of the twelve imported modules is edited.

The integration adds no business rule, prompt or capture lineage. It uses the
original parser, image preparation, observation validation, deterministic assessment,
tenant-scoped Store and real local Ollama provider. UI, collection ingestion,
evaluation tooling and review mutation interfaces are intentionally not imported.
The original review/automated-assessment separation remains intact.

Stored-object reconstruction in input_resolver follows the read-only validation
pattern in the original annotation_evaluation/system.py without importing that
evaluation subsystem. The new resolver adds explicit trusted bindings and hashes,
timestamp export rejection, registered-file validation and Round 3 input assertions.

The shared fork starts at starter commit
`ab72b2413354862b75ad7556fd45440d099cb320`.
The organizer Returns CSV is unchanged and has SHA-256
`0cca916d25c9db57495420e4c02cebd1ac298de9fa3f9f148fe3e9289e9b3103`.
