# Security architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## Zero-Knowledge Authentication

Our system uses a zero-knowledge authentication model: the server never sees passwords, passkeys, backup codes, or encryption keys in plaintext. Authentication requires both server-side verification of cryptographic hashes and client-side ability to decrypt the master key.

### Key Principles

- **Server = encrypted storage only**: It stores blobs it cannot decrypt
- **Dual verification authentication**:
  1. Server-side: Verifies the provided lookup hash exists in the user's registered lookup hashes
  2. Client-side: Successful login requires successful decryption of the master key
- **No plaintext credential verification**: The server never receives or verifies plaintext credentials
- **Two-step user identification**: 
  1. First, the server locates the user record using the email hash
  2. Then, it verifies authentication by checking if the provided lookup hash exists in the user's registered lookup hashes
- **Privacy-preserving lookups**: Server uses cryptographic hashes, never plaintext identifiers
- **Multiple login methods per user**: Users are encouraged to register multiple secure login options

---

## User Signup

- The client:
  - Generates a unique **master encryption key**
  - Encrypts that key (wrapped key) using the selected login method (e.g., password)
  - Computes:
    - `email_hash = SHA256(email)`
    - `lookup_hash = SHA256(email + login_secret)`  
      `login_secret` = password, passkey PRF value, or backup code
  - Sends to server:
    - Plaintext `email` and `username` (so server can send verification/security emails)
    - `email_hash`
    - `lookup_hash`
    - Wrapped master encryption key
    - Login method type (`password`, `passkey`, or `backup_code`)
- The server:
  - Stores `email`, `username`, etc., encrypted via `encryption_key_user_server` (stored in HashiCorp Vault)
  - Stores `email_hash` as an indexed field for fast login lookup
  - Adds `lookup_hash` to the user’s `user_lookup_hashes` array
  - Associates the wrapped encryption key with that `lookup_hash` and method
  - (If method is password) Requires the user to:
    - Set up OTP-based 2FA (e.g., TOTP via Google Authenticator)
    - Confirm email

---

## Login Flow

Three supported login methods:
- **Password (+ 2FA)**
- **Passkey**
- **Backup Code**

Login always proceeds as follows:

### 1. Client sends:

- `email_hash = SHA256(email)`
- `lookup_hash = SHA256(email + login_secret)`
- (Optional) `otp_code` (required for password logins)

### 2. Server logic:

1. **User identification (first step)**: Lookup user by `email_hash`
2. **Authentication verification (second step)**: Within the identified user record, check if the provided `lookup_hash` exists in the user's `user_lookup_hashes` array
3. If the lookup hash is found:
   - If login method is password:
     - Verify the submitted `otp_code` against user's registered TOTP secret
     - If TOTP is missing or incorrect → reject
   - If everything matches:
     - Return the **corresponding encrypted wrapped master key** and **Argon2 salt**
4. If either step fails (user not found by email hash OR lookup hash not in user's array):
   - Return generic failure (does not disclose which specific step failed)

### 3. Client:

- Derives a key using `Argon2(login_secret, salt)`
- Attempts to decrypt the wrapped master key
- If decryption succeeds → login is successful
- The decrypted key is stored in localStorage or sessionStorage depending on “stay logged in”

### 🔁 Multiple login methods per user:

Each login method (password, passkey, backup code) has:
- Its own `lookup_hash`
- Its own wrapped master key
- Its own Argon2 salt

This allows users to recover access using alternate methods if one is lost.

---

## Backup Codes

- Backup codes are generated and shown to the user during signup or in settings
- Each backup code:
  - Has a unique `lookup_hash = SHA256(email + backup_code)`
  - Has its own wrapped master key and salt
- Backup codes are single-use unless explicitly regenerated

---

## Passkey (WebAuthn)

- We use the WebAuthn [PRF extension](https://www.w3.org/TR/webauthn-3/#prf-extension) to derive a **passkey secret** client-side
- `lookup_hash = SHA256(email + passkey_prf_secret)`
- Like all methods, this generates a unique wrapped master key and salt

---

## Chats

- Each chat has its own symmetric `encryption_key_chat`
- Chat keys are encrypted with the user’s decrypted `encryption_key_user_local` and uploaded
- Messages are AES-encrypted/decrypted on the client

---

## API Keys

- API keys authenticate without requiring the user email on each request; the API key alone serves as credential  
- For each API key, the server stores:
  - `api_key_hash = SHA256(api_key)` for lookup  
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

---

## App Skills

- If user hasn’t explicitly used an app skill via `@skill`, manual confirmation is required
- All input/output data is encrypted client-side and shown in the UI
- App skill output is filtered via a safety LLM to detect prompt injection and misuse

---

## App Settings & Memories

- Each app the user uses has its own `encryption_key_user_app`
- This key is generated on first use and encrypted with the user’s master encryption key
- App settings & memories are encrypted client-side before being uploaded

---

## Terms Explained

### `email_hash`

- `SHA256(email)`
- Used to look up the user record
- Plaintext email is never used in auth flows

### `lookup_hash`

- `SHA256(email + login_secret)`
- Unique per login method
- Stored in the user’s `user_lookup_hashes` array

### `user_lookup_hashes`

- A list of accepted `lookup_hash` values
- One for each login method (password, passkey, backup code, API key)

### `login_secret`

- The secret used to derive the wrapped key
- Can be:
  - Password
  - WebAuthn PRF value
  - Backup code
  - API key

### `wrapped_master_key`

- The user’s master encryption key, encrypted with a key derived from `login_secret` via `Argon2`
- Stored alongside the `lookup_hash` and `login_method_type`

### `encryption_key_user_local`

- Generated client-side at signup
- Decrypted locally after login and used to encrypt/decrypt all user data

### `encryption_key_user_server`

- Stored in HashiCorp Vault
- Used only to encrypt server-visible data: email, username, preferences

### `encryption_key_chat`

- AES key used for chat encryption, generated client-side per chat

### `encryption_key_user_app`

- App-specific key for settings/memories, encrypted using `encryption_key_user_local`

---

## Safety Layers

### Pre-processing

Each input request is passed through a lightweight LLM with output:

- `harmful_or_illegal_request_chance`
- `category`
- `selected_llm`

### Post-processing

The final LLM output is analyzed for:

- `follow_up_user_message_suggestions`
- `new_chat_user_message_suggestions`
- `harmful_or_illegal_response_chance` (0–10)
  - If >6: output is suppressed with:
    > “Sorry, I think my response was problematic. Could you rephrase and elaborate your request?”

### App Skill Output Security Scan

- `prompt_injection_attack_chance` evaluated per app skill output
- If >6:
  > “Content replaced with this security warning. Reason: Security scan revealed high chance of prompt injection attack.”

### Server Error Handling

If server fails:

> “Sorry, an error occurred while I was processing your request. Be assured: the OpenMates team will be informed. Please try again later.”


## Assumptions & Consequences

1. Assumption: Our server will get hacked eventually, our database will get exposed eventually.
	Consequence: Store user data e2ee so that attackers can’t do anything useful with the data (so that worse case scenario would be that they can decrypt the user email addresses using the hashicorp vault managed keys).

2. Assumption: Goverments will request user data and we won’t be able to verify if or not the reason is ethically right and truthful.
	Consequence: Protect sensitive user data at rest using e2ee using user controlled keys. If we don't have the encryption keys, we can't hand them out. Also, no storing of logs beyond the minimum required for account security reasons.

3. Assumption: Users will succeed with be able to access system prompt eventually, for every LLM powered software.
	Consequence: Embrace it. Project is open source, so everyone can see the prompt parts anyway. Detecting prompt injection attacks and refusing to reply in such cases is only a part of the security architecture. More important when it comes to building the system prompt: data minimization. Only include the data which are stricktly needed and function calling to access more data.