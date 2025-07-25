# Security architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## Zero-Knowledge Authentication

Our system uses a zero-knowledge authentication model: the server never sees passwords, passkeys, backup codes, or encryption keys in plaintext. Authentication requires both server-side verification of cryptographic hashes and client-side ability to decrypt the master key.

### Key Principles

- **Server = encrypted storage only**: It stores blobs it cannot decrypt
- **Dual verification authentication**:
  1. Server-side: Verifies the provided lookup hash exists in the user’s registered lookup hashes
  1. Client-side: Successful login requires successful decryption of the master key
- **No plaintext credential verification**: The server never receives or verifies plaintext credentials
- **Two-step user identification**:
  1. First, the server locates the user record using the email hash
  1. Then, it verifies authentication by checking if the provided lookup hash exists in the user’s registered lookup hashes
- **Privacy-preserving lookups**: Server uses cryptographic hashes, never plaintext identifiers
- **Multiple login methods per user**: Users are encouraged to register multiple secure login options

## Email Encryption Architecture

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
  - Adds lookup_hash to the user’s user_lookup_hashes array
  - Associates the wrapped encryption key with that lookup_hash and method
  - Generates and stores a unique account_id for invoice/accounting use
  - (If method is password) Requires the user to:
    - Set up OTP-based 2FA (e.g., TOTP via Google Authenticator)


## Login Flow

Three supported login methods:

- Password (+ 2FA)
- Passkey
- Recovery Key (offline fallback, stored securely by the user)

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

- lookup_hash = SHA256(recovery_key + salt)
- Recovery key unlocks its own wrapped master key directly (like passkeys or passwords)


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

- We use the WebAuthn PRF extension to derive a passkey secret client-side
- lookup_hash = SHA256(passkey_prf_secret + salt)
- Like all methods, this generates a unique wrapped master key and salt



## Chats

- Each chat has its own symmetric encryption_key_chat
- Chat keys are encrypted with the user’s decrypted encryption_key_user_local and uploaded
- Messages are AES-encrypted/decrypted on the client



## API Keys

- API keys authenticate without requiring the user email on each request; the API key alone serves as credential
- For each API key, the server stores:
  - api_key_hash = SHA256(api_key) for lookup
  - wrapped master key encrypted with Argon2 derived from the API key
  - Argon2 salt
  - Status (active, revoked)
  - Allowed IP addresses list
  - Pending IP addresses list awaiting user confirmation
  - Metadata (creation date, last used date, label, etc.)
- On each API request, server looks up API key by hash
- If request originates from an unknown IP, access is blocked and the IP is added to pending list
- User receives notification in the web UI and must explicitly approve the new IP before requests from it are accepted
- After IP approval, subsequent requests from the IP are accepted seamlessly
- This approach provides strong protection against unauthorized API key usage, balancing usability and security
- API keys allow loading the wrapped master key and encrypted user data; client-side SDK decrypts data using the API key



## App Skills

- If user hasn’t explicitly used an app skill via @skill, manual confirmation is required for sensitive skills (skills which can cause huge financial costs or harm if not executed with clear consent of user. Example: Send email, Generate video, Delete server, etc.)
- All input/output data is encrypted client-side and shown in the UI
- App skill output is filtered via a safety LLM to detect prompt injection and misuse



## App Settings & Memories

- Each app the user uses has its own encryption_key_user_app
- This key is generated on first use and encrypted with the user’s master encryption key
- App settings & memories are encrypted client-side before being uploaded



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

Each input request is passed through a lightweight LLM with output:

- harmful_or_illegal_request_chance
- category
- selected_llm

### Post-processing

The final LLM output is analyzed for:

- follow_up_user_message_suggestions
- new_chat_user_message_suggestions
- harmful_or_illegal_response_chance (0–10)
- If >6: output is suppressed with:
  > “Sorry, I think my response was problematic. Could you rephrase and elaborate your request?”

### App Skill Output Security Scan

- prompt_injection_attack_chance evaluated per app skill output
- If >6:
  > “Content replaced with this security warning. Reason: Security scan revealed high chance of prompt injection attack.”

### Server Error Handling

If server fails:

> “Sorry, an error occurred while I was processing your request. Be assured: the OpenMates team will be informed. Please try again later.”

### Assumptions & Consequences

1. - **Assumption:** Our server will get hacked eventually, our database will get exposed eventually.
   - **Consequence:** Store user data e2ee so that attackers can’t do anything useful with the data. Even email addresses are client-side encrypted with user-controlled keys.

2. - **Assumption:** Governments will request user data and we won’t be able to verify if the reason is ethically right and truthful.
   - **Consequence:** Protect sensitive user data at rest using e2ee with user-controlled keys. If we don’t have the encryption keys, we can’t hand them out. Also, no storing of logs beyond the minimum required for account security reasons.

3. - **Assumption:** Users will eventually succeed in accessing system prompts for every LLM-powered software.
   - **Consequence:** Embrace it. Project is open source, so everyone can see the prompt parts anyway. Detecting prompt injection attacks and refusing to reply in such cases is only part of the security architecture. More important when building the system prompt: data minimization. Only include strictly needed data and use function calling to access additional data.