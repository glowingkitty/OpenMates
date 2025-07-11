# Security architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## Zero-Knowledge Authentication

Our authentication system follows a zero-knowledge architecture where the server never has access to user passwords, backup codes, or master encryption keys in plaintext form. Authentication is performed by the user's ability to decrypt their own data on the client side.

### Key Principles:
- **Server as encrypted storage**: The server stores encrypted blobs but cannot decrypt them
- **Client-side verification**: Authentication success is determined by successful decryption of the master key
- **No traditional password verification**: The server never verifies passwords directly

## User signup

- User-specific master encryption key generated on user device & encrypted via login method before being uploaded to server
- User-specific server encryption key is generated on server and stored in HashiCorp Vault
- Username, email address and other less sensitive user data which server needs access to independent of user login are encrypted using server encryption key
- **Email addresses are stored both hashed (for lookup) and encrypted (for operational use)**

## Chats

- For each chat a separate encryption key is generated
- On user device chat encryption key is encrypted using user master encryption key, before being uploaded to server 
- User device encrypts & decrypts chats via AES, using decrypted chat encryption key

## API Keys

- API keys follow the same zero-knowledge pattern as passwords
- Each API key generates its own wrapped master key using Argon2 derivation
- API keys are hashed (not stored in plaintext) for server-side lookup
- Users must approve new IPs accessing their account via API keys in web interface (and also receives email about new IP trying to access the account via API key with option to accept or decline and deactivate api key in web ui after login)

## App skills

- If user hasn't explicitly mentioned via @ specific app skill, user has to first confirm each app skill call
- Details of which data app skill had as input and created as output are visible in UI (and therefore also saved, encrypted on user device)
- Output of APIs are first processed by safety LLM request before being further processed by app skill (protection against prompt injection attacks) 

## App settings & memories

- If user hasn't explicitly mentioned via @ specific app settings & memories, user has to first confirm each the submitting of the requested app settings & memories

## Terms explained

### encryption_key_user_local

On user device generated encryption key during signup. **A separate wrapping key is derived from the user's secret (e.g., password and a unique salt, using Argon2) to encrypt this key before the resulting encrypted blob is stored on the server.** If "Stay logged in" is selected during login, decrypted key will be stored in local-storage, else it's saved in session-storage. If no encryption key is found in either on page reload, user is auto logged out and all local user data are auto deleted (will be downloaded again on next login).

### encryption_key_user_server

On server generated encryption key during signup, encrypted & stored in HashiCorp Vault. Used for encrypting data which server needs access to (email address).

### encryption_key_chat

On user device generated encryption key for each chat.
Encrypted on user device via AES using encryption_key_user_local.

### encryption_key_user_app

On user device generated encryption key for each app for which the user saves settings & memories. Generated the first time user is saving settings & memories for an app. Encrypted on user device via AES using encryption_key_user_local.

### pre_processing

Requests via mistral small model json output with keys:

- harmful_or_illegal_request_chance
- category
- selected_llm

### post_processing

Requests via mistral small model json output with keys:

- follow_up_user_message_suggestions
	- list of strings (with max 6 words)
- new_chat_user_message_suggestions
	- list of strings (with max 6 words)
- harmful_or_illegal_response_chance
	- int 0-10
	- if above 6: hide assistant response immediately and replace it with "Sorry, I think my response was problematic. Could you rephrase and elaborate your request?"

### server_error_processing

If server error occurs while processing user request, return default response:
"Sorry, an error occurred while I was processing your request. Be assured: the OpenMates team will be informed. Please try again later."

### app_skill_output_security_scan

Requests via mistral small model json output with keys:

- prompt_injection_attack_chance
	- int 0-10
	- Used for app skills with reasonable chance output could include prompt injection attack
	- if above 6: replace output with "Content replaced with this security warning. Reason: Security scan revealed high chance of prompt injection attack."