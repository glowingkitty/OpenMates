# Debug Tools

This document describes the debugging tools available for troubleshooting chat synchronization, message storage, and data consistency issues.

## Overview

OpenMates provides debug tools for both frontend and backend debugging:

| Tool | Location | Purpose |
|------|----------|---------|
| Browser Console Debug Utilities | Frontend (browser) | Inspect IndexedDB, validate data consistency |
| `inspect_chat.py` | Backend (Docker) | Inspect Directus database, Redis cache status |

## Frontend Debug Utilities

The frontend provides debug functions accessible via the browser's developer console. These utilities allow inspecting IndexedDB data, checking message counts, and forcing re-syncs when data inconsistencies are detected.

### Accessing Debug Utilities

1. Open the web app in your browser
2. Open Developer Tools (F12 or Cmd+Option+I)
3. Go to the Console tab
4. Use any of the following commands:

### Available Commands

All debug commands are **read-only** - they inspect data but never modify it.

#### `window.debugChat(chatId)`

Inspect a specific chat's metadata and messages in IndexedDB.

```javascript
await window.debugChat('02c083ce-32ce-4ce5-ac04-2ef25e263be3')
```

**Output includes:**
- Chat metadata (`messages_v`, `title_v`, `draft_v`, timestamps)
- Message count and list
- Role distribution (user vs assistant)
- **Version analysis** - Detects if `messages_v` doesn't match actual message count

**Example output:**
```
🔍 Opening IndexedDB...
✅ Database opened: chats_db version: 16
📦 Object stores: ['chats', 'messages', 'embeds', ...]

📋 CHAT METADATA:
  - chat_id: 02c083ce-32ce-4ce5-ac04-2ef25e263be3
  - messages_v: 7
  - title_v: 1

💬 MESSAGES:
  Total count: 6
  1. [user] message_id: abc123...
  2. [assistant] message_id: def456...
  ...

📊 VERSION ANALYSIS:
  messages_v: 7
  actual_message_count: 6
  Status: ✅ Versions appear consistent
```

#### `window.debugAllChats()`

Get an overview of all chats in IndexedDB with consistency checks.

```javascript
await window.debugAllChats()
```

**Output includes:**
- Total chat count
- Total message count
- List of all chats with their `messages_v` and actual message counts
- **Highlights inconsistent chats** where version doesn't match message count

#### `window.debugGetMessage(messageId)`

Get raw message data for a specific message ID.

```javascript
await window.debugGetMessage('abc123-def456-...')
```

### Troubleshooting Common Issues

#### Missing Messages After Page Reload

1. Run `debugChat('your-chat-id')` to check:
   - How many messages are in IndexedDB
   - What `messages_v` is set to
   
2. Compare with backend:
   ```bash
   docker exec api python /app/backend/scripts/inspect_chat.py your-chat-id
   ```
   
3. If IndexedDB has fewer messages but same `messages_v` as server, this indicates a sync inconsistency. The sync system should now automatically detect this and force a re-sync on next page load.

## Backend Debug Script: `inspect_chat.py`

A Python script to inspect chat data in Directus database and Redis cache.

### Usage

```bash
# Basic usage
docker exec api python /app/backend/scripts/inspect_chat.py <chat_id>

# Example
docker exec api python /app/backend/scripts/inspect_chat.py 02c083ce-32ce-4ce5-ac04-2ef25e263be3
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--messages-limit N` | Limit number of messages to display | 20 |
| `--embeds-limit N` | Limit number of embeds to display | 20 |
| `--usage-limit N` | Limit number of usage entries to display | 20 |
| `--json` | Output as JSON instead of formatted text | - |
| `--no-cache` | Skip cache checks (faster if Redis is down) | - |

### Examples

```bash
# Show more messages
docker exec api python /app/backend/scripts/inspect_chat.py abc123 --messages-limit 50

# Output as JSON for scripting
docker exec api python /app/backend/scripts/inspect_chat.py abc123 --json

# Skip cache checks
docker exec api python /app/backend/scripts/inspect_chat.py abc123 --no-cache
```

### Output Sections

The script outputs a detailed report with the following sections:

#### 1. Chat Metadata (from Directus)
- `hashed_user_id`
- Timestamps (`created_at`, `updated_at`, `last_message_timestamp`)
- Version tracking (`messages_v`, `title_v`)
- Sharing status
- Encrypted fields presence

#### 2. Messages (from Directus)
- Total message count
- Role distribution (user/assistant/system)
- Message list with IDs, roles, timestamps
- Encrypted content presence

#### 3. Embeds (from Directus)
- Total embed count
- Status distribution (processing/finished/error)
- Embed details (ID, type, status, parent relationships)

#### 4. Usage Entries (from Directus)
- Total usage count
- App/skill distribution
- Usage details (credits, tokens, model info)

#### 5. Cache Status (from Redis)
- Chat versions cache
- List item data cache
- AI messages cache
- Sync messages cache
- Draft cache
- Embed IDs index
- Active AI task marker
- Message queue status

### Sample Output

```
====================================================================================================
CHAT INSPECTION REPORT
====================================================================================================
Chat ID: 02c083ce-32ce-4ce5-ac04-2ef25e263be3
Generated at: 2026-01-04 17:14:55
====================================================================================================

----------------------------------------------------------------------------------------------------
CHAT METADATA (from Directus)
----------------------------------------------------------------------------------------------------
  Hashed User ID:              da984418e448fdbfe......
  Created At:                  2026-01-04 16:24:40
  Messages Version (messages_v): 7
  Title Version (title_v):       1

----------------------------------------------------------------------------------------------------
MESSAGES (from Directus) - Total: 6
----------------------------------------------------------------------------------------------------
  Role Distribution: {'user': 3, 'assistant': 3}

    1. 👤 [user     ] 2026-01-04 16:24:37
       ID: 84cd7a93...
    2. 🤖 [assistant] 2026-01-04 16:24:43
       ID: cc477aaf...
    ...

----------------------------------------------------------------------------------------------------
CACHE STATUS (from Redis)
----------------------------------------------------------------------------------------------------
  ❌ Chat Versions: NOT CACHED
  ❌ Sync Messages: NOT CACHED
  ✅ Embed IDs Indexed: 40 embed(s)
```

## Backend Debug Script: `inspect_demo_chat.py`

A Python script to inspect demo chat data in Directus database and Redis cache. Demo chats are public example conversations shown to non-authenticated users.

### Usage

```bash
# By display ID (demo-1, demo-2, etc.)
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1

# By UUID
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py 10ebe5d8-e496-4d4d-8802-51af1817583a
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--lang LANG` | Language to inspect (en, de, fr, etc.) | en |
| `--messages-limit N` | Limit number of messages to display | 20 |
| `--embeds-limit N` | Limit number of embeds to display | 20 |
| `--json` | Output as JSON instead of formatted text | - |
| `--no-cache` | Skip cache checks (faster if Redis is down) | - |

### Examples

```bash
# Inspect German translation
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1 --lang de

# Output as JSON for scripting
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1 --json

# Quick check without cache
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1 --no-cache
```

### Output Sections

#### 1. Demo Metadata (from Directus)
- UUID and display ID mapping
- Original chat ID (source chat)
- Status (pending_approval, translating, published)
- Admin approval info
- Encrypted fields presence (category, icon)
- Content hash for change detection

#### 2. Translations (from Directus)
- All available language translations
- Encrypted fields presence per language (title, summary, follow-up suggestions)

#### 3. Messages (from Directus)
- Language-specific message count
- Language breakdown across all translations
- Role distribution (user/assistant/system)
- Encrypted content and metadata presence

#### 4. Embeds (from Directus)
- Embed count (embeds are NOT translated, stored only once)
- Type distribution
- Warns if duplicate embeds exist from before the fix

#### 5. Cache Status (from Redis)
- Demo chat data cache per language
- Demo chats list cache per language

## Comparing Frontend vs Backend Data

When debugging sync issues, compare data from both sources:

| Check | Frontend Command | Backend Command |
|-------|------------------|-----------------|
| Message count | `debugChat('id')` → `messages.total_count` | `inspect_chat.py id` → "MESSAGES - Total: N" |
| Messages version | `debugChat('id')` → `messages_v` | `inspect_chat.py id` → "Messages Version" |
| Cache status | N/A (IndexedDB is always "cached") | `inspect_chat.py id` → "CACHE STATUS" section |

**If counts don't match:**
1. Backend has more messages → The sync system should auto-detect this and re-sync on page reload
2. Frontend has more messages → Unusual, may indicate sync bug (report issue)

## Related Documentation

- [Sync Architecture](./sync.md) - How the 3-phase sync system works
- [Zero-Knowledge Storage](./zero_knowledge_storage.md) - How encryption affects debugging
- [Logging](./logging.md) - Server-side logging for debugging

