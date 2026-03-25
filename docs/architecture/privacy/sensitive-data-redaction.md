---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts
  - frontend/packages/ui/src/stores/piiVisibilityStore.ts
  - frontend/packages/ui/src/stores/embedPIIStore.ts
  - frontend/packages/ui/src/stores/personalDataStore.ts
  - frontend/packages/secret-scanner/src/scanner.ts
  - backend/apps/ai/processing/content_sanitization.py
  - backend/apps/ai/processing/external_result_sanitizer.py
---

# Sensitive Data Redaction

> Client-side PII detection replaces 32 categories of sensitive data with suffix-based placeholders before sending to the server. A separate server-side layer sanitizes external content for prompt injection.

## Why This Exists

- Users paste API keys, emails, credit cards into chat — these must never reach the LLM in plaintext
- Zero-knowledge architecture: server never sees original PII values
- External API results (web search, etc.) may contain prompt injection — server-side sanitization blocks this
- Cross-device PII mappings must sync without exposing originals to the server

## How It Works

### Client-Side PII Detection (32 categories)

Real-time regex detection in [piiDetectionService.ts](../../frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts) as user types (300ms debounce):

1. `detectPII()` scans message text against 32 regex patterns with validation functions
2. `replacePIIWithPlaceholders()` creates suffix-based tokens: `[TYPE_last3chars]` (e.g., `[EMAIL_com]`, `[OPENAI_KEY_f9d]`)
3. Placeholders sent to server instead of originals — server/LLM never see real values
4. Mappings encrypted with chat key and stored in `encrypted_pii_mappings` field on each message
5. On render, `restorePIIInText()` replaces placeholders with originals using cumulative mappings from all messages in the conversation

**Categories:** Secrets (AWS, OpenAI, Anthropic, GitHub PAT, Stripe, Google, Slack, Twilio, SendGrid, Azure, HuggingFace, Databricks, Firebase, generic), Personal IDs (email, phone, SSN, passport, tax ID, license plate), Financial (credit card with Luhn validation, IBAN with ISO 7064 check), Network (IPv4 excluding private ranges, IPv6), Crypto (PEM private keys, JWT), System (home paths, user@hostname, MAC addresses), Finance (Bitcoin legacy/SegWit, Ethereum wallets)

**Validation:** Credit cards use Luhn algorithm, IBANs use ISO 7064 check digits, SSNs validate area/serial ranges, phone numbers validate digit counts. Context-aware patterns require keywords for ambiguous types (e.g., passport requires `passport:` prefix).

### Visibility Toggle

[piiVisibilityStore.ts](../../frontend/packages/ui/src/stores/piiVisibilityStore.ts) manages per-chat show/hide state:
- Default: PII hidden (placeholders shown with opacity 0.3)
- Eye icon in chat header toggles visibility
- Session-only — defaults to hidden on reload (privacy-first)
- Click individual PII in editor to exclude from replacement

### Two-Layer Embed PII

[embedPIIStore.ts](../../frontend/packages/ui/src/stores/embedPIIStore.ts) manages two mapping layers:
- **Message-level:** PII detected in user message text (cumulative across conversation)
- **Embed-level:** PII detected in code files, sheets, docs (stored per embed)
- Both layers merged for unified show/hide toggle
- Share links only provide embed key → non-owners always see placeholders

### User-Defined Personal Data

[personalDataStore.ts](../../frontend/packages/ui/src/stores/personalDataStore.ts) stores user-provided sensitive data (names, addresses, birthdays) for auto-detection:
- Client-side encrypted with master key (AES-GCM 256-bit)
- Synced via WebSocket for cross-device access
- Stored in `user_app_settings_and_memories` collection with `app_id="privacy"`
- Per-category detection toggles (email, phone, credit card, SSN, IBAN, etc.)

### CLI Secret Scanner

[secret-scanner package](../../frontend/packages/secret-scanner/src/scanner.ts) provides dual-layer detection for CLI:
- **Registry-based:** Aho-Corasick automaton for known secret values from `.env` and Settings & Memories
- **Pattern-based:** Same regex patterns as `piiDetectionService.ts`
- Roundtrip verified: `text → redact → restore` produces original text

### Server-Side Content Sanitization

[content_sanitization.py](../../backend/apps/ai/processing/content_sanitization.py) sanitizes external content (not user messages) for prompt injection:

**Layer 1 — ASCII Smuggling:** Removes invisible Unicode characters (Tags U+E0000-E007F, Variant Selectors, Zero-Width, BiDi controls) before LLM sees them

**Layer 2 — LLM-Based Detection:** Calls safety model with prompt injection detection tool. Chunks at word boundaries (max 50k tokens). Block threshold: 7.0, review threshold: 5.0. Detected injection strings replaced with `[PROMPT INJECTION DETECTED & REMOVED]`. Fails closed on any error.

[external_result_sanitizer.py](../../backend/apps/ai/processing/external_result_sanitizer.py) recursively scans skill results, prioritizing description/content/body fields over URLs/IDs.

## Edge Cases

- **AI references placeholders:** When AI responds mentioning `[EMAIL_com]`, `restorePIIInText()` restores it using cumulative mappings from all user messages in the conversation
- **Copy/export:** Respects current visibility toggle — copies either originals or placeholders
- **Cross-device sync:** PII mappings encrypted with chat key, synced via WebSocket with version conflict resolution
- **Embed sharing:** Non-owners always see placeholders (share key doesn't include message-level PII mappings)
- **Content sanitization failure:** Fails closed — returns empty string rather than allowing unsanitized content

## Related Docs

- [PII Protection](./pii-protection.md) — architecture overview of client-side PII system
- [PII Detection Phase 2](./pii-detection-phase2.md) — planned server-side document PII detection
- [Prompt Injection](./prompt-injection.md) — defense-in-depth for external content
- [Security](../core/security.md) — encryption tiers (client-managed vs vault)
