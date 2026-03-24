---
status: planned
last_verified: 2026-03-24
key_files: []
---

# Developer Settings

> Planned API key management and device authorization for programmatic access via REST API, pip/npm packages, and CLI.

## Why This Exists

Users need secure programmatic access to OpenMates from scripts, CI/CD pipelines, and developer tools. Device confirmation adds a security layer so that even a compromised API key cannot be used from an unauthorized device.

## How It Works (Planned)

### Device Confirmation

When a new device/IP attempts programmatic access:

1. Request is blocked; notification sent to user's web UI.
2. User reviews and approves in Settings > Developer.
3. Subsequent requests from that device/IP are accepted automatically.

**Device identification (GDPR-compliant):**
- REST API: `SHA256(IP_address:user_id)` hash stored for approval.
- CLI/pip/npm: `SHA256(machine_identifier:user_id)` hash (works across VMs/network changes).
- Only anonymized IP (first two octets, e.g., `184.149.xxx`) and region (country/city) stored for display.
- Full IP addresses never stored in plaintext.

### API Keys (Planned)

- **Client-side generation:** Keys generated in user's browser using CSPRNG. Shown once, then only `SHA256(api_key)` stored server-side (zero-knowledge).
- **Key wrapping:** Each API key can decrypt the user's wrapped master key, enabling access to encrypted data.
- **Revocation:** Immediate via Settings > Developer.
- **Scope:** Future enhancement for per-app/skill permissions.

### Access Methods

| Method    | Device ID        | Auth                    |
|-----------|-----------------|-------------------------|
| REST API  | IP hash         | API key in header       |
| pip/npm   | Machine ID hash | API key in config       |
| CLI       | Machine ID hash | API key or magic link   |

All methods require device confirmation for first-time access.

### GDPR Compliance

- Only security-necessary data collected (device hash, anonymized IP, region).
- Device records deletable at any time (right to erasure).
- Access logs retained 30-90 days for abuse prevention.
- Failed access attempts logged separately with limited retention.

## Related Docs

- [CLI Package Architecture](./cli_package.md)
- [Device Sessions](../data/device-sessions.md)
- [Security Architecture](../core/security.md)
