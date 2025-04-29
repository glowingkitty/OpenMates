**1. Core Feature:**

* A dedicated "Chats" section within the web application, replacing "Activity History".

**2. Key Management & Encryption:**

* **Key Generation:** The **server** generates a unique AES-GCM encryption key per chat upon its initiation.
* **Key Storage:** The actual chat encryption key is stored securely in **Hashicorp Vault**.
* **Key Reference:** The **reference/path** to the key in Vault is stored alongside chat metadata in Dragonfly (cache) and Directus (database).
* **Data-at-Rest Encryption:** The server uses the key (retrieved from Vault) to encrypt sensitive chat content (messages, draft Tiptap JSON, title) before saving to Dragonfly and Directus.
* **Data-in-Transit:** Data is sent **decrypted** over the secure WebSocket (WSS) connection after being decrypted by the server.
* **Client-Side Storage:** Chat data (metadata, messages, Tiptap draft JSON) is stored **decrypted** in the browser's **IndexedDB**.

**3. Draft Handling:**

* **Trigger:** Drafts auto-save when the user pauses typing >700ms, clicks outside the input, or `visibilitychange` occurs (if content is non-empty and changed).
* **Content:** Draft content is Tiptap JSON, sent decrypted over WSS.
* **Versioning:** Draft/title updates use versioning (`basedOnVersion`, `_v`). Stale updates are rejected, logged server-side; stale client data is discarded (no user notification for now).
* **Offline:** Chats with drafts saved locally to IndexedDB first. If offline and sync fails: attempt sync on reconnect.

**4. New Chat Initiation & Persistence:**

* **ID:** Client generates temp ID; backend creates final ID (`{first 8 chars of hashed user id}_{client_generated_chat_id}`).
* **Backend Process:** Server generates key, stores in Vault, gets reference. Encrypts initial draft content.
* **Persistence Rule:**
    * The initial chat record (metadata + vault ref + encrypted draft + `_v:1`) is saved **only** to the **Dragonfly cache**.
    * The chat record is persisted to **Directus** only when the **first actual message** (user or AI) is sent/received for that chat.

**5. Sync & Real-time (WebSocket):**

* **Connection:** Secure (WSS), multiplexed connection per device.
* **Auth:** Uses API auth tokens + device fingerprint check. Requires 2FA re-validation if fingerprint mismatches (e.g., due to IP change via VPN).
* **Updates:**
    * *Active Chat:* Receives LLM response updates paragraph-by-paragraph.
    * *Background Chats:* Receive notifications only upon full message completion.
    * Syncs chat list changes (new, delete, title change, etc.).
    * Syncs draft updates according to versioning rules.

**6. Loading, Rendering & Client Storage Limits (IndexedDB):**

* **Offline Scope:** Max 1000 most recent chats stored decrypted in IndexedDB. Older chats load on-demand if online.
* **Load Priority:** Phased IndexedDB loading (Last open chat content -> Recent 20 metadata -> Recent 20 content -> Remaining up to 1000 metadata -> Remaining up to 1000 content).
* **Client Image Previews:** S3 low-resolution image previews/thumbnails (distinct from LLM images) for chats stored in IndexedDB are limited to **5MB total** size across all cached chats, managed via an LRU (Least Recently Used) eviction strategy in IndexedDB.
* **Rendering:** Use a virtual scrolling library (e.g., `svelte-virtual-list`, TanStack Virtual) for the chat list view.
* **Interaction:** Clicking a chat loads instantly from IndexedDB if present; otherwise, its download via WebSocket is prioritized.

**7. Server-Side Caching Strategy (Dragonfly & Disk):**

* **Overall Goal:** Reduce Directus load and improve latency for active chats and LLM interactions.
* **Cache Systems:** Dragonfly (for text/metadata), Backend Local Disk (for images needed by LLM).
* **Dragonfly - Text & Metadata Cache:**
    * **Scope:** Cache only the **last 3 active chats per user**, determined via an LRU (Least Recently Used) mechanism specific to each user's active set.
    * **Content:**
        * Chat Metadata (`chat:{chat_id}:metadata`): Store `id`, `hashed_user_id`, `vault_key_reference`, `encrypted_title`, `encrypted_draft`, `version`, timestamps. Title/draft remain encrypted.
        * Full Message History (`chat:{chat_id}:messages`): Store the complete list of message objects for the chat as **encrypted** Tiptap JSON (decrypted on demand).
    * **TTL:** 30-minute **sliding expiration** on all cached items (resets on access).
    * **Logic:** Use read-aside (load from Directus on miss, decrypt messages, populate cache). Update/invalidate cache entries immediately after successful writes to Directus.
    * **Note:** Monitor Dragonfly RAM. Caching full decrypted histories for 3 potentially long chats per active user requires adequate memory provisioning.
* **Backend Disk Cache - Images for LLM:**
    * **Scope:** Cache image files referenced in messages that are needed for LLM processing.
    * **Location:** Backend server's local disk, managed via a **named Docker volume** for persistence.
    * **Content:** Image files, potentially resized/re-formatted to a "medium-high resolution" suitable for the LLM.
    * **TTL:** 30-minute **sliding expiration**.
    * **Logic:** Check disk cache before downloading source image (e.g., from S3/Hetzner). On cache miss, download, optionally process (resize), and save to the disk cache before providing to the LLM. Implement cache pruning (based on TTL, potentially max disk size).
    * **Note:** This cache is local to each backend server instance unless shared storage (e.g., NFS, EFS) is configured later. Avoid caching image blobs in Dragonfly.

**8. Code Quality:**

* Implementation should prioritize readable code, good separation of concerns, and appropriately structured files/modules.


---

**1. Directus Data Model (Collections)**

*Defines the persistent storage schema in your Directus instance.*

* **Collection: `chats`**
    * `id`: String (Primary Key - format: `{first 8 chars of hashed user id}_{client_generated_chat_id}`)
    * `hashed_user_id`: String (Indexed) `[Hashed]` (Backend hashes the user's actual ID before storing/querying)
    * `vault_key_reference`: String (Reference/Path to the chat's encryption key stored in Hashicorp Vault)
    * `encrypted_title`: Text (Nullable) `[Encrypted]` (Title for the chat, encrypted using the key from Vault)
    * `encrypted_draft`: JSON/Text (Nullable) `[Encrypted]` (Tiptap JSON representing the current user draft, encrypted)
    * `version`: Integer (Used for optimistic locking/version control of drafts and potentially titles)
    * `created_at`: DateTime (Timestamp when the chat was first initiated, e.g., first draft saved)
    * `updated_at`: DateTime (Timestamp of the last update to metadata, draft, or addition of a message)
    * `last_message_timestamp`: DateTime (Nullable) (Timestamp of the most recent *completed* message, for sorting)
    * *(Persistence Rule: A record exists in this collection **only if** at least one message has been completed and saved to the `messages` collection. Chats with only a draft exist solely in the Dragonfly cache).*

* **Collection: `messages`**
    * `id`: String (Primary Key - e.g., UUID generated by the server upon message completion)
    * `chat_id`: String / Relation `chats.id` of the chat to which the message belongs to
    * `encrypted_content`: JSON/Text `[Encrypted]` (The final, complete Tiptap JSON content of the message, encrypted using the chat's key from Vault)
    * `sender_name`: String `[Indexed]` (Contains the literal string 'user' or the specific name/identifier of the AI model/mate, e.g., "Gemini", "AssistantX")
    * `created_at`: DateTime (Timestamp when the message was fully completed and persisted server-side)
    * *(Note: The `status` field is intentionally omitted here, as only completed messages are persisted)*

---

**2. FastAPI Data Models (Pydantic)**

*Defines data structures for API validation, internal logic, and responses.*

```python
class MessageBase(BaseModel):
    content: Dict[str, Any] # Decrypted Tiptap JSON object
    sender_name: str # Contains 'user' or specific AI name

class ChatBase(BaseModel):
    title: Optional[str] = None # Decrypted title
    draft: Optional[Dict[str, Any]] = None # Decrypted Tiptap JSON draft
    version: int # Current version for optimistic locking

# --- Database Representation (Mirrors Directus schema) ---

class MessageInDB(BaseModel):
    # Represents a completed message as stored in Directus
    id: str
    chat_id: str
    encrypted_content: str # Assuming encrypted JSON stored as string/text
    sender_name: str
    created_at: datetime
    # No 'status' field

class ChatInDB(BaseModel):
    # Represents a chat as stored in Directus (only if messages exist)
    id: str
    hashed_user_id: str # Hashed user identifier
    vault_key_reference: str
    encrypted_title: Optional[str] = None
    encrypted_draft: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime
    last_message_timestamp: Optional[datetime] = None

# --- Cache / Transient Representation (Includes Status) ---

class MessageInCache(MessageBase):
    # Represents a message's state while in Dragonfly cache (can be in-progress)
    id: str # Can be a temp ID until persisted if needed
    chat_id: str
    # content inherited from MessageBase
    # sender_name inherited from MessageBase
    status: Literal['sending', 'sent', 'error', 'streaming', 'delivered'] # Transient status lives here
    created_at: datetime # Timestamp of initiation or last update in cache

# --- API / WebSocket Responses (Decrypted for Client, Includes Status) ---

class MessageResponse(MessageBase):
    # Structure for sending message data to the client (via API or WebSocket)
    id: str
    chat_id: str
    # content inherited from MessageBase
    # sender_name inherited from MessageBase
    status: Literal['sending', 'sent', 'error', 'streaming', 'delivered'] # Client needs status for UI
    created_at: datetime

class ChatResponse(ChatBase):
    # Structure for sending full chat data (metadata + messages) to the client
    id: str
    # title, draft, version inherited from ChatBase
    created_at: datetime
    updated_at: datetime
    last_message_timestamp: Optional[datetime] = None
    messages: List[MessageResponse] = [] # Embeds list of messages for the client

# Rebuild models with forward references if needed (depending on file structure)
# Example: ChatResponse.model_rebuild()

# --- Specific Payloads ---

class DraftUpdateRequestData(BaseModel):
    # Payload for saving a draft
    tempChatId: Optional[str] = None # For initiating a new chat (draft-only initially)
    chatId: Optional[str] = None # For updating existing chat draft
    content: Dict[str, Any] # Decrypted Tiptap JSON from client
    basedOnVersion: int

class WebSocketMessage(BaseModel):
    # Generic wrapper for WebSocket messages
    type: str # e.g., 'chat_initiated', 'draft_updated', 'message_new', 'message_update', etc.
    payload: Dict[str, Any] # Specific payload varies based on type

# Define other specific payload models as needed, e.g.:
class ChatInitiatedPayload(BaseModel):
    tempChatId: str
    finalChatId: str
    version: int

class NewMessagePayload(BaseModel):
     message: MessageResponse # Send the newly created/completed message details
```

---

**3. Svelte Frontend Models (TypeScript Interfaces/Types)**

*Defines data structures for Svelte stores and IndexedDB storage (all data decrypted).*

```typescript
// Represents the state of a message on the client
interface Message {
  id: string; // Unique message identifier
  chatId: string; // ID of the parent chat
  content: Record<string, any>; // Decrypted Tiptap JSON object for rendering
  sender_name: string; // Holds 'user' or the specific AI name (e.g., "Gemini")
  status: 'sending' | 'sent' | 'error' | 'streaming' | 'delivered'; // Crucial for UI state rendering
  createdAt: Date; // Timestamp of creation/completion
}

// Represents the state of a full chat on the client, including its messages
interface Chat {
  id: string; // Unique chat identifier
  title: string | null; // Decrypted title
  draft: Record<string, any> | null; // Decrypted Tiptap JSON draft object
  version: number; // Last known version from server (for conflict checks)
  messages: Message[]; // Array of message objects belonging to this chat
  createdAt: Date; // Timestamp of chat initiation
  updatedAt: Date; // Timestamp of last known update (draft, message, etc.)
  lastMessageTimestamp: Date | null; // Timestamp of the actual last completed message
  isLoading?: boolean; // Optional flag for UI loading state
  isPersisted: boolean; // Derived flag: true if chat has messages and exists in Directus, false if draft-only
}

// Represents a summarized chat item for display in the sidebar list
interface ChatListItem {
  id: string;
  title: string | null;
  lastMessageSnippet: string | null; // Short preview derived from the last message's content
  lastMessageTimestamp: Date | null; // Timestamp for sorting
  hasUnread?: boolean; // Optional flag for UI state indication
}

// --- IndexedDB Structure Suggestion ---
/*
  Object Store: 'chats'
  Key: chat.id (string)
  Value: Chat object (as defined above, containing embedded Message[] array)
  Index: 'lastMessageTimestamp' (for sorting chats in the list)
  Index: 'updatedAt' (potentially useful for other queries or cleanup)
*/
```