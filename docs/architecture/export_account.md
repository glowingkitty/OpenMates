# Account Data Export Architecture

> GDPR-compliant data portability implementation with client-side processing

**Status**: ✅ Implemented

## Overview

This document describes the architecture for user account data export, implementing the GDPR "right to data portability" (Article 20). Users can request and download all their personal data in a structured, commonly used, and machine-readable format.

**Key Design Principles:**
- **Client-side processing**: All decryption and ZIP creation happens in the browser
- **YML format**: Consistent with existing chat export functionality
- **Invoice PDFs included**: All invoice PDFs are downloaded and included in the export
- **Reuse existing patterns**: Leverages `chatExportService.ts` patterns
- **No server storage**: Direct download to client (no S3 intermediate storage)
- **Efficient & user-friendly**: Progress indicators, batch processing

**Implementation Files:**
- Backend: `backend/core/api/app/routes/settings.py` (endpoints)
- Frontend Service: `frontend/packages/ui/src/services/accountExportService.ts`
- Frontend Component: `frontend/packages/ui/src/components/settings/account/SettingsExportAccount.svelte`
- Translations: `frontend/packages/ui/src/i18n/sources/settings/account.yml`

## GDPR Compliance Requirements

### Article 20 - Right to Data Portability

The implementation must satisfy:
1. **Machine-readable format**: Data exported in structured YML format
2. **Commonly used format**: YML/YAML with clear schema documentation
3. **Timely delivery**: Export completes within minutes (client-side processing)
4. **Free of charge**: No limits on export frequency (client processes data)
5. **Complete data**: All personal data the user has provided or generated

### Data Categories

Per GDPR, we export:
- **Provided data**: Information the user directly provided (email, settings, preferences)
- **Observed data**: Data collected about user behavior (usage statistics, message metadata)
- **Derived data**: Data computed from user activity (credit balances, summaries)

## User Flow

### 1. Export Request

**Location**: Settings → Account → Export My Data

**Display Information**:
- Explanation of what data will be exported
- Estimated export time based on chat count
- Format information (ZIP archive with YML files)
- Progress indicator during export

### 2. Authentication Requirement

**Before initiating export**:
- User must re-authenticate (passkey or 2FA OTP)
- This prevents unauthorized data access
- Same authentication flow as account deletion

### 3. Client-Side Export Processing

**After authentication, processing happens entirely on client**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Client-Side Export Flow                       │
├─────────────────────────────────────────────────────────────────┤
│  1. Authenticate user (passkey/2FA)                              │
│  2. Request export manifest from server (list of all data IDs)   │
│  3. Sync all chats to IndexedDB (batch processing)               │
│  4. Load all data from IndexedDB                                 │
│  5. Decrypt all encrypted data with master key                   │
│  6. Convert to YML format                                        │
│  7. Create ZIP archive using JSZip                               │
│  8. Trigger browser download                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 4. Download

**When export is ready**:
- Browser triggers automatic download
- ZIP archive contains all user data in YML format
- No server-side storage required

## Exported Data Structure

### Archive Contents

```
openmates_export_{username}_{timestamp}.zip
├── README.md                       # Export documentation and schema
├── metadata.yml                    # Export metadata
├── profile.yml                     # User profile and account info
├── compliance_logs.yml             # Consent history (privacy policy, terms of service)
├── chats/
│   └── {chat_title}_{date}/        # One folder per chat
│       ├── {chat_title}.yml        # Chat metadata and messages
│       ├── {chat_title}.md         # Markdown format
│       └── code/                   # Code embeds (if any)
├── usage/
│   └── usage_history.yml           # Usage records with credits, models, tokens
├── payments/
│   ├── invoices.yml                # Invoice history metadata
│   └── invoice_pdfs/               # All invoice PDF files
│       ├── Invoice_2024_01_15.pdf
│       ├── Invoice_2024_02_20.pdf
│       └── ...                     # One PDF per invoice
└── settings/
    └── app_settings.yml            # Per-app settings and memories
```

### Data Schemas (YML Format)

#### profile.yml

```yaml
# User Profile
export_schema_version: "1.0"
user_id: "d389df57-1f2b-4766-8457-8630081379e8"
username: "johndoe"
email: "user@example.com"
email_verified: true                    # Always true - email verification is required for account creation

account:
  status: "active"                      # Directus user status (active, draft, suspended, etc.)
  last_access: "2024-12-30T10:00:00Z"   # Last authentication

security:
  tfa_enabled: true                     # 2FA (TOTP) enabled
  has_passkey: true                     # Passkey registered
  passkey_count: 2                      # Number of passkeys

preferences:
  language: "en"                        # User's language preference
  darkmode: true                        # Dark mode enabled
  currency: "eur"                       # Preferred currency

credits:
  current_balance: 50000                # Current credit balance

auto_topup:
  enabled: false                        # If false, threshold/amount not shown

# Note: Consent history (privacy policy, terms of service) is in compliance_logs.yml
```

#### compliance_logs.yml

```yaml
# Compliance Logs - Consent History
export_schema_version: "1.0"

# This file contains your consent history for GDPR compliance.
# Privacy policy and terms of service consent are recorded when you create your account
# and whenever you accept updated versions.

current_consent_status:
  privacy_policy:
    accepted: true
    timestamp: "2024-01-01T00:00:00Z"
    action: "granted"
  terms_of_service:
    accepted: true
    timestamp: "2024-01-01T00:00:00Z"
    action: "granted"

consent_history:
  - timestamp: "2024-01-01T00:00:00Z"
    consent_type: "privacy_policy"
    action: "granted"
    status: "success"
  - timestamp: "2024-01-01T00:00:00Z"
    consent_type: "terms_of_service"
    action: "granted"
    status: "success"
  - timestamp: "2024-06-15T10:00:00Z"
    consent_type: "withdrawal_waiver"
    action: "granted"
    status: "success"

other_events:
  - timestamp: "2024-01-01T00:00:00Z"
    event_type: "user_creation"
    status: "success"
```

#### Chat Export (Reuses Existing Format)

The chat export reuses the existing `convertChatToYaml()` function from `chatExportService.ts` and `downloadChatsAsZip()` from `zipExportService.ts`. Each chat folder contains:

- **{chat_title}.yml**: Full chat data with metadata and messages
- **{chat_title}.md**: Markdown rendering of conversation
- **code/**: Code embed files with original paths
- **transcripts/**: Video transcript markdown files

#### app_settings.yml

```yaml
export_schema_version: "1.0"
settings_by_app:
  chat:
    default_model: "gpt-4"
    temperature: 0.7
    custom_system_prompt: "You are a helpful assistant..."
  code:
    default_language: "python"
    auto_complete: true
  # ... other apps
```

#### memories.yml

```yaml
export_schema_version: "1.0"
memories:
  - memory_id: "uuid"
    created_at: "2024-01-01T00:00:00Z"
    updated_at: "2024-06-15T10:00:00Z"
    app_id: "chat"
    item_key: "user_preference_1"
    content: "User prefers concise responses"
    
  - memory_id: "uuid"
    created_at: "2024-02-01T00:00:00Z"
    updated_at: "2024-02-01T00:00:00Z"
    app_id: "code"
    item_key: "coding_style"
    content: "User prefers TypeScript over JavaScript"
```

#### usage_history.yml

```yaml
export_schema_version: "1.0"
total_records: 1000
date_range:
  from: "2024-01-01T00:00:00Z"
  to: "2024-12-30T10:00:00Z"
  
usage_records:
  - usage_id: "uuid"
    timestamp: "2024-01-01T00:00:00Z"
    type: "chat"  # chat|api|embed
    model: "gpt-4"
    tokens_input: 100
    tokens_output: 500
    credits_used: 50
    chat_id: "uuid"
    
  # ... more records
```

#### invoices.yml

```yaml
export_schema_version: "1.0"
invoices:
  - invoice_id: "uuid"
    order_id: "order_123"
    date: "2024-01-15T10:00:00Z"
    amount_cents: 2000
    currency: "EUR"
    credits_purchased: 50000
    payment_method: "card ending 4242"
    status: "paid"  # paid|refunded|pending
    refund_details: null  # or object with refund info
```

#### metadata.yml

```yaml
export_version: "1.0"
export_timestamp: "2024-12-30T10:00:00Z"
user_id: "uuid"
export_id: "uuid"

data_range:
  from: "2024-01-01T00:00:00Z"
  to: "2024-12-30T10:00:00Z"

statistics:
  total_chats: 150
  total_messages: 5000
  total_embeds: 200
  total_usage_records: 1000

file_checksums:
  profile.yml: "sha256:abc123..."
  chats/chat_uuid/chat.yml: "sha256:def456..."
  # ...

gdpr_compliance:
  article_20_satisfied: true
  data_categories_included:
    - provided_data
    - observed_data
    - derived_data
```

## Implementation Details

### Backend API Endpoints

#### GET `/v1/settings/export-account-manifest`

**Purpose**: Get list of all data IDs the user has (for client to sync/fetch).

**Authentication**: Required (cookie-based session)

**Rate Limit**: 10/minute

**Response**:
```json
{
  "success": true,
  "manifest": {
    "all_chat_ids": ["uuid1", "uuid2", "..."],
    "total_chats": 150,
    "total_invoices": 5,
    "total_usage_entries": 1000,
    "has_app_settings": true,
    "has_memories": true,
    "has_usage_data": true,
    "has_invoices": true,
    "estimated_size_mb": 25.5
  }
}
```

**Note**: This endpoint returns IDs only, not content. Client uses this to:
1. Compare with IndexedDB to identify missing chats
2. Trigger sync for missing chats
3. Show progress to user

#### GET `/v1/settings/export-account-data`

**Purpose**: Get data that's not already in IndexedDB (usage, invoices, profile).

**Authentication**: Required (cookie-based session)

**Rate Limit**: 5/minute (heavier processing)

**Query Parameters**:
- `include_usage`: boolean (default: true)
- `include_invoices`: boolean (default: true)

**Response**:
```json
{
  "success": true,
  "data": {
    "usage_records": [
      {
        "usage_id": "uuid",
        "timestamp": 1704067200,
        "app_id": "chat",
        "skill_id": "ai_ask",
        "usage_type": "skill_execution",
        "source": "chat",
        "credits_charged": 50,
        "model_used": "gpt-4",
        "chat_id": "uuid",
        "actual_input_tokens": 100,
        "actual_output_tokens": 500
      }
    ],
    "invoices": [
      {
        "invoice_id": "uuid",
        "order_id": "order_123",
        "date": "2024-01-15T10:00:00Z",
        "amount_cents": 2000,
        "currency": "eur",
        "credits_purchased": 50000,
        "is_gift_card": false,
        "refund_status": "none"
      }
    ],
    "invoice_ids_for_pdf_download": ["uuid1", "uuid2"],
    "user_profile": {
      "user_id": "uuid",
      "username": "johndoe",
      "encrypted_email_with_master_key": "...",
      "email_verified": true,
      "account_status": "active",
      "last_access": "2024-12-30T10:00:00Z",
      "language": "en",
      "darkmode": true,
      "currency": "eur",
      "credits": 50000,
      "tfa_enabled": true,
      "has_passkey": true,
      "passkey_count": 2,
      "auto_topup_enabled": false
    },
    "app_settings_memories": [...],
    "compliance_logs": [
      {
        "timestamp": "2024-01-01T00:00:00Z",
        "event_type": "consent",
        "user_id": "uuid",
        "consent_type": "privacy_policy",
        "action": "granted",
        "status": "success"
      },
      {
        "timestamp": "2024-01-01T00:00:00Z",
        "event_type": "consent",
        "user_id": "uuid",
        "consent_type": "terms_of_service",
        "action": "granted",
        "status": "success"
      },
      {
        "timestamp": "2024-01-01T00:00:00Z",
        "event_type": "user_creation",
        "user_id": "uuid",
        "status": "success"
      }
    ]
  }
}
```

#### Invoice PDF Download

Invoice PDFs are downloaded via the existing endpoint:

**GET `/v1/payments/invoices/{invoice_id}/download`**

The export service downloads all invoice PDFs in batches and includes them in the ZIP archive.

### Frontend Export Service

**Location**: `frontend/packages/ui/src/services/accountExportService.ts`

```typescript
/**
 * Account Export Service
 * 
 * Handles GDPR-compliant export of all user data.
 * Processing happens entirely on the client:
 * 1. Fetch manifest (list of all data IDs)
 * 2. Sync missing chats to IndexedDB
 * 3. Load all data from IndexedDB
 * 4. Decrypt encrypted data
 * 5. Convert to YML format
 * 6. Create ZIP archive
 * 7. Trigger download
 */

export interface ExportProgress {
  phase: 'init' | 'manifest' | 'syncing' | 'loading' | 'decrypting' | 'creating_zip' | 'complete';
  progress: number;  // 0-100
  message: string;
  currentItem?: string;
}

export type ExportProgressCallback = (progress: ExportProgress) => void;

/**
 * Export all user data as a ZIP file
 * 
 * @param onProgress - Callback for progress updates
 * @returns Promise that resolves when download starts
 */
export async function exportAllUserData(
  onProgress: ExportProgressCallback
): Promise<void>;

/**
 * Get export manifest (list of all data IDs)
 */
async function fetchExportManifest(): Promise<ExportManifest>;

/**
 * Sync missing chats to IndexedDB
 * Uses existing chatSyncService for efficient batch syncing
 */
async function syncMissingChats(
  allChatIds: string[],
  onProgress: ExportProgressCallback
): Promise<void>;

/**
 * Load all user data from IndexedDB
 */
async function loadAllData(): Promise<UserExportData>;

/**
 * Create ZIP archive with all data in YML format
 * Reuses existing zipExportService patterns
 */
async function createExportZip(
  data: UserExportData,
  onProgress: ExportProgressCallback
): Promise<Blob>;
```

### Processing Flow (Detailed)

#### Phase 1: Initialization
1. Validate user is authenticated
2. Initialize progress UI
3. Update progress: "Initializing export..."

#### Phase 2: Fetch Manifest
1. Call `GET /v1/settings/export-account-manifest`
2. Get list of all chat IDs user has
3. Calculate total export size estimate
4. Update progress: "Preparing X chats..."

#### Phase 3: Sync Missing Chats
1. Compare manifest chat IDs with IndexedDB
2. Identify chats not in IndexedDB
3. Use existing WebSocket sync mechanism for missing chats
4. Update progress: "Syncing chats..."
5. **Note**: Uses cached data where available

#### Phase 4: Load All Data
1. Load all chats from IndexedDB
2. Load all messages for each chat from IndexedDB
3. Update progress: "Loading chat data..."

#### Phase 5: Fetch Server Data
1. Call `GET /v1/settings/export-account-data`
2. Get usage records (already decrypted server-side with vault key)
3. Get invoice metadata
4. Get user profile data
5. Get app settings/memories
6. Update progress: "Fetching usage and invoice data..."

#### Phase 6: Decrypt Data
1. Decrypt user email with master key
2. App settings remain encrypted (app-specific keys)
3. Update progress: "Decrypting data..."

#### Phase 7: Download Invoice PDFs
1. Download all invoice PDFs in batches of 5
2. Use existing endpoint `GET /v1/payments/invoices/{id}/download`
3. Store in memory for ZIP inclusion
4. Update progress: "Downloading invoices... X/Y"

```typescript
// Download PDFs in batches to avoid overwhelming the server
const BATCH_SIZE = 5;
for (let i = 0; i < invoiceIds.length; i += BATCH_SIZE) {
  const batch = invoiceIds.slice(i, i + BATCH_SIZE);
  const results = await Promise.allSettled(
    batch.map(id => downloadInvoicePDF(id))
  );
  // Process results and add to collection
}
```

#### Phase 8: Create ZIP Archive
1. Initialize JSZip
2. Add README.md with GDPR documentation
3. Add metadata.yml with export statistics
4. Add profile.yml (user profile data)
5. Add chat folders:
   - For each chat: add .yml (structured), .md (readable), code/ (embeds)
6. Add usage/usage_history.yml
7. Add payments/invoices.yml (metadata)
8. Add payments/invoice_pdfs/ (all PDF files)
9. Add settings/app_settings.yml

```typescript
// Reuse existing chat export logic
import { convertChatToYaml, generateChatFilename } from './chatExportService';
import { downloadChatsAsZip } from './zipExportService';

// Create chats folder similar to bulk download
for (const chat of allChats) {
  const messages = messagesMap.get(chat.chat_id) || [];
  const filename = await generateChatFilename(chat, '');
  const chatFolder = zip.folder(`chats/${filename}`);
  
  // Add YML (existing function)
  const yamlContent = await convertChatToYaml(chat, messages, false);
  chatFolder.file(`${filename}.yml`, yamlContent);
  
  // Add MD, code embeds, transcripts (existing pattern)
  // ...
}
```

#### Phase 7: Download
1. Generate ZIP blob
2. Create download link
3. Trigger browser download
4. Clean up temporary objects

### Performance Optimizations

#### Batch Processing
- Process chats in batches of 50 for syncing
- Process messages in parallel using Promise.all with concurrency limit
- Stream ZIP creation instead of building entire structure in memory

#### Memory Management
- Clear processed data after adding to ZIP
- Use streaming for large files
- Limit concurrent operations

#### Progress Reporting
- Update progress at meaningful intervals (not every operation)
- Show current item being processed
- Provide time estimate based on processing speed

### Error Handling

#### Network Errors
- Retry failed chat syncs up to 3 times
- Continue with partial data if some chats fail
- Log errors but don't block entire export

#### Decryption Errors
- Skip items that fail to decrypt
- Include placeholder noting decryption failed
- Log for debugging

#### Memory Errors
- Monitor memory usage
- Warn user if export is very large (>500MB estimated)
- Offer to export in chunks if needed

## Frontend Component

**Location**: `frontend/packages/ui/src/components/settings/account/SettingsExportAccount.svelte`

**Features**:
- Authentication modal (passkey/2FA)
- Progress indicator with phases
- Current operation display
- Download completion notification
- Error handling with retry option
- Cancel button during processing

**UI States**:
1. **Initial**: "Export My Data" button with explanation
2. **Authenticating**: Passkey/2FA modal
3. **Processing**: Progress bar with phase labels
4. **Complete**: Success message with download link
5. **Error**: Error message with retry option

## Security Considerations

1. **Re-authentication**: Required before export starts
2. **Client-side decryption**: All sensitive data decrypted locally, never sent to server in plaintext
3. **No server storage**: Export never stored on server (reduces attack surface)
4. **Memory cleanup**: Sensitive data cleared after ZIP creation
5. **Audit logging**: Export requests logged (timestamp, IP, device)

## Excluded Data

The following data is NOT included in exports for security reasons:

1. **Encryption keys**: Master key, chat keys, device keys
2. **API keys**: Actual API key values (only metadata)
3. **Password hashes**: Authentication credentials
4. **Internal IDs**: Stripe customer IDs, internal reference IDs
5. **System metadata**: Server-side processing flags

## Future Enhancements

### File Attachments (Server-Side Processing)

When support for uploaded images and files is added:

1. **Server-side preparation required**: Large files can't be efficiently processed client-side
2. **Flow**:
   - Client requests export with attachments
   - Server prepares file archive on S3
   - Server returns signed download URL
   - Client downloads file archive separately
3. **Separate download**: Files downloaded as separate ZIP (not combined with data export)
4. **Progress**: Server sends WebSocket updates during preparation

### Other Future Features

1. **Selective Export**: Choose specific data categories
2. **Date Range Export**: Export only data from specific period
3. **Format Options**: Support JSON in addition to YML
4. **Scheduled Exports**: Automatic periodic exports
5. **Direct Transfer**: Transfer to another service (GDPR Article 20.2)

## Related Documentation

- [Account Deletion Architecture](./delete_account.md) - Similar authentication flow
- [Security Architecture](./security.md) - Encryption and authentication
- [Chat Export Service](../frontend/packages/ui/src/services/chatExportService.ts) - Existing chat export
- [ZIP Export Service](../frontend/packages/ui/src/services/zipExportService.ts) - Existing ZIP creation
- [Cache Architecture](./cache_architecture.md) - IndexedDB patterns
