# Developer Settings

Developer settings allow users to manage programmatic access to their OpenMates account via REST API, pip/npm packages, and CLI. These settings ensure secure access control and device management for all developer tools.

## Overview

Developer settings are accessible through `Settings > Developer` and provide:

- **API Key Management**: Create, view, and revoke API keys for programmatic access
- **Device Management**: View and manage approved devices for API/pip/npm/CLI access
- **Access Logs**: Review recent access attempts and device confirmations
- **Security Controls**: Configure IP restrictions and device approval policies

## Device Confirmation

### First-Time Device Access

When a new device or IP address attempts to access your account via REST API, pip/npm package, or CLI for the first time:

1. **Access is blocked**: The request is denied with a notification sent to your account
2. **Confirmation required**: You must explicitly approve the new device/IP in Developer Settings
3. **Approval process**: Once approved, subsequent requests from that device/IP are automatically accepted
4. **Notification**: You receive a notification in the web UI when a new device attempts access

### Device Identification (GDPR-Compliant)

**Data Minimization Principle**: Only the minimum data necessary for security and user identification is collected and stored.

**What is collected (temporarily):**

- **IP Address**: Used to derive approximate geo-location (country/region/city) and for device identification
- **Machine identifier** (for CLI/pip/npm): When available, a device-specific identifier that works across VMs and different network configurations

**What is stored (privacy-preserving):**

- **Device Hash**: A cryptographic hash (SHA256) used to check if a device has been approved
  - For REST API: Hash of `IP_address:user_id` (for security verification)
  - For CLI/pip/npm: Hash of `machine_identifier:user_id` (for security verification)
- **Anonymized IP Address**: Only the first two octets are stored (e.g., `184.149.xxx`) for user identification in the UI
- **Estimated Region**: Country and region information derived from IP address (for user identification)
- **No full IP addresses**: Complete IP addresses are **never stored** in plaintext
- **No geo-coordinates**: Precise location data (latitude/longitude) is **never stored**
- **Minimal metadata**: First access timestamp and last access timestamp

**Privacy-Preserving Approach:**

- Full IP addresses are hashed immediately for security checks
- Only anonymized IP (first two octets) is stored for user identification
- Region information (country/region/city) is stored to help users identify devices
- Users can give devices custom names in Developer Settings for easier management
- The hash cannot be reversed to reveal the original IP address

**Identification Methods by Access Type:**

- **REST API**:
  - Security check: Hash of `IP_address:user_id` (stored for approval verification)
  - User identification: Anonymized IP (e.g., `184.149.xxx`) + region (country/region/city)
- **CLI/pip/npm Package**:
  - Security check: Hash of `machine_identifier:user_id` (stored for approval verification)
  - User identification: Machine identifier info (anonymized if applicable) + region
  - More reliable than IP addresses (works across VMs and network changes)

### Managing Approved Devices

In Developer Settings, you can:

- **View all approved devices**: See list of all approved devices with anonymized IP (e.g., `184.149.xxx`) and region information
- **Name devices**: Give custom names to devices for easier identification (e.g., "Work Laptop", "Home Server")
- **Revoke access**: Immediately revoke access for any device
- **View device details**: See anonymized IP, region (country/region/city), first access time, and last access time
- **Pending approvals**: Review and approve/deny pending device access requests with anonymized IP and region information
- **Delete device records**: Permanently delete device approval records (GDPR right to erasure)

## API Keys

### Purpose and Use Cases

API keys provide programmatic access to OpenMates without requiring full login credentials. They are useful for:

- **Automated integrations**: Scripts and services that need to interact with OpenMates
- **CI/CD pipelines**: Automated workflows that use OpenMates skills
- **Third-party applications**: External tools that integrate with OpenMates

### API Key Security Model

**Status**: ⚠️ **PLANNED** (not yet implemented)

**Planned Implementation**: API keys work in conjunction with device confirmation:

- **API Key + Device Confirmation**: Each API key requires device confirmation for first-time access from new IPs/devices
- **Key Storage**: API keys are hashed client-side (SHA256) before being sent to the server, and only the hash is stored server-side (never stored in plaintext)
- **Encryption**: API keys can decrypt the wrapped master key, allowing access to encrypted user data
- **Revocation**: API keys can be revoked at any time, immediately blocking all access

### API Key vs Device Confirmation

**Question**: If device confirmation is required for all access methods, do regular API keys still make sense?

**Answer**: Yes, API keys still provide value even with device confirmation:

1. **Persistent Authentication**: API keys don't expire like session tokens, making them suitable for long-running services
2. **Multiple Devices**: One API key can be used across multiple approved devices
3. **Granular Control**: Different API keys can have different permissions or be scoped to specific apps/skills
4. **Audit Trail**: API keys provide better audit trails than session-based authentication
5. **Revocation**: API keys can be revoked independently of other authentication methods

**Device confirmation adds an additional security layer** without removing the benefits of API keys. The combination provides:

- **Convenience**: API keys for persistent access
- **Security**: Device confirmation prevents unauthorized access even if an API key is compromised
- **Flexibility**: Users can approve multiple devices for the same API key

### Creating and Managing API Keys

**Status**: ⚠️ **PLANNED** (not yet implemented)

**Planned Features:**

- **Create API Key**: Generate new API keys client-side with optional labels/names
- **Multiple Keys**: Users can create and name multiple API keys for different purposes
- **View Keys**: See all active API keys with name, creation date, last used date, and associated devices
- **Revoke Keys**: Immediately revoke API keys to block all access
- **Key Permissions**: Scope API keys to specific apps or skills (future enhancement)
- **Usage Statistics**: View usage statistics per API key

### API Key Generation (Client-Side)

**Security Best Practice**: API keys are generated **client-side** for maximum security:

- **Client-side generation**: API keys are generated in the user's browser/CLI using cryptographically secure random number generation
- **One-time display**: The plaintext API key is shown **only once** during creation
- **User responsibility**: Users must securely store the API key themselves (the server cannot retrieve it)
- **Server receives hash only**: Only the hash of the API key (`SHA256(api_key)`) is uploaded to the server
- **Zero-knowledge**: The server never sees the plaintext API key, even during creation

**User Experience:**

1. User clicks "Create API Key" in Developer Settings
2. User provides a name/label for the key (e.g., "Production Server", "CI/CD Pipeline")
3. Client generates a cryptographically secure random API key
4. **Warning displayed**: "⚠️ This API key will only be shown once. Please copy and store it securely."
5. Plaintext key is displayed for the user to copy
6. User confirms they've copied the key
7. Client hashes the key and uploads only the hash to the server
8. Plaintext key is discarded from client memory

### API Key Storage

- **Server-side**: Only the hash of the API key is stored (`SHA256(api_key)`)
- **Client-side**: API keys must be stored securely by the user (environment variables, secret managers, etc.)
- **Never in version control**: API keys should never be committed to git repositories
- **Encryption**: API keys can decrypt wrapped master keys, allowing access to encrypted data
- **Cannot be retrieved**: If a user loses their API key, they must generate a new one (the server cannot provide the original)

## Access Methods

All developer access methods (REST API, pip/npm package, CLI) require device confirmation:

### REST API

- **First access**: New IP addresses must be approved in Developer Settings
- **Subsequent access**: Approved IPs can access the API without additional confirmation
- **Authentication**: Uses API keys in request headers

### pip/npm Package

- **First access**: New devices/IPs must be approved
- **Machine identifier**: Uses more reliable device identification (works across VMs)
- **Authentication**: Uses API keys stored in package configuration

### CLI

- **First access**: New devices/IPs must be approved
- **Machine identifier**: Uses reliable device identification
- **Authentication**: Uses API keys or magic link authentication (see [CLI Package Architecture](./cli_package.md))

## GDPR Compliance and Privacy

### Data Collection and Storage

**Minimal Data Collection:**

- Only data necessary for security (device identification and access control) is collected
- No personal data beyond what's required for security purposes
- Full IP addresses are never stored in plaintext; only anonymized IPs (first two octets) are stored
- IP addresses are immediately hashed for security checks; the hash cannot be reversed

**Data Retention:**

- **Device approval records**: Retained until you revoke access or delete your account
- **Access logs**: Limited retention period for security monitoring (typically 30-90 days)
- **Failed access attempts**: Logged separately with limited retention for abuse prevention
- **You can delete**: Device records can be deleted at any time through Developer Settings

**Your Rights (GDPR):**

- **Right to access**: View all stored device records and access logs
- **Right to erasure**: Delete device approval records at any time
- **Right to data portability**: Export your device approval data
- **Right to object**: Revoke device access without affecting other account features

### Security Logging

**Limited IP Logging** (for security only):

- IP addresses associated with **failed** access attempts may be logged separately
- Logged IPs have **limited retention periods** (typically 30-90 days)
- Used only for security monitoring and abuse prevention
- Not linked to device approval records

**Compliance Events:**

- Certain security events (e.g., successful device verifications) may be logged with IP for audit purposes
- These logs have limited retention and are used only for security/compliance
- You can request access to these logs through Developer Settings

## Security Considerations

### Device Confirmation Benefits

- **Prevents unauthorized access**: Even if credentials are compromised, new devices must be approved
- **User awareness**: Users are notified of all new access attempts
- **Granular control**: Users can revoke access for specific devices without affecting others
- **Privacy-preserving**: Only hashed identifiers are stored, not raw personal data

## Related Documentation

- [CLI Package Architecture](./cli_package.md) - CLI and SDK access methods
- [REST API Architecture](./rest-api.md) - REST API endpoints and authentication
- [Security Architecture](./security.md) - Overall security model and encryption
