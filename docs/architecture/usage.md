# Usage Tracking Architecture

## Overview

The usage tracking system records and displays user credit consumption across chats, apps, and API keys. The architecture is designed to scale efficiently for thousands of usage entries per user per month by using pre-aggregated summaries and archiving older data.

## Architecture Principles

1. **Fast Summary Queries**: Monthly summaries are pre-calculated and stored in separate collections for instant retrieval
2. **Lazy Detail Loading**: Individual usage entries are only loaded when a user clicks on a summary item
3. **Data Retention**: Only the last 3 months of usage entries are kept in Directus; older entries are archived to S3
4. **Incremental Updates**: Summaries are updated incrementally when usage entries are created (no expensive aggregation queries)

## Data Model

### Core Collections

#### `usage` Collection
Stores individual usage entries. Only entries from the last 3 months are kept in Directus.

**Key Fields:**
- `user_id_hash`: Hashed user identifier
- `chat_id`: Chat ID (cleartext, for client-side matching)
- `app_id`: App identifier (cleartext)
- `skill_id`: Skill identifier (cleartext)
- `api_key_hash`: SHA-256 hash of API key (for API key tracking)
- `encrypted_credits_costs_total`: Encrypted credit costs
- `encrypted_input_tokens`: Encrypted input tokens
- `encrypted_output_tokens`: Encrypted output tokens
- `created_at`: Unix timestamp (seconds)

#### `usage_monthly_chat_summaries` Collection
Pre-aggregated monthly summaries per chat.

**Key Fields:**
- `user_id_hash`: Hashed user identifier (indexed)
- `chat_id`: Chat ID (indexed)
- `year_month`: Month identifier in format "YYYY-MM" (indexed)
- `total_credits`: Total credits for this chat in this month
- `entry_count`: Number of usage entries
- `is_archived`: Boolean flag indicating if underlying entries are archived
- `archive_s3_key`: S3 key path to archived data (nullable, e.g., `usage-archives/{user_id_hash}/{year_month}/usage.json.gz`)
- `created_at`: Timestamp
- `updated_at`: Timestamp

#### `usage_monthly_app_summaries` Collection
Pre-aggregated monthly summaries per app.

**Key Fields:**
- `user_id_hash`: Hashed user identifier (indexed)
- `app_id`: App identifier (indexed)
- `year_month`: Month identifier in format "YYYY-MM" (indexed)
- `total_credits`: Total credits for this app in this month
- `entry_count`: Number of usage entries
- `is_archived`: Boolean flag indicating if underlying entries are archived
- `archive_s3_key`: S3 key path to archived data (nullable)
- `created_at`: Timestamp
- `updated_at`: Timestamp

#### `usage_monthly_api_key_summaries` Collection
Pre-aggregated monthly summaries per API key.

**Key Fields:**
- `user_id_hash`: Hashed user identifier (indexed)
- `api_key_hash`: SHA-256 hash of API key (indexed)
- `year_month`: Month identifier in format "YYYY-MM" (indexed)
- `total_credits`: Total credits for this API key in this month
- `entry_count`: Number of usage entries
- `is_archived`: Boolean flag indicating if underlying entries are archived
- `archive_s3_key`: S3 key path to archived data (nullable)
- `created_at`: Timestamp
- `updated_at`: Timestamp

## Data Flow

### Usage Entry Creation

When a usage entry is created:

1. **Insert into `usage` collection** (if within last 3 months)
   - Entry is stored with encrypted sensitive fields
   - Cleartext fields (chat_id, app_id, skill_id) stored for queryability

2. **Update monthly summaries** (incremental update)
   - Find or create summary record for the appropriate type (chat/app/api_key)
   - Increment `total_credits` and `entry_count`
   - Set `is_archived = false` (entry is new, so not archived)
   - Update `updated_at` timestamp

3. **Edge case handling**
   - If entry is older than 3 months (shouldn't happen for new entries, but handle gracefully)
   - Archive immediately if needed

### Archive Process

**Monthly Celery Task** (runs on 1st of each month at 2 AM UTC):

1. **Calculate cutoff month**: 3 months ago from current date
2. **Find users with entries to archive**: Query `usage` collection for entries older than cutoff
3. **For each user and month**:
   - Fetch all usage entries for that user/month from Directus
   - Group entries by type (chats, apps, api_keys)
   - Compress entries (gzip)
   - Encrypt archive with user's vault key
   - Upload to S3: `usage-archives/{user_id_hash}/{year_month}/usage.json.gz`
   - Update summary records:
     - Set `is_archived = true`
     - Set `archive_s3_key = "usage-archives/{user_id_hash}/{year_month}/usage.json.gz"`
   - Delete entries from Directus `usage` collection (only after successful S3 upload)

### Archive Format

**S3 Key Pattern**: `usage-archives/{user_id_hash}/{year_month}/usage.json.gz`

**Archive JSON Structure**:
```json
{
  "user_id_hash": "abc123...",
  "year_month": "2024-01",
  "archived_at": 1234567890,
  "entries": [
    {
      "id": "uuid",
      "chat_id": "chat_123",
      "app_id": "ai",
      "skill_id": "ask",
      "encrypted_credits_costs_total": "encrypted_value",
      "encrypted_input_tokens": "encrypted_value",
      "encrypted_output_tokens": "encrypted_value",
      "created_at": 1234567890,
      // ... all other usage entry fields
    }
  ]
}
```

**Encryption**:
- Archive is encrypted with user's vault key before upload
- Compressed with gzip
- Stored as encrypted + compressed file in S3

## API Endpoints

### Summary Endpoints (Fast)

**GET `/api/settings/usage/summaries`**
- Query parameters:
  - `type`: "chats", "apps", or "api_keys"
  - `months`: Number of months to fetch (default: 3)
- Returns: Array of summary objects with `is_archived` flag
- Performance: Fast - only queries summary tables

### Detail Endpoints (Lazy Loading)

**GET `/api/settings/usage/details`**
- Query parameters:
  - `type`: "chat", "app", or "api_key"
  - `identifier`: chat_id, app_id, or api_key_hash
  - `year_month`: Month in format "YYYY-MM"
- Behavior:
  1. Check summary record for `is_archived` flag
  2. If `is_archived = false`: Query Directus `usage` collection
  3. If `is_archived = true`:
     - Check cache first (cache key: `usage_archive:{user_id_hash}:{year_month}`, TTL: 1 hour)
     - If not in cache: Fetch from S3, decrypt, filter, cache, return
- Returns: Array of filtered usage entries

### Export Endpoint

**GET `/api/settings/usage/export`**
- Query parameters:
  - `months`: Number of months to export (default: 3)
- Behavior:
  - Loads entries from Directus (last 3 months)
  - If months > 3: Also loads from S3 archives
  - Returns all entries as CSV/JSON
- Performance: May be slow for large exports (consider async job for very large exports)

## Caching Strategy

### Archive Cache

**Cache Key Pattern**: `usage_archive:{user_id_hash}:{year_month}`

**Cache TTL**: 1 hour

**Cache Content**: Decrypted and processed usage entries from archived data

**Cache Invalidation**:
- When new entries are added to an archived month (shouldn't happen, but handle gracefully)
- Manual cache clear if needed

## Frontend Behavior

### Initial Load

1. Fetch summaries for last 3 months (fast)
2. Display grouped by month
3. Show "Show more" button if more months exist

### On Summary Click

1. Call details endpoint with filters
2. Show loading state (especially if loading from S3)
3. Display individual usage entries

### Show More

1. Load 3 more months of summaries
2. Append to existing list
3. Update "Show more" button visibility

### Export

1. Call export endpoint
2. Show loading state
3. Download CSV file

## Security Considerations

### Data Privacy

- **Sensitive fields encrypted**: Credits, tokens, and model identifiers are encrypted with user's vault key
- **Cleartext fields**: Only non-PII fields stored in cleartext (app_id, skill_id, chat_id for client-side matching)
- **User ID hashing**: User IDs are hashed before storage
- **Archive encryption**: Archived data is encrypted before upload to S3

### Access Control

- All endpoints require authentication
- Users can only access their own usage data
- S3 archives are private (not publicly accessible)

### Archive S3 Key

The `archive_s3_key` field stores the S3 path as cleartext because:
- It's just metadata (path identifier)
- The actual sensitive data is encrypted inside the archive
- `user_id_hash` is already hashed (not PII)
- `year_month` is not sensitive
- Encrypting the key would add complexity without security benefit

## Performance Characteristics

### Summary Queries
- **Query time**: < 50ms (indexed queries on small summary tables)
- **Data size**: ~100 bytes per summary record
- **Scalability**: Handles thousands of users with millions of usage entries

### Detail Queries (Not Archived)
- **Query time**: < 200ms (indexed queries on usage collection)
- **Data size**: Varies by number of entries
- **Scalability**: Limited by Directus query performance

### Detail Queries (Archived)
- **First load**: ~500ms - 2s (S3 fetch + decrypt + cache)
- **Cached load**: < 50ms (from cache)
- **Data size**: Varies by number of entries
- **Scalability**: Excellent (S3 scales to petabytes)