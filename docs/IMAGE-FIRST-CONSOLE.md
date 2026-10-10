# Image-first operations console

## Start and use

From the repository root, with the existing tenant tokens and manager configuration in `.env`:

```powershell
python -m uvicorn orchestration.api:app --env-file .env --host 127.0.0.1 --port 8100
```

Open http://127.0.0.1:8100 and sign in. Select or drop JPEG, PNG, or WebP images. Review each registered subject and business-stage association, choose the route and return status, then select **Validate & start**. One route/return selection applies to this batch; submit mixed-route orders separately. Open additional subject workflows through recent history. Existing evidence-only creation is retained under **Start from existing registered evidence**; lookup, review, resume and override remain available.

## Implemented path

- `PUT /uploads?unit_id=...&stage=...`: authenticated raw image body with its image Content-Type. No base64 or public media URLs. Server verifies format, 10 MB limit, 25 megapixel limit, SHA-256 and existing trusted tenant/subject/stage registration. Browser filenames are never storage paths.
- Private copies and receipts live in the existing FileStore root's `uploads` directory. Generated content-bound names are used; receipts are tenant checked and image integrity is checked again on submission.
- `POST /image-workflows`: receives `unit_id`, `route`, `returned`, and `receipts`. Resolves current trusted sources, checks flow applicability, persists receipt/input associations in workflow context and calls the existing orchestrator. Matching retries return the existing workflow without rerunning managers; changed submissions for an existing subject return 409. Resume remains explicit.
- Existing `/auth/session`, `/workflows`, `/workflows/{id}/evidence`, `/workflows/{id}/resume`, `/workflows/{id}/overrides` and `/health` remain in use.
- The orchestrator passes only each stage's own registered inputs. Configured `when` rules select stages: standard flow uses Receiving, Prep for FBA or Pack for MFN, Returns when returned, then Recovery. Existing output schema/hash/tenant validation and evidence persistence remain authoritative.
- Multiple views share one subject workflow. Different subjects produce separate workflows with explicit partial-failure reporting. Shared order photos require a trusted order subject; images are never classified into ownership automatically.
- Upload progress is per file, followed by processing state. Execution is synchronous in the current API; no fabricated percentage or repeated execution polling is used. Final evidence/results use the existing details view, including UNCERTAIN, errors and review states.

## Constraints and remaining verification

This is a registered-evidence intake, not a capture-registration service. Uploaded images must match existing trusted registrations **and available source files**. Managers continue reading independently verified source bytes; the upload is a checked, privately stored copy bound to that workflow. It does not provision missing captures, rewrite registries, invent capture times, or establish provenance from an operator assertion.

Receiving, Prep, Pack and genuine Returns image registrations are supported. Returns fixture/synthetic photos without trusted byte hashes are rejected. Recovery's current contract takes reports and upstream evidence, so direct Recovery photos are explicitly rejected; registered Recovery reports are resolved automatically.

Missing downstream configuration is recorded by existing manager/orchestrator error handling and cannot mean approval. No provider configuration, model selection, or free-tier guard was changed. No live AI inference or full browser-to-provider run was verified. No visual browser QA was performed. Existing remote HTTP manager deployments require their trusted sources/configuration to agree with the locally available registrations.

Uploads currently have no automatic retention cleanup or storage quota. A failed multi-subject batch can retain accepted private uploads and already-created subject workflows; retry uses the same receipt identities. A process crash during inference retains the existing orchestrator's recovery semantics, not an exactly-once inference guarantee.

## Changes

- `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`: image-first intake, previews/removal, metadata, validation, bounded request timeouts, batch submission, existing console features.
- `orchestration/uploads.py`: registered source adapters, image validation, private storage and receipt integrity.
- `orchestration/api.py`: authenticated upload and image-workflow routes.
- `orchestration/orchestrator.py`: stage-specific trusted upload input associations.
- `frontend/tests/app.test.cjs`, `tests/integration/test_image_uploads.py`: regression tests.

## Verification

- `npm --prefix frontend test`: 10 passed.
- `npm --prefix frontend run check`: passed.
- `npm --prefix frontend run build`: passed.
- Focused backend upload and console regression suites: 11 passed. These use controlled test doubles, not live AI.
- `git diff --check`: passed.

The initial sandbox backend run failed creating temporary directories and the next hung in Windows socketpair initialization before test execution. Running the focused tests outside that sandbox succeeded. Existing user changes were preserved; nothing was staged, committed, pushed or merged.
