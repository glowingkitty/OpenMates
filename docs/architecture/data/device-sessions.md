---
status: active
last_verified: 2026-03-24
key_files:
- backend/core/api/app/routes/auth_routes/auth_session.py
- backend/core/api/app/routes/auth_routes/auth_sessions.py
- backend/core/api/app/utils/device_fingerprint.py
- frontend/packages/ui/src/stores/authLoginLogoutActions.ts
- frontend/packages/ui/src/stores/authSessionActions.ts
claims:
- id: arch-data-device-sessions-behavior
  type: unit
  claim: Device and Session Management is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/packages/ui/src/stores/authLoginLogoutActions.ts
  - frontend/packages/ui/src/stores/authSessionActions.ts
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-data-device-sessions-behavior
  verified: '2026-06-11'
- id: arch-data-device-sessions-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-data-device-sessions-source-1
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/stores/authLoginLogoutActions.ts
- id: arch-data-device-sessions-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-data-device-sessions-source-2
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/stores/authSessionActions.ts
- id: arch-data-device-sessions-manual-3
  type: manual
  reason: 'Tiny architecture note: source-file existence claims cover the implemented anchor surface; deeper behavior remains
    covered by linked canonical docs.'
---

# Device and Session Management

> Current: "Stay Logged In" controls master key persistence and browser session lifetime.

## Why This Exists

Users access OpenMates from personal devices and browser sessions. Session lifetime and key persistence are controlled separately so users can choose between convenience and short-lived local key storage.

## How It Works

### Personal Device Sessions

**Stay Logged In = false (default):**
- Master key stored in memory only.
- Auto-cleared when page/tab closes.

**Stay Logged In = true:**
- Master key stored in IndexedDB as a CryptoKey object.
- Persists across browser sessions via Web Crypto API isolation.

### Session Token Security

- **Storage:** HTTP-only secure cookies.
- **TTL:** 30 days (with "Stay logged in") or 24 hours (default).
- **Refresh:** Automatic background refresh.
- **Revocation:** On user logout or security event.

Each refresh-token chain is one logical session. Its server-only security
metadata—including the last validated country—is stored with that token's
entry in `user_tokens:{user_id}`. Token rotation moves the complete metadata
record to the new token hash. A browser session, CLI session, and native app
session therefore keep independent risk baselines even when they belong to the
same account.

The display metadata shown in Active Sessions is client-encrypted. Replacing
plaintext display fields must preserve server-only security metadata. Targeted
logout and revocation remove only the selected token entry; logout-all remains
the explicit account-wide operation.

### Paired Sessions

Pairing v2 uses a client-to-client PAKE and a receiver-bound one-use login grant.
The API relays PAKE messages and encrypted account-key material; the short PIN,
ephemeral OPAQUE registration, and transfer key stay on the clients. The approving
client must remain active until it verifies the receiver and releases the bundle.
It reports success only after the receiver stores its session/key state and
acknowledges completion.

Every new v2 paired session has a durable record in `pair_session_deadlines`,
indexed by a hash of its refresh token. Pending acknowledgement denies ordinary
REST/WebSocket access. A selected numeric lifetime gives the record an absolute
deadline. Rotation creates a mapping for the replacement token and retires the
previous mapping; losing Redis state cannot remove the deadline. A null lifetime
keeps the ordinary session policy but still requires acknowledgement. Active
WebSocket connections with a numeric deadline close when it is reached.

The approving session needs server-verified strong authentication from the last
five minutes. Refreshing the cookie does not refresh that assurance. The
[implementation contract](../../plans/pairing-pake-hardening/protocol.md) records
wire fields and state transitions; the
[hardening roadmap](../../plans/pairing-pake-hardening/security-roadmap.md)
distinguishes this implementation from wider session and credential repairs.

### Device, Session, and Connection Identity

- A device hash uses stable client characteristics and the user ID; country is
  deliberately excluded.
- Country is a separate, session-local risk signal. A real country change may
  require 2FA or passkey verification for that session only.
- A connection hash combines the stable device hash with a tab/session ID for
  targeted WebSocket delivery.
- Existing location-coupled device hashes are accepted during migration and
  replaced by the stable hash after successful validation.
- A legacy token with no country baseline initializes its own baseline after a
  successful session check; it never copies one from shared account state.

## Threat Mitigations

| Threat               | Mitigation                                          |
|----------------------|-----------------------------------------------------|
| Forget to logout     | Session expiry, explicit logout, and short-lived key storage when Stay Logged In is off |
| Device theft         | Session auto-expires and master key can remain memory-only |
| Pairing interception | Client-only six-character PIN, PAKE peer confirmation, short-lived relay state, and HTTPS |
| Session hijacking    | HTTP-only cookies, auto-expiry, session-local location re-authentication, targeted revocation |

## Related Docs

- [Signup & Auth](../core/signup-and-auth.md) -- authentication flows
- [Encryption Architecture](../core/encryption-architecture.md) -- master key encryption
- [Developer Settings](../infrastructure/developer-settings.md) -- API key management
