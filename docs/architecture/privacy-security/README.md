---
status: active
doc_type: index
audience:
- contributors
- technical-users
last_verified: 2026-06-10
claims:
- id: arch-privacy-security-readme-behavior
  type: unit
  claim: Privacy and Security Architecture is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - docs/architecture/privacy-security/README.md
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-privacy-security-readme-behavior
  verified: '2026-06-11'
- id: arch-privacy-security-readme-index-scope
  type: manual
  reason: 'Index doc: verifies navigation scope through Markdown link validation rather than source-code anchors.'
---

# Privacy and Security Architecture

## Summary

Privacy and security architecture covers encryption, prompt-injection defenses, PII protection, email privacy, and sensitive-data redaction. This index groups implemented docs that used to be split across privacy and core security folders.

## Privacy Docs

- [PII Protection](../privacy/pii-protection.md) -- client-side PII detection and anonymization.
- [Prompt Injection](../privacy/prompt-injection.md) -- defense-in-depth against prompt injection.
- [Sensitive Data Redaction](../privacy/sensitive-data-redaction.md) -- redacting PII before LLM processing.
- [Email Privacy](../privacy/email-privacy.md) -- client-side email encryption.
- [Privacy Promises](../privacy/privacy-promises.md) -- public privacy guarantees and implementation notes.

## Security Docs

- [Security](../core/security.md) -- zero-knowledge encryption and Vault key management.
- [Encryption Architecture](../core/encryption-architecture.md) -- encrypted storage architecture.
- [Chat Encryption Implementation](../core/chat-encryption-implementation.md) -- chat encryption implementation details.
- [Passkeys](../core/passkeys.md) -- WebAuthn/PRF implementation details.

## Related

- [Architecture](../README.md) -- full architecture index
- [Data and Sync](../data/sync.md) -- multi-device synchronization
