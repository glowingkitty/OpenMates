# Incognito Mode Architecture

## Overview

Incognito mode is a privacy feature that allows users to create chats that are not synced across devices, not stored in Directus, and not cached on the server. These chats exist only in the current browser session and are automatically cleared when the tab is closed.

## User Experience

### Activation

1. **Settings Toggle**: Users can enable/disable incognito mode via a toggle in the Settings menu
   - Location: Quick settings section in `SettingsContent.svelte`
   - Icon: `icon_incognito`
   - State: Stored in sessionStorage (device-specific, not synced)

2. **First-Time Explainer**: On first activation, show a modal/explainer window that explains:
   - What incognito mode means
   - What data is/isn't stored
   - That chats disappear when the tab closes
   - That incognito mode only applies to the current device

### While Active

When incognito mode is enabled:

- **Device-Specific**: The setting only applies to the current device/browser tab
- **New Chats**: Any new chat created while incognito mode is active is marked as an incognito chat
- **Existing Chats**: Existing regular chats (created before incognito mode was activated) remain regular chats. Sending messages to existing regular chats does NOT convert them to incognito chats. Only newly created chats are affected by incognito mode.
- **Visual Indicators**: Incognito chats are displayed with:
  - Darker background color in the chat list
  - "Incognito" label and icon
  - Distinct styling to differentiate from regular chats

### When Disabled

When incognito mode is turned off:

- **Immediate Deletion**: All incognito chats are immediately deleted from memory and sessionStorage
- **Active Chat Handling**: If the user has an incognito chat open, it is closed automatically
- **UI Update**: The chat list is updated to remove all incognito chats
- **No Recovery**: Deleted incognito chats cannot be recovered (by design)

## Technical Implementation

### Frontend Architecture

#### 1. State Management

**Storage Location**: SessionStorage (not IndexedDB, not synced)

- Key: `incognito_mode_enabled` (boolean)
- Persists only for the current browser tab session
- Cleared automatically when tab closes

**State Store**: Create a new store `incognitoModeStore.ts`:

```typescript
// frontend/packages/ui/src/stores/incognitoModeStore.ts
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

function createIncognitoModeStore() {
    const { subscribe, set, update } = writable<boolean>(false);
    
    // Initialize from sessionStorage on client
    if (browser) {
        const stored = sessionStorage.getItem('incognito_mode_enabled');
        if (stored === 'true') {
            set(true);
        }
    }
    
    return {
        subscribe,
        set: async (value: boolean) => {
            if (browser) {
                sessionStorage.setItem('incognito_mode_enabled', String(value));
                
                // CRITICAL: When disabling incognito mode, delete all incognito chats
                if (!value) {
                    const { incognitoChatService } = await import('../services/incognitoChatService');
                    await incognitoChatService.deleteAllChats();
                    
                    // Dispatch event to update UI (e.g., remove from chat list)
                    window.dispatchEvent(new CustomEvent('incognitoChatsDeleted'));
                }
            }
            set(value);
        },
        toggle: async () => {
            update(async (current) => {
                const newValue = !current;
                if (browser) {
                    sessionStorage.setItem('incognito_mode_enabled', String(newValue));
                    
                    // CRITICAL: When disabling incognito mode, delete all incognito chats
                    if (!newValue) {
                        const { incognitoChatService } = await import('../services/incognitoChatService');
                        await incognitoChatService.deleteAllChats();
                        
                        // Dispatch event to update UI (e.g., remove from chat list)
                        window.dispatchEvent(new CustomEvent('incognitoChatsDeleted'));
                    }
                }
                return newValue;
            });
        }
    };
}

export const incognitoMode = createIncognitoModeStore();
```

#### 2. Chat Type Extension

**Chat Interface**: Extend the `Chat` type to include an `is_incognito` flag:

```typescript
// frontend/packages/ui/src/types/chat.ts
export interface Chat {
    // ... existing fields
    is_incognito?: boolean; // True if this chat was created in incognito mode
}
```

#### 3. Chat Creation

**New Chat Creation**: When creating a new chat while incognito mode is active:

- Set `is_incognito: true` on the chat object
- Do NOT store in IndexedDB
- Store in memory or sessionStorage only
- Generate a temporary chat_id (e.g., `incognito-${timestamp}-${randomUUID()}`)

**Location**: `frontend/packages/ui/src/services/drafts/sessionStorageDraftService.ts` or create new `incognitoChatService.ts`

#### 4. Chat Storage Strategy

**Storage Options**:

1. **SessionStorage** (Recommended):
   - Pros: Automatically cleared on tab close, simple implementation
   - Cons: Limited storage (~5-10MB), string serialization overhead
   - Use for: Chat metadata, message IDs, draft content

2. **In-Memory Only**:
   - Pros: Fast, no serialization overhead
   - Cons: Lost on page refresh (even if tab stays open)
   - Use for: Active chat state, temporary UI state

**Hybrid Approach** (Current Implementation):

- Store chat metadata in sessionStorage
- Store full messages in sessionStorage (for persistence across page refreshes)
- Keep both chats and messages in in-memory cache (Map) for fast access
- On page refresh, reload from sessionStorage (if still in same session)
- On tab close, sessionStorage is automatically cleared (by browser)

**Implementation**:

```typescript
// frontend/packages/ui/src/services/incognitoChatService.ts
class IncognitoChatService {
    private chats: Map<string, Chat> = new Map(); // In-memory cache
    private readonly STORAGE_KEY = 'incognito_chats';
    
    // Store chat metadata in sessionStorage
    async storeChat(chat: Chat): Promise<void> {
        this.chats.set(chat.chat_id, chat);
        this.persistToSessionStorage();
    }
    
    // Load from sessionStorage on init
    async loadChats(): Promise<Chat[]> {
        if (typeof window === 'undefined') return [];
        
        const stored = sessionStorage.getItem(this.STORAGE_KEY);
        if (stored) {
            const chats = JSON.parse(stored);
            chats.forEach((chat: Chat) => {
                this.chats.set(chat.chat_id, chat);
            });
        }
        return Array.from(this.chats.values());
    }
    
    private persistToSessionStorage(): void {
        const chatsArray = Array.from(this.chats.values());
        // Only store metadata, not full message content
        const metadata = chatsArray.map(chat => ({
            chat_id: chat.chat_id,
            is_incognito: true,
            created_at: chat.created_at,
            updated_at: chat.updated_at,
            // ... other metadata fields
        }));
        sessionStorage.setItem(this.STORAGE_KEY, JSON.stringify(metadata));
    }
    
    // Delete all incognito chats (called when incognito mode is disabled)
    async deleteAllChats(): Promise<void> {
        this.chats.clear();
        if (typeof window !== 'undefined') {
            sessionStorage.removeItem(this.STORAGE_KEY);
        }
    }
}
```

#### 5. Chat Display

**Chats.svelte Modifications**:

- Filter and display incognito chats separately or mixed with regular chats
- Apply visual styling:

```svelte
  <div class="chat-item" class:incognito={chat.is_incognito}>
      {#if chat.is_incognito}
          <Icon name="icon_incognito" />
          <span class="incognito-label">Incognito</span>
      {/if}
      <!-- ... rest of chat display -->
  </div>
  ```

**Styling**:

```css
.chat-item.incognito {
    background-color: var(--color-grey-30); /* Darker background */
    border-left: 3px solid var(--color-grey-50);
}

.incognito-label {
    font-size: 0.75em;
    color: var(--color-grey-60);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
```

#### 6. Message Sending

**API Request Changes**: When sending messages from incognito chats:

- Include full chat history in every request (no server-side caching)
- Add `is_incognito: true` flag to the request payload
- Do NOT create Directus entries
- Do NOT update server-side cache

**Location**: `frontend/packages/ui/src/services/chatSyncServiceSenders.ts`

**Modification**:

```typescript
export async function sendNewMessageImpl(
    serviceInstance: ChatSynchronizationService,
    message: Message,
    encryptedSuggestionToDelete?: string | null
): Promise<void> {
    const chat = await chatDB.getChat(message.chat_id);
    const isIncognito = chat?.is_incognito || false;
    
    // For incognito chats, include full message history
    let messageHistory: Message[] = [];
    if (isIncognito) {
        // Load all messages from memory/sessionStorage
        messageHistory = await incognitoChatService.getMessagesForChat(message.chat_id);
    }
    
    const payload: any = {
        chat_id: message.chat_id,
        message: {
            message_id: message.message_id,
            role: message.role,
            content: message.content,
            created_at: message.created_at,
            sender_name: message.sender_name,
            chat_has_title: chatHasMessages
        },
        is_incognito: isIncognito, // Flag for backend
        message_history: isIncognito ? messageHistory : undefined // Full history for incognito
    };
    
    // ... rest of sending logic
}
```

### Backend Architecture

#### 1. Request Handling

**WebSocket Handler**: `backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`

**Changes Required**:

- Check for `is_incognito` flag in payload
- If incognito:
  - Skip Directus chat creation/updates
  - Skip server-side caching (Redis)
  - Skip post-processing (no chat suggestions)
  - Process AI request with full message history from payload
  - Return response without persisting

**Implementation**:

```python
async def handle_message_received(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any]
):
    is_incognito = payload.get('is_incognito', False)
    message_history = payload.get('message_history', []) if is_incognito else None
    
    if is_incognito:
        # Skip all persistence operations
        # Process AI request directly with message_history
        # Return response without caching
        pass
    else:
        # Normal flow: create/update chat, cache, etc.
        pass
```

#### 2. Post-Processing Skip

**Location**: `backend/apps/ai/processing/postprocessor.py`

**Changes**: Skip post-processing entirely for incognito chats:

- Do not generate `new_chat_request_suggestions`
- Do not generate `follow_up_request_suggestions`
- Do not update chat summary or tags
- Do not store any metadata

**Implementation**:

```python
async def handle_postprocessing(
    task_id: str,
    user_message: str,
    assistant_response: str,
    chat_summary: str,
    chat_tags: List[str],
    base_instructions: Dict[str, Any],
    secrets_manager: SecretsManager,
    cache_service: CacheService,
    available_app_ids: List[str],
    is_incognito: bool = False  # New parameter
) -> PostProcessingResult:
    if is_incognito:
        # Return empty result - no suggestions, no metadata
        return PostProcessingResult(
            follow_up_request_suggestions=[],
            new_chat_request_suggestions=[],
            harmful_response=0.0,
            top_recommended_apps_for_user=[]
        )
    
    # ... normal post-processing logic
```

#### 3. Usage Tracking

**Location**: `backend/core/api/app/services/billing_service.py` and `backend/core/api/app/services/directus/usage.py`

**Changes**: For incognito chats:

- Still track usage (for billing purposes)
- Store usage entries with `chat_id` set to a special value: `"incognito"` (not individual chat IDs)
- Group all incognito usage under a single "Incognito chats" collection in usage settings

**Implementation**:

```python
async def charge_user_credits(
    self,
    user_id: str,
    credits_to_deduct: int,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    usage_details: Optional[Dict[str, Any]] = None,
    api_key_hash: Optional[str] = None,
    device_hash: Optional[str] = None,
    is_incognito: bool = False  # New parameter
) -> None:
    # Use special chat_id for incognito chats
    chat_id = "incognito" if is_incognito else usage_details.get('chat_id')
    
    await self.directus_service.usage.create_usage_entry(
        # ... other parameters
        chat_id=chat_id,  # "incognito" for all incognito chats
        message_id=None if is_incognito else usage_details.get('message_id'),
        # ... rest of parameters
    )
```

### Usage Settings Display

**Location**: `frontend/packages/ui/src/components/settings/SettingsUsage.svelte`

**Changes**:

- Group all usage entries with `chat_id === "incognito"` under a single "Incognito chats" collection
- Display as a single aggregated entry (not split by individual chats)
- Show total credits used across all incognito chats

**Implementation**:

```typescript
// In SettingsUsage.svelte
function groupUsageByChat(entries: UsageEntry[]): Map<string, UsageEntry[]> {
    const grouped = new Map<string, UsageEntry[]>();
    
    for (const entry of entries) {
        // Group incognito chats together
        const chatId = entry.chat_id === 'incognito' ? 'incognito' : entry.chat_id;
        
        if (!grouped.has(chatId)) {
            grouped.set(chatId, []);
        }
        grouped.get(chatId)!.push(entry);
    }
    
    return grouped;
}
```

## Data Flow

### Normal Chat Flow (Non-Incognito)

```text
User sends message
  → Store in IndexedDB
  → Send to server (with chat_id)
  → Server checks cache
  → If cache hit: use cached history
  → If cache miss: load from Directus
  → Process AI request
  → Store response in Directus
  → Update cache
  → Post-process (generate suggestions)
  → Return response
  → Client stores in IndexedDB
```

### Incognito Chat Flow

```text
User sends message (incognito mode active)
  → Store in memory/sessionStorage only
  → Send to server (with is_incognito flag + full message_history)
  → Server skips cache check
  → Process AI request directly with message_history
  → Skip Directus storage
  → Skip cache update
  → Skip post-processing
  → Return response
  → Client stores in memory/sessionStorage only
  → Usage tracked with chat_id="incognito"
```

## Security Considerations

1. **No Server-Side Persistence**: Incognito chats are never stored on the server, ensuring complete privacy
2. **Session-Only Storage**: Data is cleared when the tab closes, preventing accidental data leakage
3. **Full History in Requests**: Each request includes full chat history, ensuring no server-side state tracking
4. **Usage Tracking**: Usage is still tracked for billing, but aggregated under a single "incognito" identifier

## Edge Cases

1. **Tab Refresh**:
   - If user refreshes the page, incognito chats should be restored from sessionStorage
   - If sessionStorage is cleared, chats are lost (by design)

2. **Multiple Tabs**:

   - Each tab has its own incognito mode state
   - Incognito chats in one tab are not visible in another tab
   - This is intentional - incognito mode is tab-specific

3. **Switching Incognito Mode**:
   - **When disabling incognito mode**: All incognito chats are immediately deleted from memory and sessionStorage
   - If the user had an incognito chat open, it should be closed and the chat list updated
   - New chats created after disabling will be regular chats (stored in IndexedDB)
   - **When enabling incognito mode**: Only new chats created after enabling are incognito
   - Existing regular chats remain as regular chats (cannot be converted to incognito)

4. **Offline Mode**:

   - Incognito chats work offline (stored in sessionStorage)
   - Messages queue up and send when connection is restored
   - No special handling needed beyond normal offline behavior

## Implementation Checklist

### Frontend

- [ ] Create `incognitoModeStore.ts` for state management
- [ ] Add `is_incognito` flag to Chat type
- [ ] Create `incognitoChatService.ts` for storage management
- [ ] Implement `deleteAllChats()` method in `incognitoChatService.ts`
- [ ] Update `incognitoModeStore` to delete all chats when mode is disabled
- [ ] Update `Chats.svelte` to display incognito chats with styling
- [ ] Update `Chats.svelte` to handle `incognitoChatsDeleted` event and remove chats from list
- [ ] Update `ActiveChat.svelte` to close active chat if it's incognito when mode is disabled
- [ ] Update `SettingsContent.svelte` to wire up toggle
- [ ] Create first-time explainer modal component
- [ ] Update `chatSyncServiceSenders.ts` to include full history for incognito chats
- [ ] Update `SettingsUsage.svelte` to group incognito usage
- [ ] Add translations for incognito mode UI text

### Backend

- [ ] Update `message_received_handler.py` to handle `is_incognito` flag
- [ ] Skip Directus operations for incognito chats
- [ ] Skip cache operations for incognito chats
- [ ] Update `postprocessor.py` to skip processing for incognito chats
- [ ] Update `billing_service.py` to use `chat_id="incognito"` for incognito usage
- [ ] Update usage tracking to aggregate incognito entries

### Testing

- [ ] Test incognito mode toggle in settings
- [ ] Test first-time explainer display
- [ ] Test chat creation in incognito mode
- [ ] Test message sending with full history
- [ ] Test tab refresh (sessionStorage persistence)
- [ ] Test tab close (data clearing)
- [ ] Test usage tracking aggregation
- [ ] Test visual styling of incognito chats
- [ ] Test switching incognito mode on/off
- [ ] **Test deletion of all incognito chats when mode is disabled**
- [ ] **Test that active incognito chat is closed when mode is disabled**
- [ ] **Test that chat list updates immediately when incognito chats are deleted**
- [ ] Test offline behavior with incognito chats

## Future Enhancements

1. **Export Functionality**: Allow users to export incognito chats before closing tab
2. **Warning on Tab Close**: Show a warning if user tries to close tab with unsaved incognito chats
3. **Incognito Chat Limits**: Set limits on number of incognito chats or message count
4. **Selective Incognito**: Allow users to mark individual chats as incognito after creation
5. **Incognito Chat Search**: Enable search within incognito chats (client-side only)
