# Pairing v2 client cryptography

Both OPAQUE roles run on clients. The approving client creates a fresh OPAQUE
server setup and PIN registration for each pairing; neither setup nor
registration record is sent to the API relay. The receiving client runs OPAQUE's
client role. No registration record is persisted after the exchange.

The dependency is pinned to `@serenity-kit/opaque@1.1.0` (MIT; source tag
`ca1cb22f03b9e456159ce367e2975124f87f5ad8`). Its source declares
`opaque-ke` 4.0.0 as a semver dependency and uses the Ristretto255,
TripleDH-SHA512, Argon2id ciphersuite.
The application selects custom Argon2id v0x13 settings of 8192 KiB memory,
three iterations, and one lane to support the Watch client. The 2023 third-party
review predates JS 1.1.0 and core 4.0.0; it does not audit this application
protocol or establish the exact Rust patch version inside the published WASM.
JavaScript immutable strings cannot be guaranteed zeroized; exchange state drops
references on abort, failure, and completion.

The canonical context is the UTF-8 encoding of
`JSON.stringify(["openmates-pair",2,token,session_id,receiver_token_hash,authorizer_user_id,auto_logout_minutes])`.
OPAQUE identifiers are `openmates-pair-v2/client/${context}` and
`openmates-pair-v2/server/${context}`; the OPAQUE user identifier is the context
itself. After verifying the final client proof, the approver derives an AES-256-GCM
key from the 64-byte OPAQUE session key using HKDF-SHA256, SHA-256(context) salt,
and UTF-8 `openmates-pair-v2/bundle` info. The context is AES-GCM associated data.
The IV is 12 random bytes. Wire messages, IV, ciphertext, and 32-byte capability
and grant secrets use unpadded base64url; secret hashes use lowercase SHA-256 hex.
