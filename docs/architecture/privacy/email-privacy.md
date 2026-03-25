---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/services/cryptoService.ts
  - backend/core/api/app/utils/encryption.py
  - backend/core/api/app/routes/auth_routes/auth_login.py
  - backend/core/api/app/routes/auth_routes/auth_2fa_setup.py
---

# Email Privacy Protection

> Client-side email encryption with ephemeral server-side key access, ensuring email addresses are never stored in plaintext on the server.

## Why This Exists

User email addresses are sensitive PII. OpenMates encrypts them client-side so the server stores only encrypted blobs. The server can temporarily decrypt emails (in-memory) during active operations like login notifications or payment receipts, then immediately discards the key.

## How It Works

### Storage Schema

| Field | Encryption | Purpose |
|-------|-----------|---------|
| `encrypted_email_address` | Client-side with `email_encryption_key` | Primary storage |
| `user_email_salt` | Plaintext (unique per user) | Key derivation input |
| `encrypted_email_with_master_key` | Client-side with master key | Passwordless passkey login |
| `encrypted_email_auto_topup` | Server-side with Vault | Automated billing receipts |
| `hashed_email` | SHA256(email) | Uniqueness checks and user lookup only |

### Key Derivation

The `email_encryption_key` is derived client-side in [`cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts):

```
email_encryption_key = SHA256(email + user_email_salt)
```

The server never stores or derives this key. It only receives it temporarily during active operations.

### Login Flows

**Password login:**
1. Client derives `email_encryption_key` from email + salt
2. Client sends key temporarily to server during login
3. Server decrypts email in-memory, sends login notification
4. Server discards key immediately

**Passkey login:**
1. User authenticates with passkey (no email entry)
2. Server returns `encrypted_email_with_master_key` to client
3. Client decrypts email, derives `email_encryption_key`, sends to server
4. Server temporarily decrypts for notification, discards key

### Payment Processing

- **Auto top-up receipts**: Uses `encrypted_email_auto_topup` (HashiCorp Vault transit encryption, server can decrypt without user interaction)
- **Manual payment receipts**: Client provides `email_encryption_key` during payment flow
- **Mailjet integration**: Server decrypts recipient email only at send time. Uses Send API only -- never uploads contact lists.

### Invoice Privacy

Invoices use a 7-character randomly generated **Account ID** (e.g., "K7M9P2S") instead of email addresses. This satisfies German business record requirements while keeping personal emails out of accounting systems.

## Edge Cases

- **Server compromise**: Attacker gets encrypted email blobs and per-user salts, but cannot derive decryption keys without the original email addresses.
- **Vault-encrypted emails**: The `encrypted_email_auto_topup` field is an exception -- the server can decrypt it for automated billing. This is isolated from user-controlled encryption.
- **Mailjet delivery logs**: Standard email provider behavior; Mailjet may retain delivery logs per their policies.

## Related Docs

- [Zero-Knowledge Storage](../core/zero-knowledge-storage.md) -- overall encryption architecture
- [Signup and Auth](../core/signup-and-auth.md) -- authentication flows
