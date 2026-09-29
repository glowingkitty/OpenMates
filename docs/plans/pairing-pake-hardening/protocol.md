# Pairing protocol implementation contract

This implements the user-approved client-to-client PAKE pairing flow. The
approving client holds the account master key. The receiving client begins
unauthenticated. The API is a relay for encryption and remains the authority
for ordinary account sessions. Running client software is trusted; preventing
a malicious replacement application from reading its own keys is outside this
protocol's guarantees.

## Client cryptography

The implementation uses `@serenity-kit/opaque` 1.1.0 in browser/Node and a native
binding to `opaque-ke` exactly 4.0.0. OPAQUE's server
role runs **inside the approving client**, including fresh local registration
for the generated PIN. Its server setup and registration record never go to
the API. The receiving client runs its client role. This is not a backend
password registration feature.

The ciphersuite is Ristretto255 OPRF, TripleDH with Ristretto255 and SHA-512,
and Argon2id v0x13 with 8192 KiB memory, three iterations, and one lane. The
lower-memory parameters are fixed for Watch interoperability. Registration
records remain ephemeral on the already-unlocked approver; they are never relay
state. The published JS artifact is pinned by lockfile integrity. Its upstream
2023 review predates this release and does not constitute an audit of this
integration. Application bindings include protocol version, pairing token,
receiver session ID, receiver-capability hash, approving user ID, and selected
session lifetime. Role identifiers are `openmates-pair-v2/client/${context}` and
`openmates-pair-v2/server/${context}`; the OPAQUE user identifier is the canonical
context itself. Clients independently
construct and validate the canonical context: UTF-8 JSON without whitespace of
`["openmates-pair",2,token,session_id,receiver_token_hash,authorizer_user_id,auto_logout_minutes]`.
A successful PAKE derives the AES-256-GCM key using HKDF-SHA256 over the decoded
OPAQUE session key, SHA-256(context) as salt, and UTF-8
`openmates-pair-v2/bundle` as info. That context is also AEAD associated data.
The approving client releases the bundle only after validating
the receiving client's final proof. Each client accepts only one peer exchange
per pairing; failure requires fresh ephemeral state and a new pairing/PIN.

## Wire contract

All new endpoints live under `/v1/auth/pair/v2`. Legacy pairing endpoints return
an explicit update-required response without parsing or echoing PIN input.
These are first-party auth endpoints, with existing Origin/native client rules,
strict request-size/schema limits, and rate limits. No developer API-key access
or paid provider operation is introduced.

The receiver generates a random 32-byte capability locally and submits only its
SHA-256 hash on initiation. Requests made in its role carry the capability in
`X-OpenMates-Pair-Receiver`; it must never be logged. The six-character display
token is a routing identifier, not a decryption key or sufficient authorization.

1. `POST /initiate`: receiver sends `receiver_token_hash`, `session_id`, and an
   optional device hint. Response includes `protocol_version: 2`, display
   `token`, and absolute pairing expiry. No raw PIN or encrypted bundle exists.
2. `GET /info/{token}`: authenticated prospective approver obtains receiver
   display metadata, session ID, and capability hash.
3. `POST /approve/{token}`: authenticated approver reserves the waiting session
   with its account/logical-session identity, display name, and
   `auto_logout_minutes` (null or 30/60/240/480/1440). The approved metadata forms
   the immutable context. The approving client now displays its local PIN.
   Approval requires strong authentication verified on this same logical
   session within five minutes. Ordinary token refresh never renews that proof.
   Otherwise the client obtains fresh password-plus-enrolled-2FA, enrolled OTP
   within its existing authenticated session, or passkey verification; the
   backend enforces proof validity and never receives a plaintext password.
   The current legacy lookup-hash array cannot prove a password credential's
   method. Password-only accounts without an enrolled OTP or usable passkey need
   a safe typed-proof migration before cutover; accepting a caller's password
   label would reintroduce the bypass. This is an unresolved compatibility gate,
   not permission to require those users to enroll a new factor silently.
4. `GET /receiver/{token}` and `GET /authorizer/{token}`: role-authenticated
   polling returns explicit state and only the peer message needed in that
   state. Receiver messages require the capability; authorizer messages require
   the reserving account and logical session. Terminal failure and successful
   completion are distinct.
5. `POST /receiver/{token}/message` accepts `stage: request` then
   `stage: finish`, each with an opaque PAKE `message`. The authenticated
   authorizer's corresponding message endpoint accepts `stage: response`.
   Messages advance state by atomic compare-and-set; replacement, duplicate
   branches, role swaps, and out-of-order messages are rejected. No PIN hash or
   PAKE server registration record is accepted.
6. After verifying the final PAKE proof, the approver creates an independent
   random 32-byte grant secret. The encrypted bundle contains that secret and
   the exported existing account master key, with only the necessary local
   account metadata. `POST /authorize/{token}` carries `encrypted_bundle`,
   `iv`, and `grant_hash` (SHA-256 of the grant secret). The backend records the
   hash bound to the existing receiver, approver, and approved session lifetime.
   It never obtains a reusable password/passkey/recovery lookup credential.
   Before exporting the key, the approver obtains current authenticated account
   metadata from `GET /account-check`, decrypts that account's encrypted email
   with the local master key, and verifies its hash. The bundle contains
   `user_id`, `hashed_email`, `user_email_salt`, and
   `account_context.encrypted_email_with_master_key` so the receiver can make the
   same account/key check and initialize its account state without another login.
7. The receiver downloads and decrypts the bundle, validates the context and
   account identity, then `POST /complete/{token}` with its capability and
   `grant_secret`. The backend atomically consumes that grant and mints an
   ordinary session for the bound account through shared session finalization.
   It returns existing cookie/WS/user response semantics without raw refresh
   tokens in JSON. The public `login_method: pair` bypass is rejected.
   `pair_expires_at` carries the absolute Unix deadline in seconds, or null.
8. The newly minted session remains durably pending and cannot use ordinary
   REST/WebSocket routes. After locally storing its account-key/session state,
   the receiver explicitly acknowledges completion. The server coordinates the
   relay ACK and durable activation; terminal polling reports success only when
   both are confirmed. ACK retries are idempotent for the bound receiver. Failure
   after grant consumption must fail closed and allow a new pairing, never replay
   the consumed grant. A subsequent transient synchronization error does not undo
   an already stored and acknowledged login.

Cancellation is available to the bound approver or receiver and atomically
terminates the exchange. Pairing has an absolute short lifetime. Endpoint-local
state enforces one exchange per PIN even if the relay tries to restart messages.
All temporary crypto state is discarded on failure, cancellation, or completion.
The relay states are `waiting`, `approved`, `request`, `response`, `finish`,
`ready`, `claimed`, `completed`, `acknowledging`, `acknowledged`, `failed`, and `cancelled`.
Only `acknowledged` is successful sender completion; missing/expired state is
not success. PAKE messages are bounded at 16 KiB and ciphertext at 64 KiB.

## Session deadline

The selected numeric lifetime is a server-enforced absolute deadline, carried
through issuer refresh-token rotation and cache rebuilding. Null retains the
ordinary existing session policy. A pair-only durable deadline record is the
backend implementation: one-time shortening of Directus `expires` is
insufficient because refresh resets that field. Both REST and WebSocket entry
points must enforce the deadline, and affected live connections must close.
The CLI/native/web clients also stop using expired paired sessions and remove
local credentials. Ordinary sibling sessions retain their own independent state.
Durable ledger rows also retain pending-ACK, confirmed-ACK, and retired-token
state. Refresh creates a new mapping and retains a retired old-token record;
an old token cannot lose the pairing restrictions after cache eviction. Ordinary
non-paired tokens may cache a verified absence of pair membership briefly; new
pair tokens override that marker before they can be returned to a receiver.

## Review and compatibility

Protocol fields may be refined during implementation without changing these
approved guarantees. Native sender and receiver support, including Watch, must
be addressed before cutting over the shared service. There is no automatic
fallback to the insecure PIN-upload protocol. Independent review must assess
PAKE integration, context binding, client secret lifecycle, and grants; library
audit claims must identify the actual audited version rather than imply that
the new composition has already been audited.
