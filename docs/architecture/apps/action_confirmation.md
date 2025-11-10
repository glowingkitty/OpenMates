# Action Confirmation Architecture

This document describes how write and sensitive operations are secured through action confirmation, with different security models for web app (chatbot) and programmatic access (REST API, CLI, pip/npm package).

## Overview

OpenMates implements different security models based on the access method:

- **Web App (Chatbot Interface)**: Always requires user confirmation for write/sensitive app skills
- **REST API / CLI / Pip/Npm Package**: No confirmation required, but protected through multiple security layers

## Web App (Chatbot Interface)

### Autonomous Mode

**Location**: Settings header (toggle in the main Settings interface header)

**How it works**:

- **Default**: Disabled (confirmation required for write/sensitive skills)
- **When Enabled**: Auto-confirms all app skills (including write skills) without user confirmation
- **Per-Skill Override**: Users can still require confirmation for specific skills even when Autonomous Mode is enabled
  - Settings Location: `Settings > App Store > [App Name] > [Skill Name] > Always Require Confirmation`
  - When enabled for a skill: That skill always requires confirmation, even in Autonomous Mode
- **Use Case**: Power users who want faster workflows while maintaining granular control

**Security Considerations**:

- All auto-confirmed actions are still logged (see [Privacy-Compliant Logging](#3-privacy-compliant-logging) section below)
- Users can review app skill history in usage Settings
- Can be disabled instantly at any time
- Per-skill overrides provide safety net for critical operations

### Confirmation Flow

When a user requests a write or sensitive action through the chatbot:

1. **Action Classification**: Server checks if the app skill requires confirmation
   - **Check Autonomous Mode**: If Autonomous Mode is enabled, skip to execution (unless skill has "Always Require Confirmation" override)
   - **Check Per-Skill Override**: If skill has "Always Require Confirmation" enabled, queue for approval regardless of Autonomous Mode
   - **Skills requiring confirmation**: Queue for user approval (e.g., send email, create calendar event, delete file)
   - **Skills not requiring confirmation**: Execute immediately (e.g., read-only operations, low-risk actions)

2. **Queue App Skill**: Server creates a pending app skill record
   - Generate unique `app_skill_id` and confirmation token
   - Set expiration (e.g., 5 minutes default)
   - Store app skill details (encrypted if sensitive)

3. **Notify User**: Server sends WebSocket message to all user's connected devices

   ```json
   {
     "type": "app_skill_confirmation_required",
     "payload": {
       "app_skill_id": "uuid",
       "action_type": "send_email" | "delete_file" | "create_calendar_event",
       "skill_id": "email.send",
       "app_id": "email",
       "description": "Send email to john@example.com",
       "details": {...},
       "expires_at": "2024-01-01T12:05:00Z",
       "confirmation_token": "secure_token"
     }
   }
   ```

4. **User Confirmation**: App skill appears in chat interface with confirmation UI

   - **Embedded Preview UI**: App skills requiring confirmation appear as part of the embedded preview UI system, in the same location where app skill calls are typically displayed
   - **Fullscreen Mode**: Confirmation UI is also available when embedded previews are opened in fullscreen mode
   - **Visual Distinction**: App skills requiring confirmation are clearly marked and easy to identify (e.g., highlighted border, confirmation badge)
   - **Confirmation Options**:
     - **Individual approval**: Approve/reject each app skill one by one directly in the embedded preview UI (maximum control)
     - **Group approval**: Easily approve all pending app skills in a group at once (faster workflow)
     - App skills are grouped visually when multiple require confirmation
   - User sends confirmation via WebSocket:

   ```json
   {
     "type": "app_skill_confirmation_response",
     "payload": {
       "app_skill_id": "uuid" | ["uuid1", "uuid2", ...],  // Single or array for group approval
       "confirmation_token": "secure_token",
       "decision": "approve" | "reject",
       "group_mode": false  // true if approving multiple app skills in a group
     }
   }
   ```

   **Group Approval Flow**:
   - Multiple app skills requiring confirmation are visually grouped in the chat
   - "Approve All" button appears for grouped app skills
   - User can approve the entire group with one click
   - Each app skill is still validated individually with its confirmation token

5. **App Skill Execution**: Server validates confirmation and executes
   - If approved: Execute app skill, send completion notification
   - If rejected: Cancel app skill, notify user
   - If expired: Cancel app skill, notify user of expiration

### App Skill Confirmation Settings

Each app skill has a default confirmation requirement setting:

- **Default Settings**: Defined per skill in the app's configuration
- **User Override**: Users can change confirmation requirements in App Store settings
  - Per-app settings: Enable/disable confirmation for all skills in an app
  - Per-skill settings: Enable/disable confirmation for specific skills
- **Settings Location**: `Settings > App Store > [App Name] > [Skill Name] > Confirmation Settings`

**Example Settings:**

- Email app: `send_email` skill requires confirmation by default
- Calendar app: `create_event` skill requires confirmation by default
- Web app: `search` skill does not require confirmation (read-only)

### Offline Handling

- **User Offline**: App skills remain queued until user comes online
- **Default Timeout**: App skills expire after 30 minutes (configurable per skill)
- **Notification on Reconnect**: When user reconnects, pending app skills are re-notified
- **App Skill History**: Users can view pending/expired app skills in Settings

### Security Features

- **Confirmation Token**: Cryptographically secure token prevents replay attacks
- **App Skill Signing**: App skill details are signed to prevent tampering
- **Rate Limiting**: Limit number of pending app skills per user
- **Privacy-Compliant Logging**: Minimal logging by default, with optional enhanced logging (see [Privacy-Compliant Logging](#3-privacy-compliant-logging) section below)

## REST API / CLI / Pip/Npm Package

### No Confirmation Required

For programmatic access, **no confirmation is required** to maintain usability for automation and scripts. Security is provided through multiple layers:

### Security Layers

#### 1. API Key Scopes/Permissions

- API keys can be scoped to specific apps/skills
- Example: Key with `email.send` scope can only send emails
- Users can create restricted keys for specific use cases
- Limits damage if a key is compromised

#### 2. Rate Limiting

- Write actions are rate-limited (e.g., 10 writes/minute per API key)
- Prevents abuse and bulk unauthorized actions
- Different limits for different action types
- Rate limits are tracked per provider, per skill, and per model

#### 3. Privacy-Compliant Logging

**Default (Minimal Logging)**:

- Only essential metadata is logged for privacy and GDPR compliance
- Includes: app skill identifier (e.g., `email.send`), timestamp, API key identifier (hash), status (success/failure)
- **No sensitive data**: Parameters, IP addresses, and device hashes are not logged by default
- Users can review minimal app skill history in Settings (web app) or Developer Settings (API/CLI)

**GDPR Compliance**:

- Data minimization: Only collect what's necessary
- Right to deletion: Users can delete their action history
- Transparency: Clear indication of what is logged at each level

#### 4. Device Confirmation

- New devices must be approved before API access
- Prevents unauthorized device access even with valid API key
- See [Developer Settings](../developer_settings.md) for details

#### 5. Optional Enhanced Security Mode

- Users can enable "Require confirmation for all API actions" in Developer Settings
- When enabled, API write actions queue for WebSocket confirmation (same as web app)
- Default: No confirmation required (for programmatic usability)
- Useful for highly sensitive accounts or compliance requirements

### API Key Management

- **Scoped Keys**: Create API keys with limited permissions
- **Key Rotation**: Regularly rotate API keys for enhanced security
- **Key Revocation**: Immediately revoke compromised keys
- **Usage Monitoring**: View all API key usage in Developer Settings

## App Skill Confirmation Requirements

### Skills Requiring Confirmation (Web App)

- **Default**: Defined per skill in app configuration
- **User Override**: Can be changed in App Store settings
- **Web App**: Requires confirmation via WebSocket before execution
- **API/CLI**: No confirmation required, but protected by scopes, rate limiting, and logging
- Examples: Sending emails, creating calendar events, deleting files, updating files

### Skills Not Requiring Confirmation

- **Default**: Defined per skill in app configuration
- **User Override**: Can be changed in App Store settings
- **Web App & API/CLI**: Execute immediately without confirmation
- Examples: Reading calendar events, fetching Figma files, reading emails, searching web, getting video transcripts

## Implementation Details

### Pending App Skill Storage

- App skills stored in Redis/Dragonfly with TTL
- Key format: `pending_app_skill:{user_id}:{app_skill_id}`
- Includes: app skill type, details, status, created_at, expires_at, confirmation_token

### WebSocket Integration

- Uses existing WebSocket infrastructure
- Messages broadcast to all user's connected devices
- Confirmation can come from any connected device

### App Skill History

- All app skills (confirmed, rejected, expired, auto-confirmed) stored in app skill history
- **Web App**: Accessible via Settings (user-friendly interface)
- **API/CLI**: Accessible via Developer Settings (developer-focused interface)
- Details included depend on logging level (minimal by default, enhanced if user opts in)

## User Experience

### Web App

- **Embedded Preview UI**: App skills requiring confirmation appear as part of the embedded preview UI system, where app skill calls are typically displayed
- **Fullscreen Mode**: Confirmation UI is available in both embedded and fullscreen preview modes
- **Visual Grouping**: Multiple app skills requiring confirmation are visually grouped together for easy identification
- **Quick Actions**: Approve/reject buttons appear directly on each app skill preview card
- **Group Approval**: Users can approve all app skills in a group with a single "Approve All" action
- **Individual Control**: Users can still approve/reject each app skill individually for maximum control
- **Autonomous Mode**: Toggle in Settings header to auto-confirm all app skills (with per-skill overrides)
- **App Skill History**: View past confirmations and auto-confirmed app skills in usage Settings

### REST API

- **Immediate Execution**: Write app skills execute immediately (no confirmation)
- **Error Responses**: Clear error messages if rate limited or unauthorized
- **App Skill Logging**: All app skills visible in Developer Settings (minimal logging by default, enhanced logging opt-in)
- **Optional Confirmation**: Can enable confirmation mode if desired
- **Optional Enhanced Logging**: Users can opt-in to enhanced logging for detailed audit trails

## Security vs. Usability Trade-off

### Web App Security Model

- Security through confirmation (user is present and actively using the interface)
- Real-time approval workflow
- Prevents accidental or unauthorized actions

### API/CLI Security Model

- Usability for programmatic access (no confirmation blocking automation)
- Security through multiple layers: scopes, rate limiting, logging, device management
- Users can opt-in to confirmation if desired

## Related Documentation

- [App Settings and Memories](./app_settings_and_memories.md) - Connected accounts and token storage
- [REST API Architecture](../rest_api.md) - API endpoints and authentication
- [Developer Settings](../developer_settings.md) - API key management and device confirmation
- [App Skills Architecture](./app_skills.md) - How app skills work
