# PII Detection Phase 2: Server-Side Document PII Detection

## Overview

Phase 1 added client-side PII detection for code embeds (pasted code and dropped `.js`/`.py`/etc. files).
Phase 2 extends PII detection to **binary document files** (PDF, DOCX, XLSX) that are uploaded to the server for text extraction.

Unlike code files (which are read client-side), binary documents require server-side text extraction before PII can be detected. The redaction must happen server-side before the extracted text is stored.

---

## Architecture Decision

**Where to detect:** Server-side, inside the document parsing pipeline, before writing to EmbedStore.

**Where to store mappings:** Same as Phase 1 — encrypted under `embed_pii:{embed_id}` in the client's EmbedStore using master-key encryption. The server sends redacted content + a serialized mapping back to the client.

**Flow:**

1. User uploads PDF/DOCX/XLSX → backend extracts text
2. Backend runs PII detection on extracted text, replaces with placeholders
3. Backend returns `{ redacted_text, pii_mappings }` to client
4. Client stores redacted text in TOON (`embed:{id}`), mappings in `embed_pii:{id}` (master-key encrypted)
5. LLM only ever sees redacted text

---

## Files to Create / Modify

### Backend

- **`backend/apps/docs/`** (new or existing app) — document parsing skill
  - Add PII detection step after text extraction in the document parsing pipeline
  - Reuse or adapt the pattern-based PII detection from `piiDetectionService.ts` (port to Python)
  - Return `pii_mappings` alongside the redacted content in the API response

- **`backend/shared/pii_detection.py`** (new file)
  - Port the PII regex patterns from `frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts` to Python
  - Functions: `detect_pii(text) -> List[PIIMatch]`, `redact_pii(text, matches) -> Tuple[str, List[PIIMapping]]`
  - Patterns to support: email, phone, SSN, credit card, IP address, API keys/tokens, UUID, passport/ID numbers

### Frontend

- **`frontend/packages/ui/src/components/enter_message/embedHandlers.ts`**
  - `insertDocumentFile()` — after receiving response from backend, call `storeEmbedPIIMappings()` if `pii_mappings` is present in the response

- **`frontend/packages/ui/src/components/embeds/docs/DocsEmbedPreview.svelte`** (if it exists)
  - Mirror Phase 1 pattern: load embed-level PII mappings on mount, register with `addEmbedPIIMappings()`, cleanup on unmount

- **`frontend/packages/ui/src/services/embedFullscreenHandler.ts`**
  - Update `docs-doc` resolver (already exists) to load and pass embed-level PII mappings, same as `code-code`

- **`frontend/packages/ui/src/components/settings/share/SettingsShare.svelte`**
  - Update `chatHasPII` check to also scan for `embed_pii:*` keys in EmbedStore (embed-level PII)
  - When `includeSensitiveData` is true, also restore embed-level PII in the `decryptedEmbeds` payload

---

## PII Patterns to Port (Python)

From `piiDetectionService.ts`:

| Type             | Pattern description                                |
| ---------------- | -------------------------------------------------- |
| `EMAIL`          | Standard email regex                               |
| `PHONE`          | US/international phone numbers                     |
| `SSN`            | US Social Security Number (XXX-XX-XXXX)            |
| `CREDIT_CARD`    | 13-16 digit card numbers with separators           |
| `IP_ADDRESS`     | IPv4 addresses                                     |
| `API_KEY`        | Long hex/base64 strings that look like keys/tokens |
| `UUID`           | Standard UUID format                               |
| `PASSPORT`       | Passport/national ID patterns                      |
| `CRYPTO_ADDRESS` | Bitcoin/Ethereum wallet addresses                  |

User-defined custom patterns (from `personalDataStore`) cannot be applied server-side since they are stored encrypted on the client. The server should only apply the built-in patterns; custom patterns remain client-side only.

---

## Considerations

- **Performance:** PII detection on large PDFs could be slow. Consider async processing with a `status: processing` embed that updates to `finished` when done.
- **User consent:** The `personalDataStore.settings.enabledDetectors` preference is client-side. The server cannot know which detectors the user has enabled. Options:
  1. Always apply all built-in detectors server-side (conservative default)
  2. Client sends enabled detector list with the upload request
     Option 2 is preferred for consistency with client-side behavior.
- **False positives in documents:** Documents (especially PDFs) may contain structured data that triggers false positives (e.g., product codes that look like credit cards). Consider a confidence threshold.
- **Sheet/table files (XLSX):** Cell values in spreadsheets need per-cell scanning, not whole-document scanning. The serialized table format (TSV/CSV) used in TOON means PII detection can run on the serialized string, but placeholder insertion must not break the TSV delimiters.
