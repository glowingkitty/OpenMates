# Security architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## Security Controls Summary

| Risk Category | Control | Implementation | Status |
|---|---|---|---|
| Token Exposure | Hash-based logging instead of plaintext | `auth_login.py:19` | ✅ Implemented |
| Weak Key Generation | Cryptographically secure RNG | `cryptoService.ts:120-130` | ✅ Implemented |
| Plaintext Password Storage | Zero-knowledge lookup hash verification | `auth_login.py:13-18` | ✅ Implemented |
| Email Exposure | Client-side encrypted email storage | `security.md#email-encryption-architecture` | ✅ Implemented |
| Weak Randomness in Recovery Keys | crypto.getRandomValues() | `cryptoService.ts:120-130` | ✅ Implemented |
| Brute Force Attacks | Rate limiting + 2FA + Email verification | `auth_login.py:50-51, 200-250` | ✅ Implemented |
| XSS/Injection Attacks | CSP Headers | `middleware.py` | 🔄 Planned (Q4) |
| Email Enumeration | Timing-consistent responses | `SECURITY_CONSIDERATIONS.md#email-enumeration` | 🔄 Future |
| Weak PBKDF2 Iterations | 100,000 iterations (2010 standard) + 2FA | `cryptoService.ts:83-92` | ✅ Adequate (600k deferred) |
| Master Key XSS Exposure | SessionStorage only (no localStorage) | `cryptoService.ts:121-155` | ✅ Implemented |

---

## Zero-Knowledge Authentication

Our system uses a zero-knowledge authentication model: the server never sees passwords, passkeys, backup codes, or encryption keys in plaintext. Authentication requires both server-side verification of cryptographic hashes and client-side ability to decrypt the master key.

### Key Principles

- **Server = encrypted storage only**: It stores blobs it cannot decrypt
- **Dual verification authentication**:
  1. Server-side: Verifies the provided lookup hash exists in the user's registered lookup hashes
  1. Client-side: Successful login requires successful decryption of the master key
- **No plaintext credential verification**: The server never receives or verifies plaintext credentials
- **Two-step user identification**:
  1. First, the server locates the user record using the email hash
  1. Then, it verifies authentication by checking if the provided lookup hash exists in the user's registered lookup hashes
- **Privacy-preserving lookups**: Server uses cryptographic hashes, never plaintext identifiers
- **Multiple login methods per user**: Users are encouraged to register multiple secure login options

<details>
<summary><b>How we ensure passwords never reach the server</b></summary>

**Risk**: Server compromise exposing user passwords
**Control**: Client-side lookup_hash derivation - server only sees hash, never plaintext

**Implementation**:
```javascript
// ✅ CORRECT: Frontend never sends plaintext password
// frontend/packages/ui/src/services/cryptoService.ts:150-160
const lookup_hash = await deriveHash(password + salt)
const payload = {
  lookup_hash,  // ← Server gets HASH only
  // password NOT included ✅
}
```

**Server-side verification**:
```python
# ✅ CORRECT: Backend verifies hash exists, never sees password
# backend/core/api/app/routes/auth_routes/auth_login.py:150-160
lookup_hash_from_client = request.body["lookup_hash"]
stored_hashes = user.user_lookup_hashes
if lookup_hash_from_client in stored_hashes:
    authentication_succeeds()  # ✅ Password never transmitted or stored
```

**Result**: Even if server is compromised, attacker gets hashes (useless without the plaintext password)

[View full implementation](../../backend/core/api/app/routes/auth_routes/auth_login.py#L150)

</details>

## Email Encryption Architecture

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts) (client-side) and [`backend/core/api/app/routes/auth_routes/auth_2fa_setup.py`](../../backend/core/api/app/routes/auth_routes/auth_2fa_setup.py) (server-side)

### Storage Schema

- **user_email_salt**: Plaintext salt unique per user
- **encrypted_email**: Client-side encrypted email address
- **hashed_email**: SHA256(email) for uniqueness checks and user lookup
- **lookup_hash**: SHA256(login_secret + salt) for authentication

### Key Derivation

```javascript
// Client-side only
email_encryption_key = SHA256(email + user_email_salt)
```

### Login Flow with Email Decryption

1. User enters email + password/passkey
2. Client derives lookup_hash = SHA256(email + login_secret)
3. Client derives email_encryption_key = SHA256(email + user_email_salt)
4. Client sends { lookup_hash, email_encryption_key } to server
5. Server finds user by lookup_hash
6. Server temporarily decrypts email: decrypt(encrypted_email, email_encryption_key)
7. Server sends notification email about new device login (if device is new)
8. Server immediately discards encryption key
9. Returns session token to client

### Security Properties

- Server never persistently stores email encryption keys
- Email plaintext never persists on server
- Each user has unique salt preventing key reuse across users
- Server gets temporary decryption capability only during active login
- Authentication fails if wrong credentials (email decryption produces invalid result)

### Email Encryption Security Stack

```
┌──────────────────────────────────────────────────┐
│ THREAT: Server compromise → Emails stolen        │
├──────────────────────────────────────────────────┤
│                                                  │
│  Layer 1: Client-Side Encryption ✅              │
│  └─ SHA256(email + salt)                         │
│     Code: cryptoService.ts:37-45                 │
│                                                  │
│  Layer 2: Ephemeral Key ✅                       │
│  └─ Key discarded immediately after use          │
│     Code: auth_2fa_setup.py:120-130              │
│     ⚠️  Only sent during login, never stored     │
│                                                  │
│  Layer 3: Unique Salt Per User ✅                │
│  └─ Prevents key reuse across user base          │
│     Code: security.md#storage-schema             │
│                                                  │
│  Layer 4: No Decryption Keys in DB ✅            │
│  └─ Server never stores encryption keys          │
│     Code: auth_2fa_setup.py:150-160              │
│                                                  │
│  RESULT: Server compromise = unreadable data     │
│          attacker gets: encrypted blobs + salt   │
│          attacker cannot get: keys or plaintext  │
│                                                  │
└──────────────────────────────────────────────────┘
```

## Invoice Privacy Protection

### Customer Identification

- Account ID: 7-character human-readable identifier (e.g., “K7M9P2S”) included on invoices
- account_id: Stored in plaintext in the user record on the server; used for invoices and customer support
- Invoice schema: Contains account ID in plaintext, never email addresses

### German Legal Compliance

- Account IDs on invoices satisfy German business record requirements
- Personal email addresses are not exposed on invoices or in accounting systems
- Account IDs are non-sequential and randomly generated, providing privacy protection
- Customer support can locate users directly via account ID lookup

## User Signup

**Implementation**: 
- **Frontend**: [`frontend/packages/ui/src/components/Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte) and [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)
- **Backend**: [`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py)

- The client:
  - Generates a unique master encryption key
  - Generates user_email_salt (random, unique per user)
  - Encrypts email: encrypted_email = encrypt(email, SHA256(email + user_email_salt))
  - Encrypts master key (wrapped key) using the selected login method (e.g., password or passkey)
- Computes:
  - email_hash = SHA256(email)
  - lookup_hash = SHA256(login_secret + salt)
  login_secret = password, passkey PRF value, or recovery key
- Sends to server:
  - email_hash, encrypted_email, user_email_salt
  - lookup_hash
  - Wrapped master encryption key
  - Login method type (password, passkey, or recovery_key)
- The server:
  - Stores encrypted email and salt
  - Stores email_hash as an indexed field for fast login lookup
  - Adds lookup_hash to the user's user_lookup_hashes array
  - Associates the wrapped encryption key with that lookup_hash and method
  - Generates and stores a unique account_id for invoice/accounting use
  - (If method is password) Requires the user to:
    - Set up OTP-based 2FA (e.g., TOTP via Google Authenticator)


## Login Flow

**Implementation**: 
- **Backend**: [`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py)
- **Frontend**: [`frontend/packages/ui/src/components/Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte) and [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)

Three supported login methods:

- Password (+ 2FA) ✅ **IMPLEMENTED**
- Passkey ⚠️ **PLANNED** (not yet implemented)
- Recovery Key (offline fallback, stored securely by the user) ⚠️ **PLANNED** (not yet implemented)

❗ Backup codes do not provide direct access. They are used only as a temporary second factor in combination with a password.

### Backup Code Flow (used with password):

- Client submits:
  - email_hash
  - lookup_hash = SHA256(password + salt)
  - backup_code instead of otp_code
- Server:
  - Verifies password lookup_hash
  - Verifies one-time backup code (marks it as used)
  - If valid, proceeds as with password + otp login

### Recovery Key Flow (standalone full-access login):

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality for offline recovery.

**Planned Implementation**: Future recovery key system (to be created)

- lookup_hash = SHA256(recovery_key + salt)
- Recovery key will unlock its own wrapped master key directly (like passkeys or passwords)


### Backup Codes

- Backup codes are used as a second factor during password login, in place of the OTP code
- Characteristics:
  - Single-use by default
  - Cannot decrypt the master key by themselves
  - When used, mark as consumed and log the event
- Generated during:
  - Initial password + 2FA setup
  - Manually by the user later in settings


### Recovery Key

- A secure, standalone login credential designed for emergency access (loss of password & passkeys)
- Characteristics:
  - Acts like a login method
  - Derives a lookup_hash = SHA256(recovery_key + salt)
  - Has its own wrapped master key and Argon2 salt
  - Not rate-limited as aggressively as backup codes, but recommended to be stored securely offline
  - Only shown once and never retrievable again
  - Can be revoked by the user (deleting its associated lookup_hash entry)


### 🔁 Multiple login methods per user

Each login method has:

- Its own lookup_hash
- Its own wrapped master key
- Its own Argon2 salt

Valid methods include:

- password (with OTP or backup code)
- passkey
- recovery_key



### Passkey (WebAuthn)

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality for passwordless authentication.

**Planned Implementation**: Future WebAuthn integration (to be created)

- We will use the WebAuthn PRF extension to derive a passkey secret client-side
- lookup_hash = SHA256(passkey_prf_secret + salt)
- Like all methods, this will generate a unique wrapped master key and salt


### Magic login link

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality for VSCode extension, CLI, and public computer login.

**Planned Implementation**: Future magic link system (to be created)

Will be used to login in VSCode extension, CLI and also shows up as alternative login option for public computers in login interface where email is showing up.
Will require both devices to enter a random 3 character key that shows up on the other device, before login is possible.

### **Step 1: Device Requests Authentication**

**VSCode Extension:**

1. User opens extension for first time → shows “Login Required”
2. User clicks “Login” button
3. Extension generates unique request token
4. Extension displays authentication dialog with:
- Clickable link: `https://openmates.org/#pair=abc123def456`
- QR code of the same URL
- “Waiting for authentication…” spinner

**CLI:**

1. User runs `myapp login`
2. CLI generates unique request token
3. CLI displays in terminal:
   
   ```
   To login, visit this link or scan the QR code:
   
   https://openmates.org/#pair=abc123def456
   
   [ASCII QR CODE]
   
   Waiting for authentication...
   ```

Both devices start polling server: `GET /api/auth/poll/{request_token}`

### **Step 2: Browser Authentication**

1. User visits pairing URL (clicks link or scans QR on mobile)
2. Browser loads: `https://openmates.org/#pair=abc123def456`
3. If user not logged in → redirects to login page first
4. After login, browser shows device authorization page:
   
   ```
   Authorize device access?
	 
	 Warning: the device will have full access to your account! Keep in mind that no OpenMates related support will ever ask you to login or for your login credentials.
   
   Device: VSCode Extension (or CLI)
   Platform: Windows/macOS/Linux
   IP: 192.168.1.100
   Time: 2:34 PM
   
   [Authorize] [Cancel]
   ```

### **Step 3: Crypto Material Encryption**

1. User clicks “Authorize”
2. Browser generates random 6-digit code: “482751”
3. Browser encrypts crypto bundle using the code
4. Browser uploads to server: `POST /api/auth/complete/{request_token}`
5. Browser shows completion page with “Enter this code: {code} (expires in 2 minutes)

### **Step 4: Device Receives Authentication**

**VSCode Extension:**
1. Extension’s polling detects encrypted bundle is ready
2. Extension shows input dialog: “Enter 6-digit code from browser:”
3. User enters “482751”
4. Extension downloads and decrypts bundle
5. Extension shows “Login successful!” and proceeds to main interface

**CLI:**
1. CLI’s polling detects encrypted bundle is ready  
2. CLI prompts: `Enter 6-digit code from browser: `
3. User types “482751” and presses Enter
4. CLI downloads and decrypts bundle
5. CLI shows “✓ Login successful!” and proceeds

### **Step 5: Cleanup**

1. Server deletes encrypted bundle and request token
2. Both devices now have full crypto materials and can operate normally

### Security Properties

- **No email/account ID required** on device - completely privacy-preserving
- **Same UX for both platforms** - consistent user experience
- **Cross-device/cross-platform** - works between any combinations
- **Zero-knowledge maintained** - server never sees decrypted materials
- **Time-bounded** - request tokens and codes expire quickly
- **User authorization** - explicit consent for each device pairing

This gives you a seamless, privacy-first authentication flow that works identically across all your applications!​​​​​​​​​​​​​​​​


## Chats

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts) and [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)

- Each chat has its own symmetric encryption_key_chat
- Chat keys are encrypted with the user's decrypted encryption_key_user_local and uploaded
- Messages are AES-encrypted/decrypted on the client



## API Keys

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality for developer API access.

**Planned Implementation**: Future API key management system (to be created)

- API keys authenticate without requiring the user email on each request; the API key alone serves as credential
- **Client-side generation**: API keys are generated client-side using cryptographically secure random number generation
- **Zero-knowledge**: The server never sees the plaintext API key; only the hash is uploaded
- **One-time display**: Plaintext API keys are shown only once during creation; users must store them securely
- For each API key, the server will store:
  - api_key_hash = SHA256(api_key) for lookup
  - wrapped master key encrypted with Argon2 derived from the API key
  - Argon2 salt
  - Status (active, revoked)
  - Allowed IP addresses list (or device hashes for CLI/pip/npm)
  - Pending IP addresses list awaiting user confirmation
  - Metadata (creation date, last used date, label/name, etc.)
- On each API request, server will look up API key by hash
- If request originates from an unknown IP/device, access will be blocked and added to pending list
- User will receive notification in the web UI and must explicitly approve the new IP/device before requests from it are accepted
- After IP/device approval, subsequent requests will be accepted seamlessly
- This approach will provide strong protection against unauthorized API key usage, balancing usability and security
- API keys will allow loading the wrapped master key and encrypted user data; client-side SDK will decrypt data using the API key

For detailed information on API key management, device confirmation, and developer settings, see [Developer Settings](./developer_settings.md).



## App Skills

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality for app skills integration.

**Planned Implementation**: Future app skills system (to be created)

- If user hasn't explicitly used an app skill via @skill, manual confirmation will be required for sensitive skills (skills which can cause huge financial costs or harm if not executed with clear consent of user. Example: Send email, Generate video, Delete server, etc.)
- All input/output data will be encrypted client-side and shown in the UI
- App skill output will be filtered via a safety LLM to detect prompt injection and misuse



## App Settings & Memories

**Implementation**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts) and [`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)

### Architecture

Each app the user uses has its own encryption key (`encryption_key_user_app`), following the same pattern as chats. Every individual item (watched movie, planned trip, favorite restaurant, etc.) is stored as a separate Directus row for scalability:

- Generated on first use (per app/user combination)
- Encrypted with user's master encryption key for device sync
- Each item encrypted client-side before upload as separate entry
- Server stores only encrypted items + hashed identifiers, never plaintext data
- Enables server-side pagination, filtering, and efficient selective sync

### Storage Schema

```yaml
user_app_settings_and_memories:
  hashed_user_id: string (indexed)
  app_hash: string (indexed)  # SHA256(app_id + user_email_salt) - server cannot identify which app
  settings_group_hash: string (indexed)  # SHA256(settings_group_key + user_email_salt) - e.g., "watched_movies", "to_watch_list"
  encrypted_app_key: string   # App-specific key, encrypted with master key (same for all items in app)
  encrypted_item_json: text   # Single item encrypted with app_key (e.g., one movie, one restaurant, one trip)
  created_at: integer
  updated_at: integer
  sequence_number: integer  # For maintaining order/sorting client-side
```

### Key Derivation

```javascript
// Client-side only
app_hash = SHA256(app_id + user_email_salt)
settings_group_hash = SHA256(settings_group_key + user_email_salt)
app_encryption_key = generateRandomKey()  // Generated on first use
encrypted_app_key = encrypt(app_encryption_key, master_key)
```

### Client-Side Flow

1. **First use of app**:
   - Generate random `app_encryption_key`
   - Derive: `app_hash = SHA256(app_id + user_email_salt)`
   - Encrypt key: `encrypted_app_key = encrypt(app_encryption_key, master_key)`

2. **Saving an item** (e.g., a movie, restaurant, trip):
   - Serialize single item to JSON according to app schema
   - Derive: `settings_group_hash = SHA256("watched_movies" + user_email_salt)`
   - Encrypt: `encrypted_item = encrypt(item_json, app_encryption_key)`
   - Create one Directus row with all hashed identifiers and encrypted data

3. **Loading app data**:
   - Query: `SELECT * FROM user_app_settings_and_memories WHERE hashed_user_id = X AND app_hash = Y LIMIT 100`
   - Decrypt app key once: `app_key = decrypt(encrypted_app_key, master_key)`
   - Decrypt each item: `item = decrypt(encrypted_item_json, app_key)`

### Server Perspective

- **Cannot identify which app**: Only sees `app_hash` (opaque hash)
- **Cannot identify which settings group**: Only sees `settings_group_hash` (opaque hash)
- **Cannot access plaintext data**: All items remain encrypted
- **Can provide efficient pagination**: `SELECT * ... LIMIT 10 OFFSET 20` without decryption
- **Can sort server-side**: By `created_at`, `updated_at`, `sequence_number` without understanding data
- **Can sync selectively**: Client can request only specific apps/groups by their hashes

### Request/Response Security Model

App settings/memories requests are stored as system messages in chat history (encrypted with chat key). This provides:

- **Zero-knowledge persistence**: Requests encrypted with chat key, server cannot decrypt
- **Client-controlled decryption**: Only client can decrypt app settings/memories using master key
- **Selective sharing**: Client controls which items are shared (accepted/declined per key)
- **No server-side filtering**: Server never sees declined items or filtering logic

For implementation details, see [app_settings_and_memories.md](./apps/app_settings_and_memories.md) and [message_processing.md](./message_processing.md).

### Security Properties

- **Zero-knowledge app storage**: Server never learns app names, group names, or data structure
- **Per-app key isolation**: Compromise of one app's data doesn't affect others
- **Device-agnostic encryption**: Same app key works across all user devices
- **Scalable**: Individual items as rows enable pagination, efficient sync, and selective loading
- **Client-controlled search**: Preprocessing cannot directly search encrypted data; client performs all matching
- **Privacy-preserving selective sync**: Client controls which apps/groups sync to which devices without revealing identities

### Skill-Generated Entries Security

Settings/memories entries created via skills follow zero-knowledge encryption:

- **Temporary plaintext exposure**: Server sees plaintext only during skill validation (schema check)
- **Client-side encryption**: User confirmation triggers client-side encryption with app-specific key
- **Zero-knowledge storage**: Server stores only encrypted data, never plaintext
- **No persistent server access**: Server cannot decrypt stored entries without client cooperation

For implementation details and complete flow, see [app_settings_and_memories.md](./apps/app_settings_and_memories.md#execution-flow).



## Terms Explained

### email_hash

- SHA256(email)
- Used to look up the user record
- Plaintext email is never used in auth flows

### lookup_hash

- SHA256(login_secret + salt)
- Unique per login method
- Stored in the user’s user_lookup_hashes array

### user_lookup_hashes

- A list of accepted lookup_hash values
- One for each login method (password, passkey, recovery key, API key)

### login_secret

- The secret used to derive the wrapped key
- Can be:
  - Password
  - WebAuthn PRF value
  - Recovery key
  - API key

### wrapped_master_key

- The user’s master encryption key, encrypted with a key derived from login_secret via Argon2
- Stored alongside the lookup_hash and login_method_type

### encryption_key_user_local

- Generated client-side at signup
- Decrypted locally after login and used to encrypt/decrypt all user data

### encryption_key_user_server

- Stored in HashiCorp Vault
- Used only to encrypt server-visible data: credits and other low sensitivity data

### encryption_key_chat

- AES key used for chat encryption, generated client-side per chat

### encryption_key_user_app

- App-specific key for settings/memories, encrypted using encryption_key_user_local

### email_encryption_key

- SHA256(email + user_email_salt)
- Derived client-side for email encryption/decryption
- Sent temporarily to server only during login for notification emails

### user_email_salt

- Random salt unique per user, stored in plaintext on server
- Used to derive email encryption key and prevent key reuse across users

### account_id

- 7-character human-readable identifier (e.g., “K7MA9P2”)
- Stored in plaintext in the user record
- Used on invoices and for support lookups

## Safety Layers

### Pre-processing

**Implementation**: [`backend/apps/ai/processing/preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)

Each input request is passed through a lightweight LLM with output:

- harmful_or_illegal_request_chance
- category
- selected_llm

### Prompt Injection Protection

OpenMates implements a layered defense strategy against prompt injection attacks:

For detailed information on prompt injection threats, defense strategies, and implementation recommendations, see the [Prompt Injection Protection Architecture](./prompt_injection_protection.md) document.

### Post-processing

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

**Planned Implementation**: Future dedicated post-processing module (to be created)

The final LLM output is planned to be analyzed for:

- follow_up_user_message_suggestions
- new_chat_user_message_suggestions
- harmful_or_illegal_response_chance (0–10)
- If >6: output is suppressed with:
  > "Sorry, I think my response was problematic. Could you rephrase and elaborate your request?"

### App Skill Output Security Scan

**Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality for when app skills are implemented.

**Planned Implementation**: Future app skills security module (to be created)

- prompt_injection_attack_chance evaluated per app skill output
- If >6:
  > "Content replaced with this security warning. Reason: Security scan revealed high chance of prompt injection attack."

### Server Error Handling

**Implementation**: [`backend/core/api/app/routes/websockets.py`](../../backend/core/api/app/routes/websockets.py) and WebSocket handlers

If server fails:

> "Sorry, an error occurred while I was processing your request. Be assured: the OpenMates team will be informed. Please try again later."

### Assumptions & Consequences

1. - **Assumption:** Our server will get hacked eventually, our database will get exposed eventually.
   - **Consequence:** Store user data e2ee so that attackers can’t do anything useful with the data. Even email addresses are client-side encrypted with user-controlled keys.

2. - **Assumption:** Governments will request user data and we won’t be able to verify if the reason is ethically right and truthful.
   - **Consequence:** Protect sensitive user data at rest using e2ee with user-controlled keys. If we don’t have the encryption keys, we can’t hand them out. Also, no storing of logs beyond the minimum required for account security reasons.

3. - **Assumption:** Users will eventually succeed in accessing system prompts for every LLM-powered software.
   - **Consequence:** Embrace it. Project is open source, so everyone can see the prompt parts anyway. Detecting prompt injection attacks and refusing to reply in such cases is only part of the security architecture. More important when building the system prompt: data minimization. Only include strictly needed data and use function calling to access additional data.

## Implementation Files

### Backend Security Implementation
- **[`backend/core/api/app/utils/encryption.py`](../../backend/core/api/app/utils/encryption.py)**: Core encryption service using HashiCorp Vault
- **[`backend/core/api/app/routes/auth_routes/auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py)**: Zero-knowledge authentication implementation
- **[`backend/core/api/app/routes/auth_routes/auth_2fa_setup.py`](../../backend/core/api/app/routes/auth_routes/auth_2fa_setup.py)**: 2FA setup with email decryption
- **[`backend/core/api/app/services/directus/user/user_authentication.py`](../../backend/core/api/app/services/directus/user/user_authentication.py)**: User authentication service
- **[`backend/core/api/app/services/directus/user/user_profile.py`](../../backend/core/api/app/services/directus/user/user_profile.py)**: User profile management

### Frontend Security Implementation
- **[`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)**: Client-side encryption/decryption service
- **[`frontend/packages/ui/src/services/db.ts`](../../frontend/packages/ui/src/services/db.ts)**: Local database with encryption
- **[`frontend/packages/ui/src/components/Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte)**: Main login component with authentication flow
- **[`frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte`](../../frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte)**: Password and 2FA components
- **[`frontend/packages/ui/src/components/EnterBackupCode.svelte`](../../frontend/packages/ui/src/components/EnterBackupCode.svelte)**: Backup code entry component

### WebSocket Security Handlers
- **[`backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py)**: Encrypted metadata handling
- **[`backend/core/api/app/routes/handlers/websocket_handlers/ai_response_completed_handler.py`](../../backend/core/api/app/routes/handlers/websocket_handlers/ai_response_completed_handler.py)**: AI response completion with encryption