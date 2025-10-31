# Account Data Backup & Export

> Feature not yet implemented

## Overview

Account data backup and export functionality for GDPR compliance and manual backups. Users can download or automatically backup their account data from Account Settings, with granular control over what data is included.

**Location**: Account Settings → Data & Privacy → Download/Backup Account Data

**Implementation Placeholder**: `frontend/packages/ui/src/components/settings/user/SettingsDownloadUserData.svelte`

## Backup Scope

### Data Categories (User Selectable)

Users can individually enable/disable each category:

1. **Chats & Messages** (Default: Enabled)
   - All chats with complete message history
   - Optional: Include uploaded files associated with chats

2. **App Settings & Memories** (Default: Enabled)
   - App-specific settings for all apps
   - Memories associated with apps

3. **Usage Logs** (Default: Enabled)
   - API usage history
   - Credit consumption logs
   - Feature usage statistics

4. **Account Settings** (Default: Enabled)
   - User profile information
   - Preferences (language, dark mode, currency)
   - Privacy settings and consent records
   - and all other account settings (except for sensitive data like passwords, payment methods, etc.)

## Backup Formats

### Encryption Options

- **Decrypted Backup (Default)**: Human-readable format for GDPR compliance and data portability
- **Encrypted Backup (Optional)**: Data encrypted with a custom backup encryption key (user-defined, stored client-side only)

### File Format

- **Primary**: YAML (structured, human-readable)
- **Alternative**: JSON (optional, machine-readable)
- Packaged as ZIP archive for download

## Backup Methods

### One-Time Download

For GDPR data export and manual backups:
1. User selects data categories to include
2. User chooses encryption option
3. System generates backup files (client-side)
4. User downloads ZIP file

### Automatic Cloud Backup

Scheduled backups to cloud storage or FTP servers:
- **Frequency**: Manual, Daily, Weekly, Monthly, or Custom interval
- **Storage Options**:
  - Cloud: AWS S3, Google Cloud Storage, Azure Blob, Dropbox, Google Drive, OneDrive, WebDAV
  - FTP/FTPS/SFTP servers (SFTP recommended)
- **Credentials**: Stored client-side only (encrypted in IndexedDB)

## Security & Privacy

- **Data Encryption**: Encrypted backups use custom backup key (user-defined, separate from master key)
- **Transmission**: All uploads use HTTPS/TLS/SSH encryption

## Implementation

**Frontend:**
- `frontend/packages/ui/src/services/accountBackupService.ts` - Main backup service
- `frontend/packages/ui/src/services/backupStorage/` - Storage provider integrations
- Reuses existing `chatExportService.ts` for chat export functionality


## GDPR Compliance

Fulfills GDPR requirements:
- **Article 15** (Right to Access): Users can download all personal data
- **Article 20** (Data Portability): Structured, portable format
- **Article 17** (Right to Erasure): Users can backup before account deletion

## Related Documentation

- `docs/architecture/chats.md` - Chat export functionality
- `docs/architecture/apps/app_settings_and_memories.md` - App settings structure
- `docs/architecture/security.md` - Security architecture
