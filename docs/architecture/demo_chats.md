# Demo Chats Architecture

## Overview

Demo chats are curated example conversations that showcase OpenMates capabilities. They are displayed to **all users (authenticated and non-authenticated)** in the chat list sidebar.

There are **two types** of demo chats:

1. **Intro Chats** (Static/Bundled): Pre-defined chats bundled with the app, always available offline
   - Examples: "Welcome to OpenMates!", "What makes OpenMates different?"
   - Stored in: `frontend/packages/ui/src/demo_chats/data/`
   - Translations: `frontend/packages/ui/src/i18n/sources/demo_chats/`
   - Fixed chat IDs: `demo-welcome`, `demo-different`, etc.

2. **Community Demos** (Dynamic/Server-fetched): User-submitted chats approved by admins
   - Maximum of 5 published demos at a time
   - Fetched from server, stored in-memory and IndexedDB
   - Auto-generated IDs: `demo-1` through `demo-5` (based on creation order)
   - When limit exceeded, oldest demo is automatically deleted

**Client-side ID Generation:** Community demos use ephemeral IDs generated client-side. Intro chats use fixed IDs defined in code.

## Adding Intro Chats

Intro chats are static chats bundled with the application. They're perfect for onboarding, feature explanations, and always-available examples. Here's how to add a new intro chat:

### Step 1: Create Translation Content

Create a new YAML file in `frontend/packages/ui/src/i18n/sources/demo_chats/`.

**Reference Examples:**
- [`welcome.yml`](../../frontend/packages/ui/src/i18n/sources/demo_chats/welcome.yml) - Welcome chat with assistant message
- [`what_makes_different.yml`](../../frontend/packages/ui/src/i18n/sources/demo_chats/what_makes_different.yml) - Chat with user question and assistant answer

**Translation Keys:** The YAML structure becomes translation keys like `demo_chats.example_chat.title.text` in the compiled JSON files. The file must include translations for all 22 supported languages: `en`, `de`, `zh`, `es`, `fr`, `pt`, `ru`, `ja`, `ko`, `it`, `tr`, `vi`, `id`, `pl`, `nl`, `ar`, `hi`, `th`, `cs`, `sv`.

### Step 2: Create the Data File

Create a TypeScript file in `frontend/packages/ui/src/demo_chats/data/`.

**Type Definition:** See [`frontend/packages/ui/src/demo_chats/types.ts`](../../frontend/packages/ui/src/demo_chats/types.ts) for the `DemoChat` interface.

**Reference Examples:**
- [`welcome.ts`](../../frontend/packages/ui/src/demo_chats/data/welcome.ts) - Chat starting with assistant message
- [`what-makes-different.ts`](../../frontend/packages/ui/src/demo_chats/data/what-makes-different.ts) - Chat with user question and assistant answer

**Important Fields:**
- `chat_id`: Must be unique and start with `demo-` (e.g., `demo-example`)
- `slug`: URL-friendly identifier (used in routes)
- `title`/`description`: Use translation keys (e.g., `demo_chats.example_chat.title.text`), not hardcoded text
- `messages`: Array of user/assistant messages using translation keys
- `metadata.order`: Controls display order in sidebar (1 = first, 2 = second, etc.)
- `metadata.icon_names`: Array of Lucide icon names (see [Lucide Icons](https://lucide.dev/icons/))

### Step 3: Add to Intro Chats Array

Update [`frontend/packages/ui/src/demo_chats/index.ts`](../../frontend/packages/ui/src/demo_chats/index.ts):
1. Import your new chat at the top
2. Add it to the `INTRO_CHATS` array

The array is automatically sorted by `metadata.order`, so ensure your new chat has the correct order value.

### Step 4: Rebuild Translations

After creating the YAML file, rebuild the compiled translation JSON files:

```bash
cd frontend/packages/ui
npm run build:translations
```

This generates the `locales/{locale}.json` files that the app uses at runtime.

### Step 5: Test

1. **Access the chat**: Navigate to `/#chat-id=demo-example` in the browser
2. **Check sidebar**: Verify it appears in the correct order
3. **Test translations**: Change language and verify content translates correctly
4. **Verify links**: Check that any internal links (like `/#chat-id=demo-different`) work correctly

### Best Practices

1. **Translation Keys**: Always use translation keys (e.g., `demo_chats.example_chat.title.text`) instead of hardcoded strings
2. **All Languages**: Provide translations for all 22 supported languages (or at minimum, English)
3. **Unique IDs**: Ensure `chat_id` is unique and follows the `demo-*` pattern
4. **Order**: Set `metadata.order` to control display position (1 = first, higher = later)
5. **Icons**: Use Lucide icon names for `icon_names` (see [Lucide Icons](https://lucide.dev/icons/))
6. **Markdown**: Content supports Markdown formatting (headings, lists, links, etc.)
7. **Internal Links**: Use hash links like `/#chat-id=demo-different` to link to other intro chats

### Example: Existing Intro Chats

- **Welcome Chat**: `demo-welcome` - First-time user introduction
  - Data file: [`frontend/packages/ui/src/demo_chats/data/welcome.ts`](../../frontend/packages/ui/src/demo_chats/data/welcome.ts)
  - Translations: [`frontend/packages/ui/src/i18n/sources/demo_chats/welcome.yml`](../../frontend/packages/ui/src/i18n/sources/demo_chats/welcome.yml)
- **What Makes Different**: `demo-different` - Feature comparison and differentiators
  - Data file: [`frontend/packages/ui/src/demo_chats/data/what-makes-different.ts`](../../frontend/packages/ui/src/demo_chats/data/what-makes-different.ts)
  - Translations: [`frontend/packages/ui/src/i18n/sources/demo_chats/what_makes_different.yml`](../../frontend/packages/ui/src/i18n/sources/demo_chats/what_makes_different.yml)

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

See [`frontend/packages/ui/src/demo_chats/communityDemoStore.ts`](../../frontend/packages/ui/src/demo_chats/communityDemoStore.ts) for the IndexedDB schema and implementation.

**Key Points:**
- Demos stored by position (0-4) not by fixed ID
- Position 0 = newest, position 4 = oldest
- Messages and embeds keyed by `[position, order]`
- Content hash used for change detection

### Loading Flow

See [`frontend/packages/ui/src/demo_chats/communityDemoStore.ts`](../../frontend/packages/ui/src/demo_chats/communityDemoStore.ts) for the complete loading flow implementation.

**Process:**
1. Get local hashes from IndexedDB (ordered by position)
2. Fetch demo list with hash comparison via `/v1/demo/chats?hashes=...`
3. For each changed demo, fetch full data and update local DB
4. Load all demos into memory from IndexedDB and generate IDs
5. Store in `communityDemoStore` for in-memory access

### Generating Display IDs

Display IDs (`demo-1` through `demo-5`) are generated client-side based on position. See [`frontend/packages/ui/src/demo_chats/communityDemoStore.ts`](../../frontend/packages/ui/src/demo_chats/communityDemoStore.ts) for the implementation.

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
