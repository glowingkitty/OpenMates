---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts
  - frontend/packages/ui/src/components/enter_message/MessageInput.svelte
  - frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte
  - frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts
  - frontend/packages/ui/src/components/ChatHistory.svelte
  - frontend/packages/ui/src/services/db/chatKeyManagement.ts
  - frontend/packages/ui/src/types/chat.ts
  - backend/core/directus/schemas/messages.yml
---

# PII Anonymization

> Client-side detection and replacement of personally identifiable information before messages reach the server, with encrypted mappings for client-side restoration.

## Why This Exists

Users may inadvertently paste API keys, email addresses, or credit card numbers into chat messages. The server and LLM providers should never see these values. All detection and replacement happens client-side; the server only receives encrypted placeholders and encrypted mappings it cannot read.

## How It Works

```mermaid
graph LR
    A["User types<br/>message"] -->|300ms debounce| B["PII Detection<br/>Service<br/>regex scan"]
    B --> C["TipTap decorations<br/>highlight PII"]
    B --> D["Warning banner<br/>1 email, 1 API key"]
    C --> E{User sends?}
    E -->|Yes| F["Final scan +<br/>create mappings"]
    F --> G["Replace PII with<br/>placeholders<br/>[EMAIL_com]"]
    G --> H["Encrypt message +<br/>pii_mappings with<br/>chat key"]
    H --> I["Server receives<br/>only placeholders"]

    J["Assistant responds<br/>using [EMAIL_com]"] --> K["Restore original<br/>value client-side"]
    K --> L["Render with<br/>color-coded highlight"]
```

### Detection Flow

1. **Real-time scanning** (300ms debounce): [`piiDetectionService.ts`](../../frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts) scans text using regex patterns as the user types
2. **Visual feedback**: TipTap decorations highlight detected PII in the editor. [`PIIWarningBanner.svelte`](../../frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte) shows a summary (e.g., "1 email, 1 API key")
3. **On send**: [`sendHandlers.ts`](../../frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts) runs a final scan, creates mappings, and replaces PII with placeholders before the message is created
4. **Storage**: Both the replaced content and `pii_mappings` array are encrypted with the chat key before storage

### Supported PII Types

| Type | Example | Placeholder |
|------|---------|-------------|
| EMAIL | user@example.com | `[EMAIL_com]` |
| PHONE | +1-555-123-4567 | `[PHONE_567]` |
| AWS_ACCESS_KEY | AKIAIOSFODNN7EXAMPLE | `[AWS_KEY_PLE]` |
| AWS_SECRET_KEY | (40-char with context) | `[AWS_SECRET_f9d]` |
| OPENAI_KEY | sk-proj-abc123... | `[OPENAI_KEY_f9d]` |
| ANTHROPIC_KEY | sk-ant-api03-... | `[ANTHROPIC_KEY_xyz]` |
| GITHUB_PAT | ghp_abc123... | `[GITHUB_TOKEN_123]` |
| STRIPE_KEY | sk_live_abc... | `[STRIPE_KEY_abc]` |
| GOOGLE_API_KEY | AIzaSyB... | `[GOOGLE_KEY_yB_]` |
| SLACK_TOKEN | xoxb-123... | `[SLACK_TOKEN_23_]` |
| CREDIT_CARD | 4111-1111-1111-1111 | `[CARD_111]` |
| SSN | 123-45-6789 | `[SSN_789]` |
| IPV4 | 203.0.113.50 | `[IP_.50]` |
| IPV6 | 2001:0db8:... | `[IPV6_b8:]` |
| PRIVATE_KEY | -----BEGIN PRIVATE KEY----- | `[PRIVATE_KEY_---]` |
| JWT | eyJhbG... | `[JWT_TOKEN_hbG]` |

### Restoration During Rendering

[`ChatHistory.svelte`](../../frontend/packages/ui/src/components/ChatHistory.svelte) calls `buildCumulativePIIMappings()` to aggregate all PII mappings from user messages. Both user and assistant messages are processed -- when the AI responds using a placeholder like `[EMAIL_com]`, it is restored to the original value with color-coded highlighting.

### Visual Highlighting Categories

| Category | Color | PII Types |
|----------|-------|-----------|
| Communication | Blue | EMAIL |
| Identity | Green | PHONE |
| Secrets | Red | API keys, tokens, private keys |
| Financial | Purple | CREDIT_CARD, SSN |
| Network | Gray | IPV4, IPV6 |

### Data Model

Messages include `encrypted_pii_mappings` (encrypted JSON in IndexedDB/Directus) and `pii_mappings` (decrypted on-demand, never persisted in plaintext). Each mapping contains `placeholder`, `original`, and `type`.

### Click-to-Exclude

Users can click highlighted PII in the editor to exclude it from replacement (useful for false positives like example data in code). Exclusions are session-scoped and not persisted.

## Edge Cases

- **Regex-based only**: No NLP/ML detection -- names, addresses, and context-dependent PII are not detected
- **Client-side only**: Requires JavaScript; no server-side fallback
- **Cumulative mappings**: Assistant messages use mappings aggregated from all prior user messages in the conversation, ensuring consistent restoration across follow-ups

## Related Docs

- [PII Detection Phase 2](./pii-detection-phase2.md) -- planned server-side document PII detection
- [Sensitive Data Redaction](./sensitive-data-redaction.md) -- full redaction architecture (client-side PII + server-side content sanitization)
- [Email Privacy](./email-privacy.md) -- email encryption architecture
