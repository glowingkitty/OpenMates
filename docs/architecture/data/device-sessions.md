---
status: partial
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/stores/authLoginLogoutActions.ts
  - frontend/packages/ui/src/stores/authSessionActions.ts
---

# Device and Session Management

> Current: "Stay Logged In" toggle controls master key persistence. Planned: QR phone login for public computers, magic links for CLI/VSCode, and API key device authorization.

## Why This Exists

Users access OpenMates from personal devices, public computers, and developer tools (CLI, VSCode). Each scenario has different security requirements for session lifetime, key storage, and device authorization.

## How It Works

### Implemented: Personal Device Sessions

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

## Planned Features

### Phone-Based QR Login (Public Computers)

1. Public computer displays QR code with unique request token.
2. Phone scans, authenticates user, shows device authorization dialog.
3. Phone generates 6-digit code, encrypts login bundle (master key + session), uploads to server.
4. User enters code on public computer; computer downloads and decrypts bundle.
5. 30-minute fixed session with visible countdown. No refresh, no persistence.

**Security:** Auto-logout at 30 min, IndexedDB cleared on internet disconnect, remote logout from phone with biometric confirmation.

### Magic Login Links (CLI/VSCode/Developer Tools)

Same 6-digit code exchange pattern via browser authorization:
1. Tool displays pairing URL + QR code.
2. User visits URL, authenticates, clicks "Authorize".
3. Browser generates 6-digit code, encrypts crypto bundle, uploads.
4. Tool polls, prompts for code, decrypts bundle.

### API Key Device Authorization

- Client-side key generation, `SHA256(api_key)` stored server-side.
- New IP/device blocked until approved in web UI.
- Wrapped master key per API key (Argon2 derivation).

### Threat Mitigations

| Threat               | Mitigation                                          |
|----------------------|-----------------------------------------------------|
| Forget to logout     | 30-min auto-logout + remote logout from phone       |
| Device theft         | Session auto-expires; visible in device list         |
| Network eavesdropping| 6-digit codes (1M combinations), 2-min TTL, HTTPS   |
| Session hijacking    | HTTP-only cookies, auto-expiry, encrypted clearing   |
| QR code reuse        | Unique tokens per request; single-use completion     |

## Related Docs

- [Signup & Auth](../core/signup-and-auth.md) -- authentication flows
- [Zero-Knowledge Storage](../core/zero-knowledge-storage.md) -- master key encryption
- [Developer Settings](../infrastructure/developer-settings.md) -- API key management
