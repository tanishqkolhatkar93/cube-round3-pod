# Developer Guidelines & Hard Constraints

100% Evaluation Compliance Mandates:

1. **Always Fail Open**: If an API call to Gemini fails, times out, or throws an exception, the system MUST return `PENDING`. Do not crash the UI. Do not halt the warehouse line.
2. **Tenancy Isolation**: All backend requests MUST require an `x-org-id` header. Evidence contracts must be isolated and tagged by this ID.
2. **Structured Output Only**: The AI must return structured JSON matching the Pydantic schemas. Do not use raw free-text parsing.
4. **Never Invent Evidence**: The AI must only match what is explicitly documented in the manifest and visible in the image.
5. **Uncertainty is a Feature**: If an image is blurry or occluded, the AI MUST return `UNCERTAIN . It must never issue a low-confidence `SEAL`.