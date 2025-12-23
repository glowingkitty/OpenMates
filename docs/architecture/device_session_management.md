# Device and Session Management

OpenMates provides secure device authorization and session management for multiple access scenarios, from personal devices to public computers and developer tools.

## Session Security Models

### Personal Device Sessions

**Current Implementation** (Stay Logged In Toggle):

- **Stay Logged In = false** (default):
  - Master key stored in memory only
  - Auto-cleared when page/tab closes
  - No persistence across browser sessions

- **Stay Logged In = true**:
  - Master key stored in IndexedDB as CryptoKey object
  - Persists across sessions with Web Crypto API isolation
  - Better security than localStorage/sessionStorage

### Public Computer Sessions

**Status**: 🔄 **Planned** - Enhanced security for shared devices

**Planned Security Features**:
- **Public Computer Toggle** (default: ON):
  - Forces memory-only master key storage
  - Auto-deletes IndexedDB on internet disconnection
  - 30-minute automatic logout regardless of activity
  - Cannot use offline mode (data stays server-synced)
  - Visible security indicators in UI

## Device Authorization Methods

### 1. Phone-Based QR Login

**Status**: 🔄 **Planned** - Secure login for public computers using smartphone

#### Security Architecture

```
Phone ----[Auth + Biometric]----> Generate 6-digit code
          (master key protected)
                |
                v
Server  <- [Encrypted Bundle] <- Upload encrypted session
           (6-digit encrypted)
           (server can't decrypt)
                |
                v
Server  <- [6-digit Code] <- Public Computer
           + Session Request
                |
                v
        Decrypt & Login ✅
```

#### Login Flow

**Step 1: Public Computer Requests Access**
1. User selects "Login via phone" on public computer
2. Computer generates unique request token
3. Displays QR code: `https://openmates.org/#phonelogin=abc123def456`
4. Shows "Scan with your phone to login" with polling spinner

**Step 2: Phone Authorization**
1. User scans QR code or clicks link on phone
2. Phone authenticates user (if not already logged in)
3. Phone shows device authorization dialog:
   ```
   Login to Public Device?

   Requesting device: Chrome on Windows 10
   IP Address: 192.168.1.100
   Time: 2:34 PM

   ⚠️ This device will have full access to your account.
   You can logout this device anytime from your phone.

   [Allow]  [Cancel]
   ```

**Step 3: Secure Key Exchange**
1. User taps "Allow" → Phone generates random 6-digit code
2. Phone encrypts login bundle (master key, session data) with code
3. Phone uploads encrypted bundle to server
4. Phone displays: "Enter code on device: 482751 (expires 2 min)"

**Step 4: Public Computer Login**
1. Computer polling detects encrypted bundle ready
2. Computer prompts: "Enter 6-digit code from your phone:"
3. User enters code → Computer downloads and decrypts bundle
4. Computer starts 30-minute session with visible countdown timer

#### Session Management from Phone

**Connected Devices View**:
```
Connected Devices

iPhone 14 Pro (this device)
Last login: Just now

MacBook Pro
Last login: 2 hours ago
[Logout]

Public Computer
Last login: 5 minutes ago ← Auto-logout in 25 min
[Logout]
```

**Remote Logout Security**:
- Biometric confirmation required (Face ID/Touch ID/Fingerprint)
- Rate limiting: Max 1 logout per device per minute, 5 total per 5 minutes
- Immediate session termination and data cleanup on target device

#### Public Computer Security Features

**30-Minute Auto-Logout Timeline**:
```
0:00 - Login successful → Timer starts
       → "Logged in until 2:30 PM" shown in UI

25:00 - Warning displayed
        → "Session expires in 5 minutes"
        → No extension available (public computer mode)

30:00 - Automatic logout
        → IndexedDB cleared
        → Master key removed from memory
        → Redirect to login page
```

**Internet Disconnect Protection**:
- Detects connection loss on public computers
- Immediately clears all cached data and master key
- Shows: "Internet connection lost. Data cleared for security."
- Requires new QR login on connection restore

### 2. Magic Login Links

**Status**: 🔄 **Planned** - For CLI, VSCode extension, and developer tools

#### Use Cases
- **VSCode Extension**: First-time setup and authentication
- **CLI Tools**: `myapp login` command authentication
- **Developer APIs**: Secure API key generation flows

#### Security Flow

**Step 1: Device Requests Authentication**

**VSCode Extension**:
```
Login Required

Click link or scan QR code to authenticate:
https://openmates.org/#pair=abc123def456

[ASCII QR CODE]

Waiting for authentication...
```

**CLI**:
```bash
$ myapp login
To login, visit this link or scan the QR code:

https://openmates.org/#pair=abc123def456

[ASCII QR CODE]

Waiting for authentication...
```

**Step 2: Browser Authorization**
1. User visits pairing URL (click link or scan QR)
2. Browser authenticates user (if needed)
3. Shows device authorization:
   ```
   Authorize device access?

   ⚠️ Warning: Device will have full account access!

   Device: VSCode Extension / CLI
   Platform: Windows/macOS/Linux
   IP: 192.168.1.100
   Time: 2:34 PM

   [Authorize] [Cancel]
   ```

**Step 3: Secure Crypto Exchange**
1. User clicks "Authorize" → Browser generates 6-digit code
2. Browser encrypts crypto bundle with code
3. Browser uploads to server: `POST /api/auth/complete/{request_token}`
4. Browser shows: "Enter this code: 482751 (expires in 2 minutes)"

**Step 4: Device Authentication**
1. Device polling detects bundle ready
2. Device prompts: "Enter 6-digit code from browser:"
3. User enters code → Device downloads and decrypts bundle
4. Device shows "✓ Login successful!" and proceeds

## API Development Security

**Status**: 🔄 **Planned** - Secure API keys for developer access

### API Key Management
- **Client-side generation**: API keys generated using secure random
- **Zero-knowledge storage**: Server stores only SHA256(api_key), never plaintext
- **One-time display**: Keys shown once during creation, must be stored securely
- **Wrapped master keys**: Each API key encrypts master key with Argon2

### Device/IP Authorization
- **Allowlist system**: API keys restricted to approved IPs/device hashes
- **Pending approval**: Unknown IPs blocked, added to pending list
- **User confirmation**: Web UI notification for new device approval
- **Automatic acceptance**: After approval, subsequent requests accepted

### API Key Storage Schema
```yaml
api_keys:
  api_key_hash: string         # SHA256(api_key) for lookup
  wrapped_master_key: string   # Master key encrypted with API key
  argon2_salt: string         # For key derivation
  status: enum                # active, revoked
  allowed_ips: array          # Pre-approved IP addresses
  pending_ips: array          # IPs awaiting user approval
  metadata:
    created_at: timestamp
    last_used: timestamp
    label: string             # User-friendly name
```

## Session Token Security

### Token Lifecycle Management

**Regular Sessions**:
- **Creation**: During successful authentication
- **Storage**: HTTP-only secure cookies
- **TTL**: 7 days (with "Stay logged in") or session-only
- **Refresh**: Automatic background refresh
- **Revocation**: User logout or security event

**Public Computer Sessions**:
- **Creation**: During phone-authorized QR login
- **TTL**: 30 minutes fixed (no refresh)
- **Storage**: HTTP-only cookies, no persistence
- **Cleanup**: Auto-expires with data clearing

### Cross-Device Session Visibility

Users can view and manage all active sessions:
```yaml
session_info:
  device_type: string      # iPhone, MacBook, Public Computer, CLI
  last_login: timestamp    # Most recent activity
  ip_address: string       # Connection source
  status: enum            # active, inactive, expiring_soon
  session_ttl: integer    # Remaining time (public computers only)
```

## Security Threat Mitigations

| Threat | Mitigation |
|--------|------------|
| **User forgets to logout** | 30-min auto-logout + remote logout from phone |
| **Device theft** | Session expires automatically; visible in device list |
| **Network eavesdropping** | 6-digit codes (1M combinations), 2-min TTL, HTTPS only |
| **Phone compromise** | Biometric required for remote logout; rate limited |
| **Session hijacking** | HTTP-only cookies, auto-expiry, encrypted data clearing |
| **QR code reuse** | Unique tokens per request; single-use completion |

## Implementation Checklist

### Backend APIs (Planned)
- [ ] `/api/auth/phone/initiate` - Generate QR code request token
- [ ] `/api/auth/phone/authorize/{token}` - Upload encrypted bundle
- [ ] `/api/auth/phone/poll/{token}` - Check authorization status
- [ ] `/api/devices/list` - Show connected devices
- [ ] `/api/devices/{device_id}/logout` - Remote logout with biometrics
- [ ] `/api/auth/magic/initiate` - Magic link request (CLI/VSCode)
- [ ] `/api/auth/magic/complete/{token}` - Complete magic link auth

### Frontend Components (Planned)
- [ ] QR code display for public computer login
- [ ] 6-digit code input dialog
- [ ] Public computer toggle and security indicators
- [ ] Connected devices management page
- [ ] Remote logout with biometric confirmation
- [ ] Session countdown timer for public computers

### Security Features (Planned)
- [ ] 30-minute auto-logout for public computers
- [ ] IndexedDB deletion on internet disconnect
- [ ] Device authorization confirmation dialogs
- [ ] Rate limiting on remote logout attempts
- [ ] Session token auto-cleanup and revocation

For authentication flows, see [Signup & Login](./signup_login.md).
For encryption implementation, see [Zero-Knowledge Storage](./zero_knowledge_storage.md).