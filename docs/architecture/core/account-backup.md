---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/services/accountExportService.ts
  - frontend/packages/ui/src/components/settings/account/SettingsExportAccount.svelte
  - frontend/packages/ui/src/components/settings/account/SettingsImportAccount.svelte
  - frontend/packages/ui/src/components/settings/notifications/SettingsBackupReminders.svelte
---

# Account Backup & Export

> GDPR-compliant data export (Article 20) fully implemented. Users can export all account data as a ZIP with YAML/CSV/binary formats, entirely client-side. Import and backup reminders also implemented.

## Why This Exists

- GDPR Article 15 (Right to Access), Article 20 (Data Portability), Article 17 (Right to Erasure -- backup before deletion)
- Users need a way to export their data in a human-readable or machine-readable format

## Current Implementation

**Location:** Account Settings > Export Account / Import Account

### Export (`accountExportService.ts`, `SettingsExportAccount.svelte`)

Processing happens entirely client-side:
1. Fetch manifest (list of all data IDs)
2. Sync missing chats to IndexedDB
3. Load all data from IndexedDB
4. Decrypt encrypted data (email, settings/memories)
5. Download profile image blob
6. Convert to YML/CSV format
7. Create ZIP archive with JSZip
8. Download to client

### Data Categories (User Selectable)

1. **Chats & Messages** -- all chats with message history, including all file embeds (images, audio, PDFs, code, transcripts)
2. **App Settings & Memories** -- per-app configurations and memories (decrypted)
3. **Usage Logs** -- API usage history (YAML + CSV)
4. **Invoice PDFs** -- payment invoices
5. **Account Settings** -- profile info, preferences (decrypted email)
6. **Profile Image** -- user avatar blob

### Import (`SettingsImportAccount.svelte`)

Allows re-importing previously exported data.

### Backup Reminders (`SettingsBackupReminders.svelte`)

Periodic reminders to encourage users to back up their data.

### Planned: Automatic Cloud Backup

Scheduled backups to S3/GCS/Azure/Dropbox/Google Drive/OneDrive/WebDAV/SFTP. Credentials stored client-side only (encrypted in IndexedDB). Not yet implemented.

## Related Docs

- [Delete Account](./delete-account.md) -- users may want to export before deletion
- [Zero-Knowledge Storage](./zero-knowledge-storage.md) -- decryption happens client-side
