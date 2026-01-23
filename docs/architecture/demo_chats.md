# Demo Chats Architecture

## Overview

Demo chats are curated example conversations that showcase OpenMates capabilities. They are displayed to **all users (authenticated and non-authenticated)** in the chat list sidebar under the "Examples" group.

Demo chats use a fixed set of IDs: `demo-1` through `demo-5`. This allows for:
- Simple client-side caching with known IDs
- Easy content replacement without creating new entries
- Consistent URLs for sharing demo content

## Data Flow

### 1. User Submits Community Suggestion

When a user shares a chat with the community:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   Backend API   │────▶│   Directus      │
│                 │     │   /v1/share/    │     │   demo_chats    │
│ - Chat data     │     │   chat/metadata │     │                 │
│ - Share key     │     │                 │     │ status:         │
│   (encrypted    │     │ Extracts key    │     │ waiting_for_    │
│   blob in URL)  │     │ from share link │     │ confirmation    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Key Details:**
- Frontend generates a share link with the chat encryption key in the URL fragment (`#key=...`)
- The key is encrypted using AES-GCM with a key derived from the chat_id (PBKDF2)
- Backend extracts this encrypted blob and stores it in `demo_chats.encrypted_key`
- Metadata (title, summary, category, icon) is encrypted with Vault and stored
- Status is set to `waiting_for_confirmation`

### 2. Admin Approval and Translation

When an admin approves the community suggestion:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Admin UI      │────▶│   Task Worker   │────▶│   Directus      │
│                 │     │   translate_    │     │                 │
│ Approve demo    │     │   demo_chat     │     │ demo_messages   │
│                 │     │                 │     │ demo_embeds     │
│                 │     │ 1. Decrypt key  │     │ demo_chat_      │
│                 │     │ 2. Fetch msgs   │     │ translations    │
│                 │     │ 3. Decrypt msgs │     │                 │
│                 │     │ 4. Translate    │     │ status:         │
│                 │     │ 5. Encrypt+save │     │ published       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Translation Task Steps:**
1. **Decrypt Share Key Blob**: Use AES-GCM with key derived from original_chat_id to extract the raw NaCl encryption key
2. **Fetch Original Messages**: Get all messages and embeds from the original chat
3. **Decrypt Content**: Use the extracted NaCl key to decrypt message/embed content
4. **Translate**: Use LLM to translate to all target languages (20 languages)
5. **Store Encrypted**: Store translated content encrypted with Vault's `demo_chats` transit key
6. **Generate Content Hash**: Create SHA256 hash of all content for change detection
7. **Update Status**: Set status to `published` and clear cache

### 3. Client Loading Demo Chats

When any user loads the web app:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │◀────│   Backend API   │◀────│   Cache/DB      │
│                 │     │   /v1/demo/     │     │                 │
│ 1. Check hash   │     │   chats         │     │ Load encrypted  │
│ 2. Fetch if     │     │                 │     │ demo chats      │
│    outdated     │     │ Decrypt with    │     │                 │
│ 3. Store in     │     │ Vault key       │     │ Decrypt         │
│    memory +     │     │                 │     │                 │
│    IndexedDB    │     │ Send cleartext  │     │                 │
│                 │     │ to client       │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Client Storage:**
- **Memory**: `communityDemoStore` holds demo chats for current session
- **IndexedDB**: `demo_chats_db` stores demo chats for offline access
- **Content Hash**: Used to detect if server has newer content

### 4. Change Detection

```
┌─────────────────┐                           ┌─────────────────┐
│   Client        │     GET /v1/demo/chats    │   Server        │
│                 │     ?hashes=demo-1:abc,   │                 │
│ Local hashes:   │     demo-2:def            │ Compare hashes  │
│ demo-1: abc123  │────────────────────────▶  │                 │
│ demo-2: def456  │                           │ Return only     │
│                 │◀───────────────────────── │ changed demos   │
│ Update changed  │     { demo-1: {...} }     │                 │
│ demos only      │                           │                 │
└─────────────────┘                           └─────────────────┘
```

**Hash Comparison:**
- Each demo chat has a `content_hash` field (SHA256 of all content)
- Client sends local hashes when fetching demo list
- Server returns only demos with different hashes
- Client updates only changed demos in IndexedDB

## Database Schema

### demo_chats (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID |
| demo_id | string | Public ID (demo-1 to demo-5) |
| original_chat_id | UUID | Reference to source chat |
| encrypted_key | string | AES-GCM encrypted share key blob |
| encrypted_title | string | Vault-encrypted title |
| encrypted_summary | string | Vault-encrypted summary |
| encrypted_category | string | Vault-encrypted category |
| encrypted_icon | string | Vault-encrypted icon name |
| encrypted_follow_up_suggestions | string | Vault-encrypted JSON array |
| content_hash | string | SHA256 hash of all content |
| status | string | waiting_for_confirmation, translating, published, translation_failed |
| approved_at | datetime | When admin approved |
| is_active | boolean | Whether demo is active |
| created_at | datetime | Creation timestamp |

### demo_messages (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID |
| demo_id | string | Reference to demo_chats.demo_id |
| message_index | int | Order in conversation |
| role | string | user or assistant |
| encrypted_content | string | Vault-encrypted message content |
| created_at | datetime | Original message timestamp |

### demo_embeds (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID |
| demo_id | string | Reference to demo_chats.demo_id |
| embed_id | string | Original embed ID |
| type | string | Embed type (web-website, app-skill-use, etc.) |
| encrypted_content | string | Vault-encrypted embed content |
| created_at | datetime | Original embed timestamp |

### demo_chat_translations (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID |
| demo_id | string | Reference to demo_chats.demo_id |
| language | string | ISO language code (en, de, zh, etc.) |
| encrypted_title | string | Vault-encrypted translated title |
| encrypted_summary | string | Vault-encrypted translated summary |
| encrypted_follow_up_suggestions | string | Vault-encrypted translated suggestions |

## API Endpoints

### GET /v1/demo/chats

List all published demo chats with optional hash comparison.

**Query Parameters:**
- `hashes` (optional): Comma-separated list of `demo_id:hash` pairs for change detection
- `lang` (optional): Language code for translations (default: browser Accept-Language)

**Response:**
```json
{
  "demos": [
    {
      "demo_id": "demo-1",
      "title": "Planning a trip to Japan",
      "summary": "An example conversation about travel planning...",
      "category": "travel",
      "icon": "plane",
      "content_hash": "abc123...",
      "updated": true  // Only if hash comparison was requested
    }
  ]
}
```

### GET /v1/demo/chat/{demo_id}

Get full demo chat data including messages and embeds.

**Response:**
```json
{
  "demo_id": "demo-1",
  "title": "Planning a trip to Japan",
  "summary": "...",
  "category": "travel",
  "follow_up_suggestions": ["What about hotels?", "Best time to visit?"],
  "content_hash": "abc123...",
  "chat_data": {
    "chat_id": "demo-1",
    "messages": [
      {
        "message_id": "demo-1-0",
        "role": "user",
        "content": "I want to plan a trip to Japan...",
        "created_at": 1700000000
      },
      {
        "message_id": "demo-1-1", 
        "role": "assistant",
        "content": "Great choice! Japan offers...",
        "created_at": 1700000001
      }
    ],
    "embeds": [
      {
        "embed_id": "demo-1-embed-0",
        "type": "web-website",
        "content": "...",
        "created_at": 1700000001
      }
    ],
    "encryption_mode": "none"
  }
}
```

## Client Implementation

### IndexedDB Schema (demo_chats_db)

```typescript
interface DemoChatDB {
  // Object stores
  demo_chats: {
    key: string;  // demo_id
    value: {
      demo_id: string;
      title: string;
      summary: string;
      category: string;
      icon: string;
      content_hash: string;
      follow_up_suggestions: string[];
      updated_at: number;
    }
  };
  
  demo_messages: {
    key: [string, number];  // [demo_id, message_index]
    value: {
      demo_id: string;
      message_id: string;
      message_index: number;
      role: 'user' | 'assistant';
      content: string;
      created_at: number;
    }
  };
  
  demo_embeds: {
    key: string;  // embed_id
    value: {
      demo_id: string;
      embed_id: string;
      type: string;
      content: string;
      created_at: number;
    }
  };
}
```

### Loading Flow

```typescript
async function loadDemoChats(): Promise<void> {
  // 1. Get local hashes from IndexedDB
  const localHashes = await getLocalDemoHashes();
  
  // 2. Fetch demo list with hash comparison
  const hashParam = Object.entries(localHashes)
    .map(([id, hash]) => `${id}:${hash}`)
    .join(',');
  
  const response = await fetch(`/v1/demo/chats?hashes=${hashParam}`);
  const { demos } = await response.json();
  
  // 3. For each changed demo, fetch full data and update local DB
  for (const demo of demos.filter(d => d.updated)) {
    const fullData = await fetch(`/v1/demo/chat/${demo.demo_id}`);
    await updateLocalDemoChat(fullData);
  }
  
  // 4. Load all demos into memory from IndexedDB
  await loadDemoChatsIntoMemory();
}
```

## Security Considerations

1. **Share Key Protection**: The share key blob is encrypted with a key derived from the chat_id using PBKDF2 (100,000 iterations). This ensures only those with the share link can access the key.

2. **Vault Encryption**: All demo content stored in Directus is encrypted with Vault's transit engine using a dedicated `demo_chats` key. This protects data at rest.

3. **Cleartext Transport**: Demo content is decrypted server-side and sent as cleartext to clients. This is intentional as demo chats are public content meant to be accessible without authentication.

4. **No User Data Leakage**: Demo chats are copies of original chats. The original chat remains encrypted with the user's personal key.

## Cache Strategy

### Server Cache (Dragonfly)

- **Key**: `public:demo_chat:list:{lang}` - List of all published demos for a language
- **Key**: `public:demo_chat:data:{demo_id}:{lang}` - Full demo data
- **TTL**: 1 hour (auto-refresh on content update)
- **Invalidation**: Clear all demo cache when any demo is published/updated

### Client Cache (IndexedDB)

- **Database**: `demo_chats_db` - Separate from user's chat database
- **Persistence**: Until explicitly cleared or demo hash changes
- **Offline Access**: Full demo content available offline

## Implementation Checklist

- [x] Share key extraction from URL fragment
- [x] Pending demo chat creation on community share
- [x] Admin approval UI
- [x] Translation task with key decryption
- [ ] Content hash generation and storage
- [ ] Hash-based change detection API
- [ ] Client-side IndexedDB for demo chats
- [ ] Offline demo chat access
- [ ] Demo chat update detection on page load
