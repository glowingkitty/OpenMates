# Synthetic session authentication proof

`fixtures/session-auth.json` is separate from the frozen `core.json` fixture.
Its bounded capability is `session.password-totp-rotation.v1`. It exercises the
actual shared Rust `SessionBridge`, npm NAPI `SessionClient`, and Python PyO3
`SessionClient` against loopback transcript servers. No product account,
OpenMates CLI, external HTTP endpoint, or model inference is involved.

The four vectors prove:

- Password-v2 login normalizes email, derives the expected Argon2/HKDF proof and
  email key, and opens the expected wrapped master key. Each attempt generates
  a new UUID and binds its challenge and subsequent refreshes to that UUID.
- A TOTP-required response remains unauthenticated; retry with the supplied
  six-digit OTP succeeds. The fixture records the current canonical legacy
  credential probe after a refused password-v2 attempt. Cookies from the refused
  attempt do not enter the retry. The OTP constant comes from the public RFC6238
  SHA1 key at Unix second59 with period30; the client forwards the supplied OTP,
  rather than generating an authenticator code.
- Three concurrent refresh calls serialize through the native actor, preserving
  the exact rotating refresh-cookie chain and advancing credential revisions.
- A valid cookie rotation survives an invalid JSON response body. A subsequent
  refresh succeeds with that rotated cookie. Remote logout failure still clears
  local credentials; further validation fails locally without an HTTP request.

Every request checks the exact body keys, SDK language identity, explicit Origin,
cookie chain, and absence of Authorization and plaintext password/master/email.
Every exported snapshot checks the expected master key, cookie, WS token, email
hash/key, endpoint and advancing revision. Public errors omit a synthetic private
server diagnostic. All adapters reject a manually mutated expected proof and
return only a generic failure message, without printing the transcript.

The account KDF/AES constants originate in
`packages/openmates-rust/tests/crypto_fixtures/account.json`. The generator
independently computes challenge-bound HMAC proofs using Python's standard
library. `test_session_auth.py` verifies deterministic fixture regeneration,
proof/OTP derivation, and strict rejection of extra fields, wrong references,
and reused session UUIDs. RFC reference: <https://www.rfc-editor.org/rfc/rfc6238>.

Run from the repository workspace:

```sh
node tests/sdk-conformance/runners/session-auth.mjs --fixture tests/sdk-conformance/fixtures/session-auth.json --capability session.password-totp-rotation.v1
python3 tests/sdk-conformance/runners/session-auth.py --fixture tests/sdk-conformance/fixtures/session-auth.json --capability session.password-totp-rotation.v1
cargo run --example session-auth-conformance --manifest-path packages/openmates-session-bindings/Cargo.toml --locked --quiet -- --fixture tests/sdk-conformance/fixtures/session-auth.json --capability session.password-totp-rotation.v1
python3 tests/sdk-conformance/test_session_auth.py
```

The npm/Python commands require their real native bindings to have been built;
missing bindings are failures. These are test adapters, with the same JSON result
contract and exact fixture SHA256 used by the main conformance gate. The gate
owner enables this separately reviewed fixture after the first immutable source
checkpoint; these files do not alter `core.json` or its five existing cases.

This proof does not establish full session parity. Positive password-v1 accounts,
OPAQUE login, signup/device pairing, real authenticator time-window enforcement,
credential-store durability, and complete WS recovery replay remain outside these
four vectors. Existing shared recovery-envelope vectors prove cryptographic
interoperability only. Full session recovery also needs identity-bound discovery,
leases, canonical rereads, persistence acknowledgements and restart/reconnect
fixtures through all three public clients; no equivalence claim follows from
these auth tests.


Owner consistency revision (private candidate; runtime unverified): authenticated
Rust transport computes optional X-OpenMates-Expected-Principal from its retained
canonical owner. It is only a restriction after normal server authentication,
never a bearer/token/API-key credential. The same Rust policy serves real native,
NAPI and PyO3 SessionClient adapters; no new caller setter or language auth logic.
The added transcript keeps intended A when a later received cookie selects B,
requires the owner assertion on protected logout, receives403 before server effect
and preserves explicit local credential clearing. A second added vector returns
the same closed mismatch from session validation, requires the shared expired
category and confirms no current credential snapshot remains in all three adapters. Backend actual-helper tests
separately prove denial before route work. These are synthetic protocol peers,
not real browser cookie or server-security acceptance evidence.

Successful first-party POST/session advertises client_security_capabilities
expected-principal-v1 and ws-dual-principal-v1. A browser Rust client requires
positive support before any WS connection or HTTP business mutation, including
remote logout and durable snapshot preparation. Missing/partial/malformed support
uses existing Unavailable with browser_owner_consistency_unsupported; old servers
silently ignoring a header cannot be accepted as guarded. Explicit native cookie
jars retain old-server compatibility. No native credential snapshot is exported
under browser authority and no browser credential durability ACK is fabricated.

Server WS admission verifies supplied signed query credential even with cookie;
different hashes may pass for same authenticated owner, while wrong owner,
expired/revoked/invalid secondary refuses1008 before accept/effects. Cookie-only
legacy and signed-query-only Safari fallback remain. Existing cookie-selected
session/device/pair restrictions remain mandatory; no WS token is valid for REST.
Legacy callers relying on a stale ignored query must refresh it on reconnect;
owning compatibility evidence remains required before activation. No cookie-domain,
CORS-origin, cipher, storage/keyformat or provider/model routing change.
