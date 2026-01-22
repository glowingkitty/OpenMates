# Security Considerations & Future Improvements

> Last Updated: December 22, 2025
> Status: Research findings and recommendations for future evaluation

This document outlines security analysis findings and recommendations for future consideration. These items represent potential improvements that either:
- Have acceptable tradeoffs for current use cases
- Require architectural decisions before implementation
- Have minimal impact on current security posture

## Quick Links to Related Security Docs

- **[THREAT_MODEL_MAPPING.md](./THREAT_MODEL_MAPPING.md)** - OWASP/CWE risks mapped to code implementations
- **[SECURITY_CHECKLIST.md](./SECURITY_CHECKLIST.md)** - Verification status of all security controls
- **[architecture/security.md](./architecture/security.md)** - Zero-knowledge architecture overview
- **[architecture/prompt_injection_protection.md](./architecture/prompt_injection_protection.md)** - LLM safety strategy

## Risk Assessment Summary

| Category | Completed | Planned | Risk Level |
|---|---|---|---|
| **Authentication** | ✅ 6/8 | 🔄 2 | 🟢 LOW |
| **Encryption** | ✅ 6/7 | 🔄 1 | 🟢 LOW |
| **Device & Session** | ✅ 3/5 | 🔄 2 | 🟢 LOW |
| **Infrastructure** | ✅ 1/4 | 🔄 3 | 🟡 MEDIUM |
| **Overall** | **✅ 20/29** | **🔄 9** | **🟢 LOW** |

**See [SECURITY_CHECKLIST.md](./SECURITY_CHECKLIST.md) for detailed control verification.**

---

## Completed Fixes (October 27, 2025)

### ✅ Token Debug Logging (CRITICAL)
- **Status**: FIXED in `backend/core/api/app/routes/auth_routes/auth_login.py`
- **Change**: Replaced plaintext token logging with hash-based logging
- **Before**: `logger.debug(f"token: {refresh_token[:20]}...")`
- **After**: `logger.debug(f"hash={hashlib.sha256(refresh_token.encode()).hexdigest()[:16]}...")`
- **Impact**: No performance impact, prevents token exposure in logs

### ✅ Recovery Key Generation (HIGH)
- **Status**: FIXED in `frontend/packages/ui/src/services/cryptoService.ts`
- **Change**: Uses `crypto.getRandomValues()` for cryptographically secure randomness
- **Before**: `Math.random()` with weak Fisher-Yates shuffle
- **After**: Secure random bytes with Fisher-Yates shuffle using `crypto.getRandomValues()`
- **Performance Impact**: <1ms additional overhead (occurs once per account creation, not per login)
- **Security Gain**: Recovery key entropy increased from <128 bits to proper cryptographic strength

---

## Future Considerations (Lower Priority)

### 1. PBKDF2 Iterations Enhancement
**File**: `frontend/packages/ui/src/services/cryptoService.ts:83-92`

**Current State**: 100,000 iterations (2010-era standard)
**Recommendation**: 600,000 iterations (2024 NIST standard)

> 🎯 **Why 100,000 PBKDF2 Iterations (Not 600,000)?**
>
> **Option A**: 100,000 iterations (current implementation)
> - ✅ Fast logins (0.2-0.5 seconds)
> - ✅ Good GPU attack resistance (millions of years to crack)
> - ✅ Works seamlessly with 2FA as second factor
> - ✅ Acceptable given defense-in-depth controls
> - Implementation: `cryptoService.ts:83-92`
>
> **Option B**: 600,000 iterations (NIST 2024 standard)
> - ✅ Better GPU resistance (billions of years to crack)
> - ❌ 6-12 second login time
> - ❌ Poor UX on re-authentication
> - ❌ Impacts account recovery flows
>
> **Our Choice**: A + Defense-in-Depth
> - Rate limiting (3 attempts per minute) + 2FA + Email verification
> - Most password attacks target weak password lists first (already covered)
> - Can upgrade differentiated approach later (100k for signup, 600k for re-auth)

**Tradeoff Analysis**:
- ✅ Improved password security against GPU/ASIC attacks
- ❌ 6x slower key derivation (~6-12 seconds on login re-auth scenarios)
- ❌ Impacts UX in login recovery scenarios and 2FA re-entry

**Decision Factors**:
- Current 100,000 iterations provides reasonable protection combined with:
  - Rate limiting (3 login attempts per minute)
  - 2FA as second factor
  - Account lockout mechanisms
  - Email verification for account recovery

**Recommendation**: Implement differentiated approach if feasible:
```typescript
// Signup password step (once per account): 100,000 iterations
const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt);

// Login re-auth scenarios (per attempt): 600,000 iterations
const wrappingKey = await cryptoService.deriveKeyFromPassword(password, salt, 600000);
```

**Effort**: Low (optional parameter) | **Impact**: Medium (UX vs Security)

---

### 2. Master Key Storage Architecture
**Files**:
- `frontend/packages/ui/src/services/cryptoService.ts:121-155` (saveKeyToSession/getKeyFromStorage)
- `frontend/packages/ui/src/stores/authSessionActions.ts:100+` (key persistence)

**Current State**: Master key stored in Base64 in sessionStorage (unencrypted)

**Security Concern**: XSS vulnerability could steal unencrypted key material from storage

> 💡 **Why SessionStorage-Only (Not IndexedDB or localStorage)?**
>
> **Option A**: SessionStorage Only (current)
> - ✅ Key cleared when page closes (no persistent XSS risk)
> - ✅ Must re-derive from password on page reload (prevents stale keys)
> - ✅ Simple, minimal code change
> - ⚠️ Requires re-entering password after page refresh
> - Implementation: `cryptoService.ts:121-155`
>
> **Option B**: IndexedDB with Encryption (future)
> - ✅ Key survives page reloads (better UX)
> - ✅ Key remains encrypted at rest
> - ❌ Adds complexity (double encryption)
> - ❌ Marginal security benefit (persistent XSS rare)
> - Effort: MEDIUM | Impact: LOW
>
> **Option C**: CryptoKey Objects (future)
> - ✅ Key material never exposed as raw bytes
> - ❌ Requires major refactoring (NaCl uses Uint8Array)
> - ❌ High effort, marginal benefit
> - Effort: HIGH | Impact: MEDIUM
>
> **Our Choice**: A + Security Documentation
> - SessionStorage-only is already secure against most XSS scenarios
> - Documenting best practices prevents misuse
> - Can upgrade to B if user feedback indicates re-auth friction

**Enhancement Options**:

#### Option A: SessionStorage Only (Recommended, No Code Change Needed)
- **Current**: Already uses sessionStorage by default
- **Benefit**: Key not persisted across page reloads (must re-derive from password)
- **Status**: ✅ Already secure if `useLocalStorage=false` is enforced
- **Recommendation**: Document that localStorage should never be used for master keys

#### Option B: IndexedDB with Encryption
- **Approach**: Store master key encrypted in IndexedDB
- **Encryption**: Use password-derived key to encrypt stored key
- **Benefit**: Survives page reloads with encrypted persistence
- **Drawback**: Additional complexity, double key derivation
- **Sync Impact**: ✅ Zero - sync.md already handles encrypted IndexedDB storage
- **Effort**: Medium | **Impact**: Low (marginal security improvement)

#### Option C: Web Crypto API CryptoKey Objects
- **Approach**: Use `crypto.subtle.importKey()` with `extractable: false`
- **Benefit**: Key material never exposed as raw bytes
- **Drawback**: Requires refactoring NaCl encryption (uses Uint8Array keys)
- **Effort**: High | **Impact**: Medium

**Recommendation**: Document SessionStorage best practices; defer B and C until key material handling is refactored.

---

### 3. OTP Rate Limiting Enhancement
**File**: `backend/core/api/app/routes/auth_routes/auth_login.py:50-51`

**Current State**: Global 3 attempts per minute limit

**Security Analysis**:
- 6-digit TOTP: 1,000,000 possible values
- At 3/min = 180/hour = 4,320/day
- Brute force: ~231 days without detection
- **Risk Level**: MEDIUM (mitigated by time-window validation)

**Recommended Enhancement**:
```python
# Progressive backoff for OTP failures
OTP_FAILURE_LIMITS = {
    1: (1, 1),      # 1st failure: 1 second delay, 1 attempt remaining
    2: (5, 1),      # 2nd failure: 5 second delay, 1 attempt remaining
    3: (30, 0),     # 3rd failure: 30 second delay, locked out
    4: (300, 0),    # 4th failure: 5 minutes locked
    5: (3600, 0),   # 5th+ failure: 1 hour locked
}
```

**Implementation Steps**:
1. Track OTP failures per user in cache: `otp_failures:{user_id}:{device_hash}`
2. Check failure count on OTP submission
3. Return remaining attempts in response (for UX feedback)
4. Reset counter on successful 2FA or password change

**Effort**: Medium | **Impact**: High | **Priority**: LOW (2FA is already second factor)

---

### 4. Email Enumeration Attack Mitigation
**File**: `backend/core/api/app/routes/auth_routes/auth_login.py:976-985`

**Current State**: Random salt returned for non-existent emails (good), but response timing varies

**Attack Vector**:
- Attacker can correlate timing to identify valid accounts
- Database query time ≠ non-existent user generation time
- Available login methods list is identical for non-existent users

**Recommended Enhancement**:
```python
async def lookup_user(...):
    # Add consistent delay for all non-existent users
    if not exists_result or not user_data:
        delay_seconds = random.uniform(0.1, 0.3)
        await asyncio.sleep(delay_seconds)
        # Rest of response...
```

**Additional**: Ensure response structure identical for existing/non-existing users

**Effort**: Low | **Impact**: Low (existing hashing already prevents most enumeration)

---

### 5. Device Hash Management
**Files**:
- `backend/core/api/app/routes/auth_routes/auth_login.py:829-852`
- `backend/core/api/app/utils/device_fingerprint.py`

**Current State**: Unlimited device hashes can be added per user

**Enhancement Recommendations**:

1. **Device Hash Limit**:
   - Enforce maximum 10 device hashes per user
   - Remove oldest hash when limit exceeded
   - Notify user of old device removal

2. **Device Trust Scoring**:
   - Track device success rate: `successful_logins / total_login_attempts`
   - Flag devices with <80% success rate for additional verification
   - Allow user to revoke untrustworthy devices

3. **Geo-Location Anomaly Detection**:
   - Compare new login location to recent logins
   - If >500km in <2 hours → trigger 2FA re-verification
   - Current geo data available in `auth_login.py:129`

**Effort**: Medium | **Impact**: Medium

---

### 6. Backup Code Security Improvements
**File**: `backend/core/api/app/routes/auth_routes/auth_login.py:592-599`

**Current State**: Backup code format logged partially (`****-****-****`)

**Issues Identified**:
- First 10 characters exposed in logs (format: `1234-5678-****`)
- Inconsistent anonymization logic
- No audit trail of which specific codes were used

**Recommendations**:

1. **Hash Before Logging**:
```python
code_hash = hashlib.sha256(original_code.encode()).hexdigest()[:16]
logger.info(f"Backup code used: {code_hash}")
```

2. **Standardized Format**:
```python
anonymized_code = "****-****-****"  # Always uniform
```

3. **Audit Trail with Hashes**:
```python
compliance_service.log_auth_event(
    event_type="backup_code_used",
    details={
        "code_hash": hashlib.sha256(code.encode()).hexdigest(),
        "codes_remaining": remaining_count
    }
)
```

**Effort**: Low | **Impact**: Low (defense in depth)

---

### 7. Session Cache TTL Consistency
**File**: `backend/core/api/app/routes/auth_routes/auth_login.py:910-934`

**Current State**: Token list cached 7x longer than user cache

**Issue**:
- User cache expires but token list remains valid
- Could create edge cases if token revocation logic added later
- Session fixation risk if cache key collision occurs

**Recommendation**:
```python
# Keep TTL proportional
cache_ttl = cookie_max_age if login_data.stay_logged_in else cache_service.SESSION_TTL
token_list_ttl = cache_ttl * 1.5  # 50% longer for safety, not 7x
```

**Additional**: Implement token revocation endpoint
```python
@router.post("/logout/revoke-token")
async def revoke_token(request: Request, cache_service: CacheService):
    """Explicitly revoke current token from valid tokens list"""
    # Implementation for explicit token revocation
```

**Effort**: Low | **Impact**: Low

---

### 8. Insufficient CSP and Security Headers
**Current State**: No Content-Security-Policy headers documented

**Recommendations**:

1. **Content-Security-Policy**:
```python
# In backend middleware
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "script-src 'self' 'wasm-unsafe-eval'; "  # For WASM if used
    "style-src 'self' 'unsafe-inline'; "  # Review if truly needed
    "img-src 'self' data: https:; "
    "connect-src 'self' wss: https:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
```

2. **HSTS Header**:
```python
response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
```

3. **X-Frame-Options**:
```python
response.headers["X-Frame-Options"] = "DENY"
```

**Effort**: Low | **Impact**: Medium (XSS/clickjacking mitigation)

---

## Security Review Checklist

- [x] Token logging secured (October 27, 2025)
- [x] Recovery key generation cryptographically secure (October 27, 2025)
- [x] PBKDF2 iterations decision (100k + 2FA is adequate; 600k deferred)
- [x] Master key storage decision (SessionStorage-only is adequate)
- [ ] Security headers implementation (CSP, HSTS planned Q4 2025)
- [ ] OTP rate limiting enhancement (3/min sufficient given 2FA)
- [ ] Session TTL consistency (24h/30d implemented; revocation deferred)
- [ ] Device management limits (future enhancement)
- [ ] Email enumeration timing mitigation (future enhancement)

---

## Architectural Notes

### Email Encryption Architecture ✅
The OpenMates email encryption implements a **dual-mode approach** maintaining zero-knowledge compliance:

#### Manual Purchases (Client-Key Mode) ✅
- Server never stores plaintext email
- Server never stores email encryption key
- Key is ephemeral and used only for purchase notifications
- Client provides email decryption key during checkout process

#### Auto Top-up (Server-Key Mode) ✅
**Added December 2025** - For automated server-side operations:
- User provides decrypted email during auto top-up setup
- Server encrypts email using user's vault key (`encrypted_email_auto_topup`)
- Server can decrypt for invoice generation without client interaction
- Maintains zero-knowledge: server uses user's own vault key (not a server key)

**Security Properties Maintained**:
- ✅ Server never stores plaintext email persistently
- ✅ No global server email encryption key
- ✅ User controls both email encryption methods
- ✅ Auto top-up email is user-vault-key encrypted (not server-controlled)
- ✅ Fallback to client-key decryption if vault decryption fails

**Implementation**: `billing_service.py:_get_decrypted_email()` prioritizes `encrypted_email_auto_topup` over `encrypted_email_address`

### Sync Architecture Is Unaffected ✅
All proposed improvements (master key storage, rate limiting, cache TTL) do not break:
- Zero-knowledge properties
- Client-side encryption-first design
- Sync.md phases 1-3 (encrypted cache warming)
- Device-agnostic key management

---

## References

- NIST Special Publication 800-63B: Authentication and Lifecycle Management
- OWASP Top 10 2023: Web Application Security Risks
- OWASP Top 10 for Large Language Models 2023
- CWE-613: Insufficient Session Expiration
- CWE-640: Weak Password Recovery Mechanism for Forgotten Password

---

## Contact

For security concerns or vulnerability reports, follow responsible disclosure practices.
