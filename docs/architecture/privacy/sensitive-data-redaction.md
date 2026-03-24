---
status: planned
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts
---

# Server-Side Sensitive Data Redaction (Planned)

> Planned server-side PII redaction using pattern matching and ML-based name detection, replacing sensitive data with realistic fake values before LLM processing.

## Why This Exists

The current PII protection ([pii-protection.md](./pii-protection.md)) is entirely client-side -- regex-based detection replaces PII with placeholders before sending to the server. This planned server-side layer would add a second defense for scenarios where client-side detection misses PII or is bypassed (e.g., programmatic API access).

## Current State

**Not implemented.** No server-side PII redaction code exists. The `backend/shared/python_utils/` directory has no PII-related modules. All current PII protection is client-side via [`piiDetectionService.ts`](../../frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts).

## Planned Approach

### Phase 1: Pattern-Based Detection

Use `data-anonymizer` library for emails, phone numbers, and credit cards:
- Speed: 5-10ms per message
- Memory: <50MB
- Faker integration for realistic replacement (better LLM processing than placeholders)
- Integration point: preprocessing stage in `preprocessor.py`

### Phase 2: ML-Based Name Detection

Add spaCy `en_core_web_sm` (13MB) for person name detection:
- Triggered conditionally (only when text looks like a letter/email)
- Confidence threshold: 0.85+
- Skip detection in code blocks, URLs, file paths
- Additional memory: ~150MB

### Key Design Decisions

- **Fake data replacement** over placeholders: Maintains text naturalness for better LLM processing while still protecting PII.
- **Context-scoped mappings**: Mappings exist only in-memory during request processing, cleared after response.
- **Conditional NER**: Name detection only runs on text that heuristically resembles personal correspondence, avoiding false positives on technical content.

## Related Docs

- [PII Protection](./pii-protection.md) -- current client-side implementation
- [PII Detection Phase 2](./pii-detection-phase2.md) -- server-side document PII detection
