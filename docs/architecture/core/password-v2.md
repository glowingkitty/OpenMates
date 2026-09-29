---
status: implementing
last_verified: 2026-09-28
key_files:
  - backend/core/api/app/routes/auth_routes/auth_login.py
  - backend/core/api/app/routes/auth_routes/auth_password.py
  - backend/core/api/app/routes/auth_routes/auth_sensitive.py
  - frontend/packages/ui/src/services/cryptoService.ts
  - frontend/packages/openmates-cli/src/crypto.ts
  - apple/OpenMates/Sources/Core/Crypto/CryptoManager.swift
---

# Versioned password authentication and account-key wrapping

The existing account master key remains the same across devices. A password
protects a downloadable wrapper for that key; changing the password replaces
the wrapper, not the key or the chat ciphertext. Password, passkey, and recovery
login remain independent ways to unwrap the same account key. Enrollment in an
authenticator app remains optional at signup and ordinary password login.

## Version 2 protocol

The client derives 32 bytes with Argon2id v19 from the exact UTF-8 password
and the account's existing random `user_email_salt`: 65,536 KiB of memory,
three iterations, one lane. HKDF-SHA256 with an empty salt and distinct ASCII
`openmates/password-v2/auth` and `openmates/password-v2/wrap` info values
produces 32-byte authentication and wrapping subkeys. All clients must agree
on the same test vector before using version 2. These parameters are versioned;
they are not inferred from the client platform.

The wrapping subkey AES-GCM encrypts the account master key locally. The
backend stores only the ciphertext, IV, version, and immutable wrapper method.
At password setup or a verified credential migration, the client sends the
authentication subkey once over the protected channel. The backend seals it
under the existing per-user Vault transit key and stores only that envelope.
It never stores a reusable fast password lookup for a version-2 record.

For login, the server issues a 32-byte random, one-use, 120-second challenge
bound to the account hash, login session ID, and purpose. The client returns
an HMAC-SHA256 proof under the authentication subkey over the protocol label,
purpose, and raw nonce. The server atomically claims the challenge, opens the
Vault-sealed subkey transiently, verifies the proof, and returns the committed
master-key wrapper for local unlock. Missing accounts get an indistinguishable
challenge response. A captured login proof cannot be reused for another
challenge, session, account, or purpose.

The same challenge mechanism is used with a one-use email code for sensitive
actions when no authenticator is enrolled. The email code is an additional
verification step, not a replacement for the password proof or a claim of
phishing-resistant multi-factor authentication. Passkey and enrolled TOTP
verification remain preferred. The resulting proof expires after five minutes
on the same logical session; refresh cannot extend it.

## Migration and compatibility

New password accounts use version 2 once web, CLI signup, Apple, and backend
pass the same vectors and login tests. Existing version-1 password, passkey,
and recovery-key login remain available. A typed version-1 password upgrade
is attempted only after successful local password unlock, a fresh verified
password login, and recent server-verified sensitive-action assurance on that
same logical session. If assurance is absent, ordinary login and chat
decryption finish without an added prompt; the upgrade waits for a later
eligible session. A client then stages a version-2 wrapper and sealed
authentication key while the version-1 record remains usable. On the same authoritative session,
the client answers a one-use version-2 migration challenge, locally unwraps
the staged server-returned wrapper, and compares its account master key to
the already unlocked key. Only then does an explicit confirmation retire a
typed version-1 password hash. The server rechecks assurance at the retirement
boundary, so a stolen session and an exposed legacy lookup hash cannot replace
the verifier by themselves. This does not require a second login secret on
ordinary login, and it keeps the last usable wrapper after an interrupted
migration. Clients check
the staged-protocol capability before starting so an older self-host server
cannot silently run an immediate-retirement path.

Typed version-1 password records identify the hash that can be retired.
Older accounts have a mixed, untyped lookup-hash list and password-labeled
wrappers without a hash-to-wrapper link. The backend cannot prove which mixed
hash is the current password. Such hashes must not be guessed away during
migration: ordinary login and chat decryption remain available, while
sensitive actions use the approved temporary legacy-secret-plus-email path
and are labeled as legacy assurance. Retirement of an ambiguous old hash
requires a separately verified association or an explicit account migration
procedure. Password-change UI must not claim that the prior secret stopped
working while an old hash remains active.

## Required evidence before rollout

- Cross-client Argon2id/HKDF vectors and browser/mobile performance checks.
- Wrong password, stale challenge, replay, account/session/purpose mismatch,
  Vault failure, and interrupted wrapper-switch tests.
- Fresh-device password signup/login/decryption, legacy login, passkey and
  recovery-key login, and password-only sensitive-action browser E2E in
  isolated CI.
- Native Xcode build and runtime validation against the same protocol before
  enabling version-2 Apple signup/login.

The Argon2id cost follows the memory-constrained profile in
[RFC 9106](https://www.rfc-editor.org/rfc/rfc9106) and exceeds the current
[OWASP minimum](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
