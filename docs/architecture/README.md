# Architecture

![Architecture header image](../images/architecture_header.png)

Technical architecture documentation for developers and contributors. For user-facing guides, see the [User Guide](../user-guide/README.md).

## Core Systems

- [Servers](servers.md) - Docker Compose infrastructure, container architecture
- [Security](security.md) - Zero-knowledge encryption, Vault key management
- [Zero-Knowledge Storage](zero-knowledge-storage.md) - Encrypted storage architecture
- [Signup & Authentication](signup-and-auth.md) - Auth flows, passkeys, 2FA
- [Passkeys](passkeys.md) - WebAuthn/PRF implementation details
- [Account Recovery](account-recovery.md) - Account reset and recovery flows
- [Account Backup](account-backup.md) - GDPR data export architecture

## Message Pipeline

- [Message Processing](message-processing.md) - Full request/response pipeline with encryption
- [Message Parsing](message-parsing.md) - Client-side TipTap JSON parsing and rendering
- [Message Input Field](message-input-field.md) - Input field architecture and embed detection
- [Message Previews Grouping](message-previews-grouping.md) - Dynamic embed grouping
- [Embeds](embeds.md) - First-class embed entity system

## AI & Models

- [AI Model Selection](ai-model-selection.md) - Provider configuration and automatic routing
- [Thinking Models](thinking-models.md) - Support for reasoning models (Gemini, Claude, o-series)
- [Hallucination Mitigation](hallucination-mitigation.md) - Reducing AI hallucinations
- [Preprocessing Model Comparison](preprocessing-model-comparison.md) - Mistral model benchmarks
- [Mates](mates.md) - Specialized AI assistant identities and routing
- [Followup Suggestions](followup-suggestions.md) - Post-processing follow-up generation

## Privacy & Security

- [PII Protection](pii-protection.md) - Client-side PII detection and anonymization
- [Prompt Injection](prompt-injection.md) - Defense-in-depth against prompt injection
- [Sensitive Data Redaction](sensitive-data-redaction.md) - Redacting PII before LLM processing
- [Email Privacy](email-privacy.md) - Client-side email encryption

## Data & Sync

- [Sync](sync.md) - 3-phase multi-device sync with zero-knowledge encryption
- [Device Sessions](device-sessions.md) - Device and session management
- [Translations](translations.md) - YAML-based i18n system

## Payments & Billing

- [Payment Processing](payment-processing.md) - Stripe integration, receipts, anti-fraud

## Infrastructure

- [Health Checks](health-checks.md) - Service monitoring and health endpoints
- [Logging](logging.md) - Backend logging with JSON formatting
- [Admin Console Log Forwarding](admin-console-log-forwarding.md) - Browser log forwarding to Loki
- [Developer Settings](developer-settings.md) - API key and device management
- [File Upload Pipeline](file-upload-pipeline.md) - 10-step secure upload pipeline
- [Vector Personalization](vector-personalization.md) - Client-side semantic search

## API & Integration

- [REST API](rest-api.md) - Programmatic access to skills and focus modes
- [Docs Web App](docs-web-app.md) - Documentation site architecture
- [Web App](web-app.md) - Unified website and chat app architecture

## Apps Architecture

For individual app documentation, see the [Apps](../apps/README.md) section. For technical details:

- [App Skills Architecture](app-skills.md) - JSON/TOON output, skill cancellation, embed storage
