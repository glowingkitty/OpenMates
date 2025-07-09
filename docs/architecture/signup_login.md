# Signup & login architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## Signup

### Step 1 - Basics

- user is asked for username and email address and to confirm terms of service and privacy policy
- user clicks continue to start server request
- server checks if email address is already in use or not and continues to step 2 (confirm email address) if not yet in use

### Step 2 - Confirm email address

- one time confirmation code is send to email address
- user enters one time code from email and it's validated once entered. If code is valid, signup continues with step 3 (secure account)
- user can also choose to click "Send again"

## Step 3 – Secure Account

- The user chooses how to secure their account: with a passkey or a password (support for hardware keys like YubiKey coming later).
- If passkey is selected:
	- A request is sent to the server to initiate passkey registration.
	- The server responds with a WebAuthn PublicKeyCredentialCreationOptions object.
	- The frontend uses the browser’s WebAuthn API to prompt the user to create a passkey
	- Once the user consents, the browser generates the credential and returns it to the frontend.
	- The frontend sends the credential data to the server.
	- The server verifies the attestation and stores the passkey’s credential ID, signCount and public key in the user data in the database.
	- user device is generating encryption key for user and uses Webauthn PRF extension (supported by iOS 18 & newer, Chrome, Android, Windows 11. However, some password managers like bitwarden might not support it. Need to consider fallback option.) to encrypt the encryption key, before uploading wrapped encryption key to server
	- user account is created on server
	- user is logged in on device (and consider the "Stay logged in" toggle selection in step 3 to decide where to store decrypted encryption key - in session-storage or local-storage).
	- continue to step 4 (setup backup codes)
- if password:
	- continue to step 3.1 (setup password)

## Step 3.1 - Setup password

- enter password & confirm password
- when user clicks continue:
	- user device is generating encryption key for user and derives secret based on email and password 
to encrypt the encryption key, before uploading wrapped encryption key to server
	- user account is created on server (password is saved hashed in database)
	- user is logged in on device (and consider the "Stay logged in" toggle selection in step 3 to decide where to store decrypted encryption key - in session-storage or local-storage).
	- continue to step 3.2 (setup otp 2fa)


## Step 3.2 - Setup OTP 2FA


## Step 4 - Setup backup codes

- ask if user wants to setup backup codes
- explain pro: login option in case access to passkey or 2fa otp is lost
- explain risk: everyone with backup code could can login to user account, security risk if not securely stored.
- if user chooses to create backup codes: generate codes (on user device or server?), save hashes in user profile on server, and generate on user device a wrapped encryption key for each backup code, and upload wrapped encryption keys to server (including "key_hash" field to request only specific key on login and not having to loop over each key from server)


## Step 5 - Upload profile image

... (work in progress)