# OpenMates Security Documentation Index

Complete guide to understanding OpenMates security architecture, controls, and threat mitigations.

---

## 🚀 Quick Start (5 minutes)

**New to OpenMates security?** Start here:

1. **[SECURITY_CHECKLIST.md](./SECURITY_CHECKLIST.md)** - What security controls we have and their status ✅
   - Visual summary table of all implemented controls
   - Risk levels per control
   - Test coverage for each

2. **[architecture/security.md](./architecture/security.md)** - How zero-knowledge authentication works 🔐
   - How passwords never reach the server
   - How email stays encrypted
   - How chats stay encrypted

---

## 📋 Complete Security Documentation

### Overview & Risk Assessment

| Document | Purpose | Audience | Read Time |
|---|---|---|---|
| **[SECURITY_CHECKLIST.md](./SECURITY_CHECKLIST.md)** | ✅ Control verification status | Dev leads, security reviewers | 15 min |
| **[SECURITY_CONSIDERATIONS.md](./SECURITY_CONSIDERATIONS.md)** | 🎯 Design decisions & tradeoffs | Architects, security team | 20 min |
| **[THREAT_MODEL_MAPPING.md](./THREAT_MODEL_MAPPING.md)** | 🗺️ OWASP/CWE to code mapping | Security auditors, compliance | 15 min |

### Architecture Details

| Document | Purpose | Code Links | Audience |
|---|---|---|---|
| **[architecture/security.md](./architecture/security.md)** | 🔐 Security overview & principles | Quick reference | All devs |
| **[architecture/zero_knowledge_storage.md](./architecture/zero_knowledge_storage.md)** | 🗄️ Client-side encryption details | `cryptoService.ts`, `db.ts` | Frontend/crypto devs |
| **[architecture/email_privacy.md](./architecture/email_privacy.md)** | 📧 Email encryption & privacy | `encryption.py`, `cryptoService.ts` | Backend/privacy devs |
| **[architecture/device_session_management.md](./architecture/device_session_management.md)** | 📱 Device authorization & sessions | Future implementation | Mobile/session devs |
| **[architecture/signup_login.md](./architecture/signup_login.md)** | 🔑 Signup/login flow details | `auth_login.py`, `Login.svelte` | Frontend/backend devs |
| **[architecture/passkeys.md](./architecture/passkeys.md)** | 🔐 WebAuthn passkey implementation | `auth_passkey.py` | Auth developers |
| **[architecture/sync.md](./architecture/sync.md)** | 🔄 Encrypted sync with security controls | `db.ts`, `cryptoService.ts` | Frontend devs |
| **[architecture/prompt_injection_protection.md](./architecture/prompt_injection_protection.md)** | 🛡️ LLM safety & injection defense | `preprocessor.py` | AI/LLM team |

---

## 🎯 Find by Security Control

### Authentication & Access Control

**Want to understand how login works?**
- Password-based: [SECURITY_CHECKLIST.md#no-plaintext-password-storage](./SECURITY_CHECKLIST.md#-no-plaintext-password-storage)
- 2FA/OTP: [SECURITY_CHECKLIST.md#mandatory-2fa-for-password-logins](./SECURITY_CHECKLIST.md#-mandatory-2fa-for-password-logins)
- Rate limiting: [SECURITY_CHECKLIST.md#rate-limiting-on-login-attempts](./SECURITY_CHECKLIST.md#-rate-limiting-on-login-attempts)
- Device verification: [SECURITY_CHECKLIST.md#device-fingerprinting](./SECURITY_CHECKLIST.md#-device-fingerprinting)

**Code locations**:
- Backend: `backend/core/api/app/routes/auth_routes/auth_login.py`
- Frontend: `frontend/packages/ui/src/components/Login.svelte`

### Encryption & Key Management

**Want to understand how encryption works?**
- Master key generation: [architecture/zero_knowledge_storage.md#master-key-management](./architecture/zero_knowledge_storage.md#master-key-management)
- Chat encryption: [architecture/zero_knowledge_storage.md#chat-encryption](./architecture/zero_knowledge_storage.md#chat-encryption)
- Email encryption: [architecture/email_privacy.md#email-encryption-architecture](./architecture/email_privacy.md#email-encryption-architecture)
- App data encryption: [architecture/zero_knowledge_storage.md#app-settings--memories](./architecture/zero_knowledge_storage.md#app-settings--memories)
- PBKDF2 rationale: [SECURITY_CONSIDERATIONS.md#pbkdf2-iterations-enhancement](./SECURITY_CONSIDERATIONS.md#1-pbkdf2-iterations-enhancement)

**Code locations**:
- Frontend crypto: `frontend/packages/ui/src/services/cryptoService.ts`
- Backend setup: `backend/core/api/app/routes/auth_routes/auth_2fa_setup.py`

### Threat Mitigation

**Want to see how we protect against specific threats?**

| Threat | Mitigation | Documentation |
|---|---|---|
| Server breach exposing passwords | Zero-knowledge lookup hashes | [THREAT_MODEL_MAPPING.md#cwe-256](./THREAT_MODEL_MAPPING.md#cwe-256-plaintext-storage-of-password) |
| Brute force attacks | Rate limiting + 2FA + email verification | [SECURITY_CHECKLIST.md#rate-limiting-on-login-attempts](./SECURITY_CHECKLIST.md#-rate-limiting-on-login-attempts) |
| Token theft via XSS | HTTP-only cookies + SessionStorage only | [SECURITY_CHECKLIST.md#session-token-http-only-cookies](./SECURITY_CHECKLIST.md#-session-token-http-only-cookies) |
| Weak encryption keys | AES-256-GCM + secure random generation | [SECURITY_CHECKLIST.md#aes-256-gcm-for-chat-encryption](./SECURITY_CHECKLIST.md#-aes-256-gcm-for-chat-encryption) |
| Prompt injection attacks | Pre/post-processing LLM analysis | [architecture/prompt_injection_protection.md](./architecture/prompt_injection_protection.md) |
| SQL injection | Parameterized ORM queries | [SECURITY_CHECKLIST.md#parameterized-database-queries](./SECURITY_CHECKLIST.md#-parameterized-database-queries) |

---

## 📊 Security Controls Summary

### Overall Status

```
✅ Implemented: 20/29 controls
🔄 Planned: 9 controls
🟢 Risk Level: LOW
```

### By Category

| Category | Status | Details |
|---|---|---|
| **Authentication** | ✅ 6/8 | Passwords never transmitted, 2FA mandatory, rate limited |
| **Encryption** | ✅ 6/7 | AES-256-GCM, secure random keys, encrypted at rest |
| **Device & Session** | ✅ 3/5 | Device fingerprinting, session TTL, HTTP-only cookies |
| **Infrastructure** | ✅ 1/4 | Parameterized queries (SQL injection protected) |
| **Safety & LLM** | ✅ 2/3 | Prompt injection detection, data minimization |
| **Audit & Compliance** | ✅ 2/2 | Event logging, backup code tracking |

See [SECURITY_CHECKLIST.md](./SECURITY_CHECKLIST.md) for full details.

---

## 🔐 How We Ensure Zero-Knowledge

OpenMates implements zero-knowledge architecture where the server never sees plaintext passwords, emails, or encryption keys.

### Key Principle Diagram

```
User's Device (🔐 Encrypted)     |     Server (🔒 Encrypted Blobs Only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                  │
Password → Derives Hash ───────→ │ Verifies Hash (doesn't know password)
           (stays local)          │

Email → Encrypts ─────────────→ │ Stores encrypted blob (can't read)
        (with salt)              │

Master Key → Encrypts Chats ──→ │ Stores encrypted chats (can't decrypt)
            (stays local)         │
```

**See [architecture/security.md](./architecture/security.md)** for detailed explanation.

---

## 🛣️ Roadmap

### ✅ Completed (October 27, 2025)
- Token logging secured (hash-based)
- Recovery key generation (secure random)
- Zero-knowledge authentication
- 2FA implementation
- Email encryption

### 🔄 Planned (Q4 2025)
- **CSP Headers**: Prevent XSS attacks
- **HSTS Headers**: Prevent downgrade attacks
- **Token revocation**: Immediate logout

### 🔮 Future Enhancements
- **PBKDF2 600k iterations**: Better GPU resistance (post-launch evaluation)
- **Email enumeration mitigation**: Timing-consistent responses
- **Device hash limits**: Max 10 devices per user
- **Progressive OTP backoff**: Exponential failure delays

See [SECURITY_CONSIDERATIONS.md](./SECURITY_CONSIDERATIONS.md) for full roadmap.

---

## 🧪 Testing & Verification

Each security control has test coverage:

- **Authentication tests**: `tests/auth/test_*.py`
- **Crypto tests**: `tests/crypto/test_*.py`
- **Integration tests**: `tests/integration/test_auth_*.py`

To verify controls:
```bash
# Run all security tests
pytest tests/auth tests/crypto -v

# Run specific control verification
pytest tests/auth/test_zero_knowledge_auth.py -v
pytest tests/crypto/test_aes_gcm.py -v
```

---

## 🔍 Finding Code

### By File Type

**Authentication & Sessions**
- Backend: `backend/core/api/app/routes/auth_routes/`
- Frontend: `frontend/packages/ui/src/components/Login.svelte`

**Encryption & Crypto**
- Frontend: `frontend/packages/ui/src/services/cryptoService.ts`
- Backend: `backend/core/api/app/utils/encryption.py`

**Database & Storage**
- Frontend: `frontend/packages/ui/src/services/db.ts` (encrypted IndexedDB)
- Backend: `backend/core/api/app/services/directus/`

**WebSocket & Real-time**
- Backend: `backend/core/api/app/routes/websockets.py`
- Handlers: `backend/core/api/app/routes/handlers/websocket_handlers/`

### By Threat

| Threat | Key Files | Docs |
|---|---|---|
| **Weak passwords** | `cryptoService.ts:83-92` | [SECURITY_CONSIDERATIONS.md#pbkdf2](./SECURITY_CONSIDERATIONS.md#1-pbkdf2-iterations-enhancement) |
| **Token theft** | `auth_login.py:19` | [SECURITY_CHECKLIST.md#token-logging](./SECURITY_CHECKLIST.md#-token-logging-secured) |
| **XSS attacks** | `cryptoService.ts:121-155` | [SECURITY_CONSIDERATIONS.md#master-key-storage](./SECURITY_CONSIDERATIONS.md#2-master-key-storage-architecture) |
| **Brute force** | `auth_login.py:50-51` | [SECURITY_CHECKLIST.md#rate-limiting](./SECURITY_CHECKLIST.md#-rate-limiting-on-login-attempts) |
| **SQL injection** | `app/services/directus/` | [SECURITY_CHECKLIST.md#parameterized-queries](./SECURITY_CHECKLIST.md#-parameterized-database-queries) |

---

## ❓ FAQ

### Q: Can the server see my passwords?
**A**: No. Passwords are never sent to the server. Instead, a hash (lookup_hash) is computed client-side and sent. See [architecture/security.md#zero-knowledge-authentication](./architecture/security.md#zero-knowledge-authentication).

### Q: Can the server see my emails?
**A**: No. Emails are encrypted client-side before being stored. The server only stores the encrypted blob and salt. See [architecture/email_privacy.md#email-encryption-architecture](./architecture/email_privacy.md#email-encryption-architecture).

### Q: Can the server see my chats?
**A**: No. Chats are encrypted with a client-side key. Each chat has its own AES-256-GCM key. See [architecture/zero_knowledge_storage.md#chat-encryption](./architecture/zero_knowledge_storage.md#chat-encryption).

### Q: What if the server is compromised?
**A**: User data remains encrypted (useless without keys). Email addresses are encrypted. Passwords are hashes (only useful if attacker already has plaintext passwords). This is our primary design assumption. See [SECURITY_CHECKLIST.md#assumptions--consequences](./SECURITY_CHECKLIST.md#threat-model-alignment).

### Q: Why only 100k PBKDF2 iterations?
**A**: Combined with 2FA (mandatory), rate limiting (3/min), and email verification, 100k iterations is adequate. We prioritize login speed while maintaining security. See [SECURITY_CONSIDERATIONS.md#pbkdf2](./SECURITY_CONSIDERATIONS.md#1-pbkdf2-iterations-enhancement).

### Q: What's planned next?
**A**: CSP/HSTS headers (Q4), then evaluate PBKDF2 upgrade post-launch. See [SECURITY_CONSIDERATIONS.md#roadmap](./SECURITY_CONSIDERATIONS.md#future-considerations-lower-priority).

---

## 📞 Security Issues

Found a vulnerability? Follow responsible disclosure practices. See **[docs/SECURITY_CONSIDERATIONS.md#contact](./SECURITY_CONSIDERATIONS.md#contact)**.

---

## 📚 References

- [NIST SP 800-63B](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-63b-3.pdf) - Authentication standards
- [OWASP Top 10 2023](https://owasp.org/Top10/) - Web security risks
- [CWE Top 25](https://cwe.mitre.org/top25/) - Common weaknesses
- [RFC 6238](https://tools.ietf.org/html/rfc6238) - TOTP standard

---

## 📖 Document Map

```
docs/
├── SECURITY_INDEX.md ← You are here
├── SECURITY_CHECKLIST.md ← Control verification
├── SECURITY_CONSIDERATIONS.md ← Design decisions
├── THREAT_MODEL_MAPPING.md ← OWASP/CWE mapping
└── architecture/
    ├── security.md ← Security overview & principles
    ├── zero_knowledge_storage.md ← Client-side encryption
    ├── email_privacy.md ← Email encryption & privacy
    ├── device_session_management.md ← Device authorization
    ├── signup_login.md ← Auth flow details
    ├── passkeys.md ← WebAuthn implementation
    ├── sync.md ← Encrypted sync
    └── prompt_injection_protection.md ← LLM safety
```

---

Last Updated: October 27, 2025

