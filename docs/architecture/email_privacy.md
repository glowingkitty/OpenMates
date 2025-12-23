# Email Privacy Protection

OpenMates implements comprehensive email privacy through client-side encryption, ensuring user email addresses remain private even from our own servers and third-party services.

## Email Encryption Architecture

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts) (client-side) and [`backend/core/api/app/utils/encryption.py`](../../backend/core/api/app/utils/encryption.py) (server-side helpers)

### Storage Schema

User emails are stored in multiple encrypted formats for different purposes:

- **encrypted_email_address**: Client-side encrypted with `email_encryption_key` (primary storage)
- **user_email_salt**: Plaintext salt unique per user (enables key derivation)
- **encrypted_email_with_master_key**: Email encrypted with master key (for passwordless passkey login)
- **encrypted_email_auto_topup**: Server-side encrypted with Vault (for automated billing receipts)
- **hashed_email**: SHA256(email) for uniqueness checks and user lookup only

### Key Derivation

```javascript
// Client-side only - server never sees this derivation
email_encryption_key = SHA256(email + user_email_salt)
```

### Security Properties

- **Server never stores email keys**: Keys derived client-side only during login
- **Temporary server access**: Email decrypted in-memory only during active operations
- **Per-user salt isolation**: Each user has unique salt preventing key reuse
- **Multiple encryption layers**: Different keys for different use cases

## Email Usage Scenarios

### 1. Login Notifications

**Password Login Flow:**
1. Client derives `email_encryption_key = SHA256(email + user_email_salt)`
2. Client sends `email_encryption_key` temporarily to server during login
3. Server decrypts email in-memory: `decrypt(encrypted_email_address, email_encryption_key)`
4. Server sends new device login notification
5. Server immediately discards encryption key from memory

**Passkey Login Flow:**
1. User authenticates with passkey (no email entry required)
2. Server returns `encrypted_email_with_master_key` to client
3. Client decrypts email using master key
4. Client derives `email_encryption_key` and sends to server
5. Server temporarily decrypts for notification and discards key

### 2. Payment Processing

For payment receipts and billing:
- **Auto top-up receipts**: Uses `encrypted_email_auto_topup` (Vault-encrypted, server can decrypt)
- **Manual payment receipts**: Client provides `email_encryption_key` during payment flow
- **Invoice delivery**: Server decrypts email only during send operation

### 3. Email Service Integration (Mailjet)

- **Transactional sending**: Server decrypts recipient email only at send time (in-memory)
- **No contact list management**: We use Mailjet's Send API only, never upload contact lists
- **Third-party logs**: Mailjet may retain delivery logs per their policies (standard for email providers)

## Invoice Privacy Protection

### Customer Identification

To protect email privacy on invoices and accounting records:

- **Account ID system**: 7-character human-readable identifier (e.g., "K7M9P2S")
- **Plaintext storage**: Account IDs stored in plaintext for business operations
- **Invoice schema**: Contains account ID only, never email addresses
- **Non-sequential generation**: Account IDs are randomly generated for privacy

### German Legal Compliance

- **Business record requirements**: Account IDs satisfy German invoice requirements
- **Privacy protection**: Personal email addresses never appear in accounting systems
- **Customer support**: Staff can locate users via account ID lookup without email access

## Security Architecture

### Email Decryption Timeline

```
Login Event ──┬──> Client derives email_encryption_key
              │
              ├──> Server receives key temporarily
              │
              ├──> Server decrypts email (in-memory only)
              │
              ├──> Server sends notification email
              │
              └──> Server discards key immediately
```

### Multiple Encryption Layers

```
Email Address Protection Stack:

┌──────────────────────────────────────────────────┐
│ THREAT: Server compromise → Emails exposed       │
├──────────────────────────────────────────────────┤
│                                                  │
│  Layer 1: Client-Side Encryption ✅              │
│  └─ SHA256(email + salt) key derivation          │
│                                                  │
│  Layer 2: Ephemeral Server Keys ✅               │
│  └─ Keys sent only during active operations      │
│                                                  │
│  Layer 3: Per-User Salt Isolation ✅             │
│  └─ Unique salts prevent cross-user attacks      │
│                                                  │
│  Layer 4: No Persistent Key Storage ✅           │
│  └─ Server never stores decryption keys          │
│                                                  │
│  RESULT: Server breach = encrypted email blobs   │
│                                                  │
└──────────────────────────────────────────────────┘
```

### Vault Integration for Automated Systems

For server-side operations requiring email access without user interaction:

- **encrypted_email_auto_topup**: Stored using HashiCorp Vault transit encryption
- **Server-controlled decryption**: Vault manages keys for automated billing
- **Use cases**: Low balance notifications, payment failure alerts
- **Isolation**: Separate from user-controlled encryption keys

## Privacy Guarantees

### What the Server Cannot See

- **Plaintext email addresses**: All emails stored encrypted
- **Email encryption keys**: Keys derived client-side only
- **Email patterns**: Server cannot correlate emails across users
- **User lookup by email**: Server uses hashed_email for lookups only

### What the Server Can Access

- **Encrypted email blobs**: Useless without user-derived keys
- **Account IDs**: For business operations and invoicing
- **Email salts**: Required for client-side key derivation
- **Vault-encrypted emails**: Only for automated billing (separate key system)

### Third-Party Exposure

- **Mailjet delivery logs**: Standard for email service providers
- **Payment processor receipts**: Required for transaction completion
- **No marketing lists**: We never upload email lists to external services

## Implementation Files

### Client-Side Email Encryption
- **[`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)**: Email encryption/decryption logic

### Server-Side Email Handling
- **[`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py)**: Login flow with email decryption
- **[`backend/core/api/app/routes/auth_routes/auth_2fa_setup.py`](../../backend/core/api/app/routes/auth_routes/auth_2fa_setup.py)**: Setup flows with email access
- **[`backend/core/api/app/utils/encryption.py`](../../backend/core/api/app/utils/encryption.py)**: Vault integration for server-side encryption

### UI Components
- **[`frontend/packages/ui/src/components/Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte)**: Login interface with email handling

## Best Practices

1. **Minimal server exposure**: Only decrypt emails during active operations
2. **Immediate key disposal**: Discard encryption keys from server memory ASAP
3. **Separate key systems**: User-controlled vs. server-controlled encryption
4. **Account ID usage**: Use account IDs instead of emails for business records
5. **Client-side derivation**: Never transmit email encryption keys unnecessarily

For overall encryption architecture, see [Zero-Knowledge Storage](./zero_knowledge_storage.md).
For authentication implementation, see [Signup & Login](./signup_login.md).