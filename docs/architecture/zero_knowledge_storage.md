# Zero-Knowledge Storage Architecture

OpenMates implements client-side encryption for all sensitive data storage, ensuring the server cannot decrypt user content without user cooperation.

## Core Principles

- **Client-side encryption**: All sensitive data encrypted before storage
- **Server stores encrypted blobs**: Server cannot decrypt stored data without user keys
- **Per-data-type key isolation**: Separate encryption keys for chats, apps, emails
- **Master key never transmitted**: Generated and managed entirely client-side

## Important Note: Chat Inference Processing

**Zero-knowledge storage ≠ Zero server access during active use**

For AI inference, the client **does** send cleartext chat content to the server for processing. Additionally:

- **Server-side caching**: Last 3 chats per user are cached via HashiCorp Vault encryption for faster inference
- **Performance optimization**: Prevents client from resending full chat history on each request
- **Ephemeral access**: Server processes cleartext only during active inference requests
- **Zero-knowledge principle**: Server cannot decrypt historical stored chats without user providing keys

The key distinction: Server needs cleartext for active AI processing, but cannot access stored chat history without user cooperation.

## Master Key Management

### Key Generation

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)

During user signup:
1. Client generates unique master encryption key (`encryption_key_user_local`)
2. Master key wrapped using login method-specific derivation:
   - **Password**: Argon2 key derivation from password + salt
   - **Passkey**: HKDF from WebAuthn PRF signature + user salt (deterministic per device)
   - **Recovery Key**: Argon2 key derivation from recovery key + salt
3. Wrapped master key stored on server, plaintext master key stays client-side only

**Note**: Passkeys use WebAuthn PRF extension to generate deterministic signatures that serve as key material, enabling true passwordless login. For complete passkey implementation details, see [Passkeys](./passkeys.md).

### Key Storage Modes

**Stay Logged In = false** (default for security):
- Master key stored in memory only (module-level variable)
- Automatically cleared when page/tab closes
- No persistence across browser sessions

**Stay Logged In = true** (convenience option):
- Master key stored in IndexedDB as CryptoKey object
- Persists across sessions
- Uses Web Crypto API isolation

**Planned: Public Computer Mode**:
- Master key memory-only with auto-logout after 30 minutes
- IndexedDB deleted on internet disconnect
- Enhanced security for shared devices

## Chat Encryption

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts) and [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)

### Storage vs. Processing Model

**Stored Chat Data (Zero-Knowledge)**:
- Each chat generates unique symmetric encryption key
- Chat keys encrypted with user's master key for storage/sync
- Messages encrypted/decrypted client-side using AES-256-GCM
- Server cannot decrypt stored chat history without user keys

**Active Inference Processing**:
- Client sends cleartext chat content for AI inference
- Server caches last 3 chats per user (HashiCorp Vault encryption)
- Improves performance by reducing redundant data transmission
- Cache is separate from permanent encrypted storage

### Chat Key Immutability & Rotation

- **Immutability by default**: Once a chat has an `encrypted_chat_key`, the server will not accept or broadcast a different key for that chat.
- **Explicit rotation only**: Key updates are allowed only when the client includes an explicit rotation flag
  (used for hidden chat hide/unhide flows).
- **Safety guarantee**: This prevents a single misconfigured device from corrupting the chat key across devices,
  which would make existing messages undecryptable.

### Embed Content Security
- Each embed generates unique key for content encryption
- Parent embeds generate their own key with wrapped key storage
- Child embeds inherit parent's key (no separate key generation)
- Key wrappers stored for cross-chat access and sharing

## Email Encryption

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)

### Email Storage Security
- Email addresses encrypted client-side before storage
- Server stores only encrypted blobs and plaintext salt (unique per user)
- Hashed email used for lookup only, never plaintext email
- Separate encryption for passkey passwordless login

### Key Derivation
Email encryption keys are derived client-side using SHA256 with the user's email and unique salt.

### Security Properties
- Server never stores email encryption keys persistently
- Email decryption only during login (temporary, in-memory)
- Each user has unique salt preventing cross-user key reuse

## App Settings & Memories

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts) and [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)

### Per-App Key Isolation
- Each app generates unique encryption key
- App keys encrypted with master key for device sync
- Individual items stored as separate encrypted database rows

### Privacy-Preserving Storage
- Server cannot identify which app (only sees opaque hashes)
- Server cannot identify settings groups (only sees opaque hashes)
- Server cannot access plaintext data (all items encrypted)
- Server can provide efficient pagination without decryption
- Client controls which apps/groups sync to which devices

## Cryptographic Implementation

### Encryption Standards
- **Symmetric encryption**: AES-256-GCM for all data encryption
- **Key derivation**: PBKDF2-SHA256 (100k iterations) combined with 2FA for passwords
- **Random generation**: Cryptographically secure random generation
- **Key wrapping**:
  - **Passwords**: Argon2 for wrapping master keys
  - **Passkeys**: HKDF from WebAuthn PRF signature for wrapping master keys
  - **Recovery Keys**: Argon2 for wrapping master keys

### Security Architecture

**Layer 1: Client-Side Encryption**
- AES-256-GCM encryption before any data transmission
- All sensitive content encrypted locally before upload

**Layer 2: Per-Data-Type Key Isolation**
- Separate encryption keys for chats, emails, apps, embeds
- Compromise of one data type doesn't affect others

**Layer 3: Master Key Protection**
- Master keys never transmitted to server
- User-controlled key management and derivation

**Layer 4: Secure Key Derivation**
- Argon2 key derivation with unique user salts
- Cryptographically secure random generation

**Result**: Server compromise yields only encrypted blobs useless without user keys

## Implementation Files

### Frontend Encryption
- **[`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)**: Core encryption/decryption service
- **[`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)**: Local encrypted database operations

### Backend Support
- **[`backend/core/api/app/utils/encryption.py`](../../backend/core/api/app/utils/encryption.py)**: Server-side encryption helpers (Vault integration)
- **[`backend/core/api/app/routes/auth_routes/auth_2fa_setup.py`](../../backend/core/api/app/routes/auth_routes/auth_2fa_setup.py)**: Key setup during authentication

### WebSocket Encryption
- **[`backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py)**: Real-time encrypted updates
- **[`backend/core/api/app/routes/handlers/websocket_handlers/ai_response_completed_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/ai_response_completed_handler.py)**: AI response encryption

## Security Guarantees

1. **Zero-knowledge storage**: Server cannot decrypt stored data without user cooperation
2. **Key isolation**: Compromise of one data type doesn't affect others
3. **Forward secrecy**: New chats/apps generate fresh encryption keys
4. **Device independence**: Same keys work across user's devices via encrypted sync
5. **Offline capability**: Local decryption works without server connectivity
6. **Ephemeral processing**: Server only accesses cleartext during active AI inference requests

For authentication flows and login implementation, see [Signup & Login](./signup_login.md).
For email-specific privacy protections, see [Email Privacy](./email_privacy.md).