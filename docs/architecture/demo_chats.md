# Demo Chats Architecture

## Overview

Demo chats are curated example conversations that showcase OpenMates capabilities. They are displayed to **all users (authenticated and non-authenticated)** in the chat list sidebar under the "Examples" group.

The system maintains a maximum of **5 published demo chats**. When a new demo is published and the limit is exceeded, the oldest demo chat (by creation timestamp) is automatically deleted along with all its messages, embeds, and translations.

**Client-side ID Generation:** The backend stores demos without fixed IDs. The client fetches the 5 most recent published demos and auto-generates display IDs (`demo-1` through `demo-5`) based on creation order.

## Zero-Knowledge Architecture

**Critical Security Principle:** The server never receives the encryption key to the user's original chat. This maintains zero-knowledge encryption for user data.

When sharing with community:
1. **Client decrypts locally** - User's browser decrypts the chat using the locally-stored encryption key
2. **Sends plaintext** - Decrypted messages and embeds are sent to server
3. **Server creates separate copy** - A new demo chat entity is created (encrypted with Vault)
4. **Original stays encrypted** - The user's original chat remains zero-knowledge encrypted

```
User's Original Chat (ZK encrypted with NaCl)
    │
    │ User shares with community
    ├─────────────────────────────────────────┐
    │                                         │
    ↓                                         ↓
Original Chat                          Demo Chat Copy
(ZK encrypted forever)                 (Vault encrypted)
Server never gets key ✅               Server can translate ✅
```

## Data Flow

### 1. User Submits Community Suggestion

When a user shares a chat with the community:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   Backend API   │────▶│   Directus      │
│                 │     │   /v1/share/    │     │   demo_chats    │
│ 1. Decrypt chat │     │   chat/metadata │     │                 │
│    locally      │     │                 │     │ Stores:         │
│ 2. Send         │     │ Receives:       │     │ - Metadata      │
│    plaintext    │     │ - Plaintext     │     │ - Messages      │
│    messages     │     │   messages      │     │ - Embeds        │
│ - Metadata      │     │ - Metadata      │     │ (All Vault      │
│ - Messages      │     │                 │     │  encrypted)     │
│ - Embeds        │     │ Encrypts with   │     │                 │
│                 │     │ Vault and stores│     │ status:         │
│                 │     │                 │     │ pending_approval│
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Key Details:**
- Frontend decrypts the chat **locally** using the NaCl key from IndexedDB
- Plaintext messages, embeds, and metadata are sent to backend
- Backend immediately encrypts everything with Vault's `demo_chats` transit key
- **No encryption key is ever sent to the server** ✅
- Status is set to `pending_approval`
- Timestamp is recorded for ordering

### 2. Admin Review and Approval

When an admin reviews and approves the community suggestion:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Admin UI      │────▶│   Backend API   │────▶│   Task Worker   │
│                 │     │   /v1/admin/    │     │   translate_    │
│ 1. Load pending │     │   approve-demo  │     │   demo_chat     │
│    suggestions  │     │                 │     │                 │
│ 2. Preview chat │     │ Updates status  │     │ 1. Load demo    │
│    (renders     │     │ to 'translating'│     │    messages     │
│    like regular │     │                 │     │    (already     │
│    chat)        │     │ Triggers async  │     │    decrypted)   │
│ 3. Approve      │     │ translation task│     │ 2. Translate    │
│                 │     │                 │     │    to 20 langs  │
│                 │     │                 │     │ 3. Store trans. │
│                 │     │                 │     │ 4. Set status   │
│                 │     │                 │     │    'published'  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Admin Preview:**
- Admin loads demo chat metadata from `demo_chats` (Vault-decrypted)
- When previewing, demo messages are loaded and rendered in the UI
- Admin sees the chat exactly as it will appear to users
- No access to original user chat needed

**Translation Task:**
- Loads demo messages/embeds (already in plaintext after Vault decryption)
- Translates to all target languages using LLM
- Stores translations encrypted with Vault
- Sets status to `published`
- Sends notification to admin that translation is complete

**Automatic Cleanup:**
- After publishing, if more than 5 demos exist, the oldest is deleted
- Deletion includes: demo_chats entry, all demo_messages, demo_embeds, demo_chat_translations

### 3. Client Loading Demo Chats

When any user loads the web app:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │◀────│   Backend API   │◀────│   Cache/DB      │
│                 │     │   /v1/demo/     │     │                 │
│ 1. Check hash   │     │   chats         │     │ Load published  │
│ 2. Fetch if     │     │                 │     │ demos (sorted   │
│    outdated     │     │ Returns 5 most  │     │ by timestamp)   │
│ 3. Generate IDs │     │ recent demos    │     │                 │
│    demo-1 to    │     │                 │     │ Decrypt with    │
│    demo-5       │     │ Decrypt with    │     │ Vault key       │
│ 4. Store in     │     │ Vault key       │     │                 │
│    memory +     │     │                 │     │                 │
│    IndexedDB    │     │ Send cleartext  │     │                 │
│                 │     │ to client       │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Client ID Generation:**
- Backend returns demos sorted by timestamp (newest first)
- Client assigns IDs sequentially: `demo-1`, `demo-2`, `demo-3`, `demo-4`, `demo-5`
- IDs are ephemeral and regenerated on each load

**Client Storage:**
- **Memory**: `communityDemoStore` holds demo chats for current session
- **IndexedDB**: `demo_chats_db` stores demo chats for offline access
- **Content Hash**: Used to detect if server has newer content

### 4. Change Detection

```
┌─────────────────┐                           ┌─────────────────┐
│   Client        │     GET /v1/demo/chats    │   Server        │
│                 │     ?hashes=hash1,hash2   │                 │
│ Local hashes:   │                           │ Compare hashes  │
│ [abc123, def456]│────────────────────────▶  │ (by position)   │
│                 │                           │                 │
│                 │◀───────────────────────── │ Return only     │
│ Update changed  │     Changed demos         │ changed demos   │
│ demos only      │                           │                 │
└─────────────────┘                           └─────────────────┘
```

**Hash Comparison:**
- Each demo chat has a `content_hash` field (SHA256 of all content)
- Client sends array of local hashes in timestamp order
- Server compares hashes by position (index 0 = newest, index 4 = oldest)
- Server returns only demos with different hashes
- Client updates only changed demos in IndexedDB

## Database Schema

### demo_chats (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID (primary key) |
| original_chat_id | UUID | Reference to source chat (for tracking only) |
| encrypted_title | string | Vault-encrypted title |
| encrypted_summary | string | Vault-encrypted summary |
| encrypted_category | string | Vault-encrypted category |
| encrypted_icon | string | Vault-encrypted icon name |
| encrypted_follow_up_suggestions | string | Vault-encrypted JSON array |
| content_hash | string | SHA256 hash of all content (for change detection) |
| status | string | pending_approval, translating, published, translation_failed |
| approved_by_admin | UUID | Admin user ID who approved |
| approved_at | datetime | When admin approved |
| is_active | boolean | Whether demo is active (soft delete) |
| created_at | datetime | Creation timestamp (used for ordering) |
| updated_at | datetime | Last update timestamp |

**Ordering:** Demos are ordered by `created_at` DESC (newest first). The 5 most recent are returned to clients.

**No Fixed IDs:** The `demo_id` field (demo-1, demo-2, etc.) is generated client-side based on position in the sorted list.

### demo_messages (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID (primary key) |
| demo_chat_id | UUID | Foreign key to demo_chats.id |
| role | string | user or assistant |
| encrypted_content | string | Vault-encrypted message content (TipTap JSON) |
| language | string | ISO language code (en, de, zh, etc.) |
| original_created_at | datetime | Original message timestamp (used for ordering) |
| created_at | datetime | Demo message creation timestamp |

**Note:** Messages are stored per-language. For 20 languages × 10 messages = 200 rows per demo. Messages are ordered by `original_created_at` to maintain conversation flow.

### demo_embeds (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID (primary key) |
| demo_chat_id | UUID | Foreign key to demo_chats.id |
| original_embed_id | string | Original embed ID (for reference) |
| type | string | Embed type (web-website, app-skill-use, etc.) |
| encrypted_content | string | Vault-encrypted embed content |
| language | string | ISO language code (en, de, zh, etc.) |
| original_created_at | datetime | Original embed timestamp (used for ordering) |
| created_at | datetime | Demo embed creation timestamp |

**Note:** Embeds are currently NOT translated (same content for all languages). Ordered by `original_created_at`.

### demo_chat_translations (Directus)

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Directus internal ID (primary key) |
| demo_chat_id | UUID | Foreign key to demo_chats.id |
| language | string | ISO language code (en, de, zh, etc.) |
| encrypted_title | string | Vault-encrypted translated title |
| encrypted_summary | string | Vault-encrypted translated summary |
| encrypted_follow_up_suggestions | string | Vault-encrypted translated suggestions JSON array |
| created_at | datetime | Creation timestamp |

**Note:** All translation content is Vault-encrypted for consistency. The server decrypts and caches all translations for quick access.

## API Endpoints

### GET /v1/demo/chats

List published demo chats (maximum 5, sorted by creation date).

**Query Parameters:**
- `hashes` (optional): Comma-separated list of content hashes for change detection
- `lang` (optional): Language code for translations (default: browser Accept-Language)

**Response:**
```json
{
  "demos": [
    {
      "title": "Planning a trip to Japan",
      "summary": "An example conversation about travel planning...",
      "category": "travel",
      "icon": "plane",
      "follow_up_suggestions": ["What about hotels?", "Best time to visit?"],
      "content_hash": "abc123...",
      "created_at": 1700000000,
      "updated": true  // Only if hash comparison was requested
    }
  ]
}
```

**Notes:**
- No `demo_id` in response - client generates based on position
- Returns 5 most recent published demos
- If `hashes` parameter provided, only changed demos are returned

### GET /v1/demo/chat/{position}

Get full demo chat data by position (0-4, where 0 = newest).

**Path Parameters:**
- `position`: Integer 0-4 representing the demo position

**Query Parameters:**
- `lang` (optional): Language code for translations

**Response:**
```json
{
  "title": "Planning a trip to Japan",
  "summary": "...",
  "category": "travel",
  "icon": "plane",
  "follow_up_suggestions": ["What about hotels?", "Best time to visit?"],
  "content_hash": "abc123...",
  "created_at": 1700000000,
  "chat_data": {
    "messages": [
      {
        "message_order": 0,
        "role": "user",
        "content": "I want to plan a trip to Japan...",
        "created_at": 1700000000
      },
      {
        "message_order": 1,
        "role": "assistant",
        "content": "Great choice! Japan offers...",
        "created_at": 1700000001
      }
    ],
    "embeds": [
      {
        "embed_order": 0,
        "original_embed_id": "embed-123",
        "type": "web-website",
        "content": "...",
        "created_at": 1700000001
      }
    ]
  }
}
```

### POST /v1/share/chat/metadata (Community Share)

Submit a chat as a community suggestion.

**Request Body:**
```json
{
  "chat_id": "user-chat-uuid",
  "is_private": false,
  "share_with_community": true,
  "title": "Planning a trip to Japan",
  "summary": "An example conversation...",
  "category": "travel",
  "icon": "plane",
  "follow_up_suggestions": ["What about hotels?"],
  "decrypted_messages": [
    {
      "role": "user",
      "content": "{\"type\":\"doc\",\"content\":[...]}",
      "created_at": 1700000000
    }
  ],
  "decrypted_embeds": [
    {
      "embed_id": "embed-123",
      "type": "web-website",
      "content": "{...}",
      "created_at": 1700000001
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "demo_chat_id": "uuid",
  "message": "Community suggestion submitted for review"
}
```

**Security Note:** Client decrypts the chat locally and sends plaintext. Server never receives the user's chat encryption key.

### POST /v1/admin/approve-demo-chat

Approve a pending demo chat for translation and publication.

**Request Body:**
```json
{
  "demo_chat_id": "uuid"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Demo chat approved and translation started"
}
```

### DELETE /v1/admin/demo-chat/{demo_chat_id}

Soft-delete a demo chat (sets `is_active = false`).

**Response:**
```json
{
  "success": true,
  "message": "Demo chat deactivated"
}
```

## Client Implementation

### IndexedDB Schema (demo_chats_db)

```typescript
interface DemoChatDB {
  // Object stores
  demo_chats: {
    key: number;  // Position (0-4)
    value: {
      position: number;  // 0 = newest, 4 = oldest
      title: string;
      summary: string;
      category: string;
      icon: string;
      content_hash: string;
      follow_up_suggestions: string[];
      created_at: number;
      updated_at: number;
    }
  };
  
  demo_messages: {
    key: [number, number];  // [position, message_order]
    value: {
      position: number;
      message_order: number;
      role: 'user' | 'assistant';
      content: string;  // TipTap JSON
      created_at: number;
    }
  };
  
  demo_embeds: {
    key: [number, number];  // [position, embed_order]
    value: {
      position: number;
      embed_order: number;
      original_embed_id: string;
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
  // 1. Get local hashes from IndexedDB (ordered by position)
  const localHashes = await getLocalDemoHashes(); // Returns array: [hash0, hash1, hash2, hash3, hash4]
  
  // 2. Fetch demo list with hash comparison
  const hashParam = localHashes.join(',');
  
  const response = await fetch(`/v1/demo/chats?hashes=${hashParam}`);
  const { demos } = await response.json();
  
  // 3. For each changed demo, fetch full data and update local DB
  for (let i = 0; i < demos.length; i++) {
    if (demos[i].updated) {
      const fullData = await fetch(`/v1/demo/chat/${i}`);
      await updateLocalDemoChat(i, fullData);
    }
  }
  
  // 4. Load all demos into memory from IndexedDB and generate IDs
  const demosFromDB = await getAllDemosFromIndexedDB();
  demosFromDB.forEach((demo, index) => {
    demo.demo_id = `demo-${index + 1}`;  // Generate ID client-side
  });
  
  // 5. Store in communityDemoStore
  communityDemoStore.set(demosFromDB);
}
```

### Generating Display IDs

```typescript
function generateDemoId(position: number): string {
  return `demo-${position + 1}`;  // 0 -> demo-1, 1 -> demo-2, etc.
}

// Usage
const demos = await fetchPublishedDemos();
demos.forEach((demo, index) => {
  demo.demo_id = generateDemoId(index);
  demo.chat_id = demo.demo_id;  // Used for rendering in Chat component
});
```

## Security Considerations

1. **Zero-Knowledge Maintained**: The user's original chat remains zero-knowledge encrypted. The server never receives the encryption key for the original chat, maintaining end-to-end encryption for user data.

2. **Explicit User Consent**: Users explicitly opt-in when sharing with community. The UI clearly indicates that the chat content will be sent to the server for review and translation.

3. **Separate Data Entities**: Demo chats are entirely separate from original chats. Deleting a demo chat does not affect the user's original chat.

4. **Vault Encryption**: All demo content is encrypted at rest using HashiCorp Vault's transit engine with a dedicated `demo_chats` key.

5. **Public Content by Design**: Demo chats are intentionally public content. After admin approval, they are accessible to all users without authentication. This is the intended behavior.

6. **Admin Review Process**: All community suggestions require admin approval before being published. This prevents malicious or inappropriate content from being displayed.

7. **Automatic Cleanup**: When more than 5 published demos exist, the oldest is automatically deleted (including all associated messages, embeds, and translations).

## Cache Strategy

### Server Cache (Dragonfly)

All demo chats are fully cached in memory for instant loading without database queries.

**Cache Structure:**

1. **Demo List Cache** (per language):
   - **Key**: `public:demo_chats:list:{lang}`
   - **Value**: Array of 5 most recent demo chat metadata (decrypted)
   - **TTL**: 1 hour
   - **Contains**: title, summary, category, icon, follow_up_suggestions, content_hash, created_at

2. **Demo Full Data Cache** (per position and language):
   - **Key**: `public:demo_chats:data:{position}:{lang}` (position 0-4)
   - **Value**: Full demo chat data including all messages and embeds (decrypted)
   - **TTL**: 1 hour
   - **Contains**: Complete chat data ready to send to client

**Cache Warming:**
- On application startup, cache is warmed for all 20 supported languages
- Cache is automatically refreshed when:
  - A new demo is published (triggers full cache clear and rewarm)
  - A demo is deleted (triggers full cache clear and rewarm)
  - TTL expires (lazy reload on next request)

**Cache Flow:**
```
Client Request → Check Cache → 
  ├─ HIT: Return cached data (instant)
  └─ MISS: Load from DB → Decrypt with Vault → Store in cache → Return
```

### Client Cache (IndexedDB)

- **Database**: `demo_chats_db` - Separate from user's chat database
- **Persistence**: Until explicitly cleared or demo hash changes
- **Offline Access**: Full demo content available offline
- **Position-Based**: Demos stored by position (0-4) not by fixed ID
- **Language-Specific**: Each language's translations stored separately

## Implementation Checklist

- [x] Share key extraction from URL fragment
- [ ] Client-side decryption and plaintext submission
- [ ] Backend pending demo creation with Vault encryption
- [ ] Admin approval UI with demo preview
- [ ] Translation task using pre-decrypted demo data
- [ ] Remove demo_id field from schema
- [ ] Timestamp-based ordering and cleanup
- [ ] Client-side ID generation (demo-1 to demo-5)
- [ ] Content hash generation and storage
- [ ] Hash-based change detection API
- [ ] Position-based demo loading API
- [ ] Client-side IndexedDB for demo chats
- [ ] Offline demo chat access
- [ ] Demo chat update detection on page load
