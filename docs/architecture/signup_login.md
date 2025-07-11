# Signup & login architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## Zero-Knowledge Authentication Flow

Our system uses zero-knowledge authentication where the server never sees plaintext passwords, backup codes, or master encryption keys. Authentication is performed by successfully decrypting encrypted data on the client side.

## Signup

### Step 1 - Basics

- User is asked for username and email address and to confirm terms of service and privacy policy
- User clicks continue to start server request
- Server checks if email address is already in use or not and continues to step 2 (confirm email address) if not yet in use

### Step 2 - Confirm email address

- One time confirmation code is sent to email address
- User enters one time code from email and it's validated once entered. If code is valid, signup continues with step 3 (secure account)
- User can also choose to click "Send again"

## Step 3 – Secure Account

- The user chooses how to secure their account: with a passkey or a password (support for hardware keys like YubiKey coming later).
- If passkey is selected:
	- A request is sent to the server to initiate passkey registration.
	- The server responds with a WebAuthn PublicKeyCredentialCreationOptions object.
	- The frontend uses the browser's WebAuthn API to prompt the user to create a passkey
	- Once the user consents, the browser generates the credential and returns it to the frontend.
	- The frontend sends the credential data to the server.
	- The server verifies the attestation and stores the passkey's credential ID, signCount and public key in the user data in the database.
	- User device is generating encryption key for user and uses WebAuthn PRF extension (supported by iOS 18 & newer, Chrome, Android, Windows 11. If failing: ask user to consider different password manager that supports WebAuthn PRF or signup via password) to encrypt the encryption key, before uploading wrapped encryption key to server
	- User account is created on server
	- User is logged in on device (and consider the "Stay logged in" toggle selection in step 3 to decide where to store decrypted encryption key - in session-storage or local-storage).
	- Continue to step 4 (setup backup codes)
- If password:
	- Continue to step 3.1 (setup password)

## Step 3.1 - Setup password

- Enter password & confirm password
- When user clicks continue:
	- **On the user's device, a master encryption key and a unique salt are generated. A wrapping key is derived from the password and salt using Argon2. This wrapping key is used to encrypt the master key.**
	- **The user's hashed email (for lookup), encrypted email (for operations), the salt, and the wrapped master key are sent to the server. The plaintext password is never sent and is not stored on the server in any form.**
	- User account is created on server
	- User is logged in on device (and consider the "Stay logged in" toggle selection in step 3 to decide where to store decrypted encryption key - in session-storage or local-storage).
	- Continue to step 3.2 (setup otp 2fa)

## Step 3.2 - Setup OTP 2FA

## Step 4 - Setup backup codes

- Ask if user wants to setup backup codes
- Explain pro: login option in case access to passkey or 2fa otp is lost
- Explain risk: everyone with backup code can login to user account, security risk if not securely stored.
- If user chooses to create backup codes: **Codes are generated on the user device. For each code, a unique salt is also generated on the device. The master key is then encrypted using a key derived from the backup code and its salt using Argon2. The server stores only the list of {salt, wrapped_key} pairs. Plaintext codes or their hashes are never sent to the server.**

## Step 5 - Upload profile image

... (work in progress)

## Login Flow

### Password Login:
1. User enters email and password
2. Client computes hashed email for lookup
3. Server returns user's salt, wrapped master key, Argon2 parameters, and auth proof
4. Client derives wrapping key using Argon2(password, salt, params)
5. Client attempts to decrypt wrapped master key
6. **Client decrypts auth proof challenge and sends response to server**
7. **Server verifies proof response**
8. **If verified: server sends encrypted chats/data**
9. **Client decrypts user data using master key**

### Backup Code Login:
1. User enters email and backup code
2. Client gets user's backup wrappers from server
3. Client tries backup code against each wrapper until successful decryption
4. Success = authentication, used backup code is invalidated

### API Key Access:
1. Client sends API key in request header
2. Server hashes API key for lookup
3. If IP is approved: server returns salt, wrapped master key, and encrypted data
4. If IP is pending: server notifies user for approval
5. Client decrypts master key using API key and proceeds with decryption