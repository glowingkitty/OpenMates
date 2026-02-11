# PII Anonymization Architecture

> **Status**: Implemented  
> **Last Updated**: 2026-02-07

## Overview

OpenMates implements client-side PII (Personally Identifiable Information) detection and anonymization to protect user privacy. Sensitive data like email addresses, API keys, and credit card numbers are automatically detected while the user types, replaced with placeholders before sending to the server, and restored (with visual highlighting) when rendering messages.

**Key principle**: The server NEVER sees the original PII values. Only encrypted mappings are stored, and restoration happens entirely client-side.

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           USER TYPES MESSAGE                             │
│              "My email is user@example.com and API key sk-proj-..."      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    REAL-TIME DETECTION (300ms debounce)                  │
│  piiDetectionService.detectPII() scans text using regex patterns         │
│  TipTap decorations highlight detected PII in the editor                 │
│  PIIWarningBanner shows summary above input ("1 email, 1 API key")       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER CLICKS "SEND"                               │
│  1. detectPII() runs final scan                                          │
│  2. createPIIMappingsForStorage() creates mapping array                  │
│  3. replacePIIWithPlaceholders() transforms content                      │
│  4. Message created with pii_mappings field                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      MESSAGE STORED & SYNCED                             │
│  content: "My email is [EMAIL_1] and API key [OPENAI_KEY_1]"            │
│  pii_mappings: [                                                         │
│    { placeholder: "[EMAIL_1]", original: "user@example.com", type: "EMAIL" }  │
│    { placeholder: "[OPENAI_KEY_1]", original: "sk-proj-...", type: "OPENAI_KEY" } │
│  ]                                                                       │
│  Both fields encrypted with chat key before storage                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    SERVER PROCESSES MESSAGE                              │
│  Server only sees encrypted blobs - cannot read PII                      │
│  AI receives: "My email is [EMAIL_1] and API key [OPENAI_KEY_1]"        │
│  AI responds: "I'll contact you at [EMAIL_1]. Never share [OPENAI_KEY_1]!" │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      MESSAGE RENDERING                                   │
│  ChatHistory.buildCumulativePIIMappings() aggregates all user mappings  │
│  restorePIIInText() replaces placeholders with highlighted originals    │
│  User sees: "I'll contact you at <highlighted>user@example.com</highlighted>" │
└─────────────────────────────────────────────────────────────────────────┘
```

## Supported PII Types

| Type           | Pattern                         | Example                     | Placeholder       |
| -------------- | ------------------------------- | --------------------------- | ----------------- |
| EMAIL          | Standard email regex            | user@example.com            | [EMAIL_1]         |
| PHONE          | US/International formats        | +1-555-123-4567             | [PHONE_1]         |
| AWS_ACCESS_KEY | AKIA followed by 16 chars       | AKIAIOSFODNN7EXAMPLE        | [AWS_KEY_1]       |
| AWS_SECRET_KEY | 40-char with context keywords   | secret_key="abc..."         | [AWS_SECRET_1]    |
| OPENAI_KEY     | sk-proj-_ or sk-_ patterns      | sk-proj-abc123...           | [OPENAI_KEY_1]    |
| ANTHROPIC_KEY  | sk-ant-api03-\* pattern         | sk-ant-api03-...            | [ANTHROPIC_KEY_1] |
| GITHUB_PAT     | ghp*\*, github_pat*_, gho\__    | ghp_abc123...               | [GITHUB_TOKEN_1]  |
| STRIPE_KEY     | sk*live*_, sk*test*_            | sk_live_abc...              | [STRIPE_KEY_1]    |
| GOOGLE_API_KEY | AIza followed by 35 chars       | AIzaSyB...                  | [GOOGLE_KEY_1]    |
| SLACK_TOKEN    | xox[bpras]-\* patterns          | xoxb-123...                 | [SLACK_TOKEN_1]   |
| CREDIT_CARD    | Major card formats + Luhn check | 4111-1111-1111-1111         | [CARD_1]          |
| SSN            | US Social Security Number       | 123-45-6789                 | [SSN_1]           |
| IPV4           | Public IP addresses             | 203.0.113.50                | [IP_1]            |
| IPV6           | Full IPv6 format                | 2001:0db8:...               | [IPV6_1]          |
| PRIVATE_KEY    | PEM-encoded private keys        | -----BEGIN PRIVATE KEY----- | [PRIVATE_KEY_1]   |
| JWT            | JSON Web Tokens                 | eyJhbG...                   | [JWT_TOKEN_1]     |

## Key Components

### Frontend

| File                                                                                                              | Purpose                                                                   |
| ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| [piiDetectionService.ts](../../frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts) | Core detection logic, regex patterns, placeholder generation, restoration |
| [MessageInput.svelte](../../frontend/packages/ui/src/components/enter_message/MessageInput.svelte)                | Real-time detection integration, TipTap decorations, click-to-exclude     |
| [PIIWarningBanner.svelte](../../frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte)        | Warning banner UI with "Undo All" button                                  |
| [sendHandlers.ts](../../frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts)               | On-send replacement and mapping storage                                   |
| [ChatHistory.svelte](../../frontend/packages/ui/src/components/ChatHistory.svelte)                                | Cumulative mapping aggregation and restoration during render              |
| [chatKeyManagement.ts](../../frontend/packages/ui/src/services/db/chatKeyManagement.ts)                           | Encryption/decryption of pii_mappings field                               |
| [ReadOnlyMessage.svelte](../../frontend/packages/ui/src/components/ReadOnlyMessage.svelte)                        | CSS styles for restored PII highlighting                                  |

### Backend/Storage

| File                                                             | Purpose                                                          |
| ---------------------------------------------------------------- | ---------------------------------------------------------------- |
| [messages.yml](../../backend/core/directus/schemas/messages.yml) | Directus schema with encrypted_pii_mappings field                |
| [chat.ts](../../frontend/packages/ui/src/types/chat.ts)          | Message type with pii_mappings and encrypted_pii_mappings fields |

## Data Model

### Message Type Extension

```typescript
interface Message {
  // ... existing fields ...

  // PII anonymization fields
  encrypted_pii_mappings?: string; // Encrypted JSON stored in IndexedDB/Directus
  pii_mappings?: PIIMapping[]; // Decrypted (computed on-demand, never stored)
}

interface PIIMapping {
  placeholder: string; // e.g., "[EMAIL_1]"
  original: string; // e.g., "user@example.com"
  type: string; // e.g., "EMAIL"
}
```

## Security Considerations

### What the Server Sees

- **Content**: `"My API key is [OPENAI_KEY_1]"` (encrypted)
- **PII Mappings**: Encrypted blob (cannot read without chat key)
- **Never sees**: The actual API key value

### Encryption

- PII mappings are encrypted using the same chat key as message content
- Stored in `encrypted_pii_mappings` field
- Decrypted on-demand during message retrieval
- Follows the same zero-knowledge architecture as all other message data

### Click-to-Exclude

Users can click on highlighted PII in the editor to exclude it from replacement:

- Useful for false positives (e.g., example data in code)
- Exclusions are tracked per-session, not persisted
- After excluding, the original text remains and is sent as-is

## Visual Highlighting

Restored PII values are displayed with color-coded highlighting:

| Category      | Color  | PII Types                      |
| ------------- | ------ | ------------------------------ |
| Default       | Orange | Generic PII                    |
| Communication | Blue   | EMAIL                          |
| Identity      | Green  | PHONE                          |
| Secrets       | Red    | API keys, tokens, private keys |
| Financial     | Purple | CREDIT_CARD, SSN               |
| Network       | Gray   | IPV4, IPV6                     |

Hover tooltip shows the PII type (e.g., "Email Address (restored from placeholder)").

## Follow-up Message Handling

When the assistant responds using placeholders from a user message:

1. `ChatHistory.buildCumulativePIIMappings()` aggregates all PII mappings from user messages
2. Assistant message content is processed with the cumulative mappings
3. Placeholders like `[EMAIL_1]` are replaced with the original value from the relevant user message

This ensures consistent restoration across the entire conversation, even for follow-up messages.

## Limitations

1. **Regex-based detection**: May miss some edge cases or have false positives
2. **No NLP/ML**: Does not detect names, addresses, or other context-dependent PII
3. **Client-side only**: Requires JavaScript; no server-side fallback
4. **Session-based exclusions**: Click-to-exclude doesn't persist across page reloads

## Future Enhancements

- Server-side Presidio integration for NLP-based detection
- User preference to disable PII detection
- Persisted exclusion rules
- Custom PII pattern definitions

## Read Next

- [Security Architecture](./security.md) - Zero-knowledge encryption overview
- [Message Processing](./message_processing.md) - How messages flow through the system
- [Sync Architecture](./sync.md) - How encrypted data syncs between devices
