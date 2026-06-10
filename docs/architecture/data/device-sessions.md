---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/stores/authLoginLogoutActions.ts
  - frontend/packages/ui/src/stores/authSessionActions.ts
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

## Threat Mitigations

| Threat               | Mitigation                                          |
|----------------------|-----------------------------------------------------|
| Forget to logout     | Session expiry, explicit logout, and short-lived key storage when Stay Logged In is off |
| Device theft         | Session auto-expires and master key can remain memory-only |
| Network eavesdropping| 6-digit codes (1M combinations), 2-min TTL, HTTPS   |
| Session hijacking    | HTTP-only cookies, auto-expiry, encrypted clearing   |

## Related Docs

- [Signup & Auth](../core/signup-and-auth.md) -- authentication flows
- [Encryption Architecture](../core/encryption-architecture.md) -- master key encryption
- [Developer Settings](../infrastructure/developer-settings.md) -- API key management
