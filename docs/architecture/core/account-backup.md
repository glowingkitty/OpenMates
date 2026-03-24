---
status: planned
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/components/settings/user/SettingsDownloadUserData.svelte
---

# Account Backup & Export

> GDPR-compliant data export allowing users to download their account data. Not yet implemented.

## Why This Exists

- GDPR Article 15 (Right to Access), Article 20 (Data Portability), Article 17 (Right to Erasure -- backup before deletion)
- Users need a way to export their data in a human-readable or machine-readable format

## Planned Design

**Location:** Account Settings -> Data & Privacy -> Download/Backup Account Data

**Placeholder component:** `SettingsDownloadUserData.svelte` (exists but not functional)

### Data Categories (User Selectable)

1. **Chats & Messages** -- all chats with message history, optionally including uploaded files
2. **App Settings & Memories** -- per-app configurations and memories
3. **Usage Logs** -- API usage history, credit consumption, feature usage
4. **Account Settings** -- profile info, preferences, privacy settings (excluding passwords/payment methods)

### Format Options

- **Decrypted (default):** YAML, human-readable, GDPR-compliant
- **Encrypted (optional):** encrypted with user-defined backup key (separate from master key)
- Packaged as ZIP archive

### Backup Methods

- **One-time download:** manual export, client-side generation
- **Automatic cloud backup (planned):** scheduled backups to S3/GCS/Azure/Dropbox/Google Drive/OneDrive/WebDAV/SFTP. Credentials stored client-side only (encrypted in IndexedDB)

## Related Docs

- [Delete Account](./delete-account.md) -- users may want to export before deletion
- [Zero-Knowledge Storage](./zero-knowledge-storage.md) -- decryption happens client-side
