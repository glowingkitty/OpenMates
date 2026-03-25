---
status: planned
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts
---

# PII Detection Phase 2: Server-Side Document PII Detection

> Planned extension of PII detection to binary document uploads (PDF, DOCX, XLSX) via server-side text extraction and redaction.

## Why This Exists

Phase 1 ([pii-protection.md](./pii-protection.md)) handles client-side PII detection for text messages and code embeds. Binary documents require server-side text extraction before PII can be detected -- the client cannot read PDF/DOCX content directly. Redaction must happen server-side before extracted text is stored or sent to LLMs.

## Current State

**Not implemented.** No server-side PII detection code exists. This document captures the planned architecture.

## Planned Architecture

### Flow

1. User uploads PDF/DOCX/XLSX to the backend
2. Backend extracts text from the document
3. Backend runs PII detection on extracted text, replaces with placeholders
4. Backend returns `{ redacted_text, pii_mappings }` to the client
5. Client stores redacted text in the embed, mappings encrypted under `embed_pii:{embed_id}` with master-key encryption
6. LLM only sees redacted text

### Detection Patterns to Port (Python)

The regex patterns from [`piiDetectionService.ts`](../../frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts) need to be ported to Python:

| Type | Description |
|------|-------------|
| EMAIL | Standard email regex |
| PHONE | US/international formats |
| SSN | US Social Security Number |
| CREDIT_CARD | 13-16 digit card numbers |
| IP_ADDRESS | IPv4 addresses |
| API_KEY | Long hex/base64 strings |
| UUID | Standard UUID format |
| PASSPORT | Passport/national ID patterns |
| CRYPTO_ADDRESS | Bitcoin/Ethereum addresses |

### Backend Changes

- New shared module `backend/shared/pii_detection.py` with `detect_pii()` and `redact_pii()` functions
- Integration into the document parsing pipeline (after text extraction, before storage)

### Frontend Changes

- Embed handlers store PII mappings on mount, register with `addEmbedPIIMappings()`, cleanup on unmount
- Settings share page updated to check for embed-level PII keys
- Fullscreen embed handler loads and passes embed-level PII mappings

### Key Considerations

- **User-defined custom patterns** cannot be applied server-side (stored encrypted on client). Server applies built-in patterns only.
- **Performance**: Large PDFs may need async processing with a `status: processing` embed state.
- **Consent**: Client should send enabled detector list with the upload request for consistency with client-side preferences.
- **Spreadsheets**: Per-cell scanning needed; placeholder insertion must not break TSV/CSV delimiters.

## Related Docs

- [PII Protection](./pii-protection.md) -- current client-side Phase 1 implementation
- [Sensitive Data Redaction](./sensitive-data-redaction.md) -- planned server-side redaction for chat messages
