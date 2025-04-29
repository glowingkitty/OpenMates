<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import Chat from './Chat.svelte';
    import { panelState } from '../../stores/panelStateStore'; // Import the new store
    import { authStore } from '../../stores/authStore';
    import { chatDB } from '../../services/db';
    import { webSocketService } from '../../services/websocketService'; // Import WebSocket service
    import type { Chat as ChatType, ChatListItem } from '../../types/chat'; // Use ChatListItem instead of ChatListEntry
    import { tooltip } from '../../actions/tooltip';
    import KeyboardShortcuts from '../KeyboardShortcuts.svelte';

    const dispatch = createEventDispatcher();

    let chats: ChatType[] = [];
    let loading = true;

    // Track current chat index
    let currentChatIndex = -1;

    // Modified sorting function based on new Chat type
    function sortChatsInGroup(chats: ChatType[]): ChatType[] {
        return chats.sort((a, b) => {
            const aIsDraft = a.draft !== null;
            const bIsDraft = b.draft !== null;

            // Prioritize drafts
            if (aIsDraft && !bIsDraft) return -1;
            if (bIsDraft && !aIsDraft) return 1;

            // If both are drafts or both are not, sort by updatedAt (most recent first)
            // Use updatedAt or fallback to createdAt if needed
            const aDate = a.updatedAt ?? a.createdAt;
            const bDate = b.updatedAt ?? b.createdAt;
            return bDate.getTime() - aDate.getTime();
            // Note: unreadCount is no longer part of the Chat type from the spec.
            // Sorting by lastMessageTimestamp might be better for non-drafts if available.
            // Let's refine later if needed. For now, updatedAt is the primary sort key after drafts.
        });
    }

    // Modified grouping logic to include sorting
    $: groupedChats = chats.reduce<Record<string, ChatType[]>>((groups, chat) => {
        const now = new Date();
        // Use updatedAt or createdAt for grouping
        const chatDate = chat.updatedAt ?? chat.createdAt;
        const diffDays = Math.floor((now.getTime() - chatDate.getTime()) / (1000 * 60 * 60 * 24));
        
        let groupKey: string;
        if (diffDays === 0) {
            groupKey = 'today';
        } else if (diffDays === 1) {
            groupKey = 'yesterday';
        } else {
            groupKey = `days_ago_${diffDays}`;
        }

        if (!groups[groupKey]) {
            groups[groupKey] = [];
        }
        groups[groupKey].push(chat);
        
        // Sort chats in this group
        groups[groupKey] = sortChatsInGroup(groups[groupKey]);
        
        return groups;
    }, {});

    // Function to get localized group title
    function getLocalizedGroupTitle(groupKey: string): string {
        if (groupKey === 'today') {
            return $_('activity.today.text');
        } else if (groupKey === 'yesterday') {
            return $_('activity.yesterday.text');
        } else if (groupKey.startsWith('days_ago_')) {
            const days = groupKey.split('_')[2];
            return $_('activity.days_ago.text', { values: { days } });
        }
        return groupKey;
    }

    // Flatten grouped chats for navigation
    $: flattenedChats = Object.values(groupedChats).flat();

    let languageChangeHandler: () => void;

    // --- WebSocket Handlers ---
    // TODO: Update payload type for initial sync if backend sends ChatResponse[] instead of ChatListEntry[]
    // Assuming backend sends data compatible with ChatListItem for the list part,
    // and potentially full ChatResponse for the last open chat.
    // For now, let's assume payload.chats contains items compatible with ChatListItem structure.
    const handleInitialSync = async (payload: { chats: ChatListItem[], lastOpenChatId?: string }) => {
        console.debug("[Chats] Handling initial sync data:", payload);
        loading = true; // Set loading true during merge
        try {
            // 1. Fetch all chats from IndexedDB
            const localChats = await chatDB.getAllChats();
            const localChatMap = new Map<string, ChatType>(localChats.map(chat => [chat.id, chat]));
            console.debug(`[Chats] Found ${localChatMap.size} chats locally.`);

            const mergedChats: ChatType[] = [];

            // 2. Iterate through WebSocket data
            for (const serverEntry of payload.chats) {
                const serverChatId = serverEntry.id;
                const localChat = localChatMap.get(serverChatId);
                // Use lastMessageTimestamp from ChatListItem for comparison, fallback to Date(0) if null
                const serverTimestamp = serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : new Date(0);

                if (localChat) {
                    // 3a. Chat exists locally - Merge based on timestamp
                    // Use updatedAt or lastMessageTimestamp from local chat for comparison
                    const localTimestamp = localChat.updatedAt ?? (localChat.lastMessageTimestamp ?? new Date(0));

                    // Prefer server list entry data if its timestamp is newer or equal
                    // Note: This only merges list metadata (title, timestamp). Full chat data (messages, draft) comes from DB or separate fetch.
                    if (serverTimestamp >= localTimestamp) {
                        console.debug(`[Chats] Merging server list entry for chat ${serverChatId} (Server newer or equal)`);
                        // Create a Chat object based on local data + server list entry
                        mergedChats.push({
                            ...localChat, // Keep local messages, draft, version etc.
                            id: serverEntry.id,
                            title: serverEntry.title, // Update title from server list entry
                            lastMessageTimestamp: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : null,
                            // Update updatedAt based on server list entry's timestamp if it's more recent
                            updatedAt: serverTimestamp > localTimestamp ? serverTimestamp : localTimestamp,
                            // isPersisted needs to be determined based on local messages or backend info
                            isPersisted: localChat.messages.length > 0, // Simple initial check
                        });
                    } else {
                        // Local data is newer? This might indicate an offline edit not yet synced.
                        // Keep local data for now, but log a warning.
                        // TODO: Consider a more robust conflict resolution strategy if needed.
                        console.warn(`[Chats] Local chat ${serverChatId} is newer than server. Keeping local version for now.`);
                        mergedChats.push(localChat);
                    }
                    localChatMap.delete(serverChatId); // Remove from map as it's processed
                } else {
                    // 3b. Chat doesn't exist locally - Add from server data
                    console.debug(`[Chats] Adding new chat ${serverChatId} from server list entry.`);
                    // Create a minimal Chat object based on the list entry
                    // Full data (messages, draft) needs to be fetched if user selects it
                    const now = new Date();
                    mergedChats.push({
                        id: serverEntry.id,
                        title: serverEntry.title,
                        draft: null, // Assume no draft initially from list entry
                        version: 1, // Default version for new entry? Or should backend provide? Assume 1.
                        messages: [],
                        createdAt: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : now, // Use timestamp or now
                        updatedAt: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : now,
                        lastMessageTimestamp: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : null,
                        isPersisted: false, // Assume not persisted if just from list entry without messages
                    });
                }
            }

            // 4. Handle chats remaining in the map (local only)
            localChatMap.forEach((localOnlyChat, chatId) => {
                // Keep local-only chats that have a draft
                if (localOnlyChat.draft !== null) {
                    console.debug(`[Chats] Keeping local-only draft chat ${chatId}.`);
                    mergedChats.push(localOnlyChat);
                } else {
                    // Chat exists locally but not on server, and isn't a draft with content.
                    // Assume it was deleted on the server or is an empty draft. Remove from local DB.
                    console.debug(`[Chats] Removing local-only chat ${chatId} (likely deleted on server or empty draft).`);
                    chatDB.deleteChat(chatId).catch(err => console.error(`[Chats] Failed to delete local-only chat ${chatId}:`, err));
                }
            });

            // 5. Update state (sorting happens reactively via groupedChats)
            chats = mergedChats;
            console.debug(`[Chats] Merged list contains ${chats.length} chats.`);

            // 6. Handle lastOpenChatId
            if (payload.lastOpenChatId) {
                console.debug(`[Chats] Initial sync included lastOpenChatId: ${payload.lastOpenChatId}`);
                const chatToSelect = chats.find(c => c.id === payload.lastOpenChatId);
                if (chatToSelect) {
                    console.debug(`[Chats] Found chat to select: ${chatToSelect.id}. Selecting it.`);
                    // Use setTimeout to ensure the UI has updated with the new chat list
                    // before trying to find the index and dispatching the event.
                    setTimeout(() => {
                        handleChatClick(chatToSelect);
                    }, 0);
                } else {
                    console.warn(`[Chats] lastOpenChatId ${payload.lastOpenChatId} not found in merged chat list.`);
                }
            }

        } catch (error) {
            console.error("[Chats] Error during initial sync merge:", error);
            // Fallback: Load directly from payload as before, or from DB?
            // Sticking with payload for now to ensure server state is reflected after error.
            chats = payload.chats.map(entry => ({
                // Map ChatListItem to minimal ChatType for fallback
                id: entry.id,
                title: entry.title,
                draft: null,
                version: 1, // Default
                messages: [],
                createdAt: entry.lastMessageTimestamp ? new Date(entry.lastMessageTimestamp) : new Date(),
                updatedAt: entry.lastMessageTimestamp ? new Date(entry.lastMessageTimestamp) : new Date(),
                lastMessageTimestamp: entry.lastMessageTimestamp ? new Date(entry.lastMessageTimestamp) : null,
                isPersisted: false,
            }));
        } finally {
            loading = false;
        }
    };

    // Adjust payload type to align with ChatResponse from backend spec
    // Assuming the backend sends a ChatResponse object for 'chat_added' events
    const handleChatAdded = (payload: {
        id: string;
        title: string | null;
        draft: Record<string, any> | null;
        version: number;
        created_at: string | Date; // ISO string or Date
        updated_at: string | Date; // ISO string or Date
        last_message_timestamp: string | Date | null; // ISO string or Date or null
        messages: Array<{ // Assuming messages match MessageResponse structure
            id: string;
            chatId: string;
            content: Record<string, any>;
            sender_name: string;
            status: 'sending' | 'sent' | 'error' | 'streaming' | 'delivered';
            created_at: string | Date; // ISO string or Date
        }>;
        // Assuming 'mates' might be included in the payload if available
        mates?: string[];
        // Assuming 'unreadCount' might be included if relevant for 'chat_added'
        unreadCount?: number;
    }) => {
        console.debug("[Chats] Handling chat added:", payload);

        const now = new Date();
        // Map payload messages to the frontend Message type
        const mappedMessages: ChatType['messages'] = payload.messages.map(msg => ({
            ...msg,
            createdAt: new Date(msg.created_at) // Ensure Date object
        }));

        const newChat: ChatType = {
            id: payload.id,
            title: payload.title ?? 'Untitled Chat',
            draft: payload.draft ?? null,
            version: payload.version ?? 1, // Use provided version or default to 1
            mates: payload.mates ?? [], // Use provided mates or default to empty array
            messages: mappedMessages,
            createdAt: new Date(payload.created_at ?? now),
            updatedAt: new Date(payload.updated_at ?? now),
            lastMessageTimestamp: payload.last_message_timestamp ? new Date(payload.last_message_timestamp) : null,
            unreadCount: payload.unreadCount ?? 0, // Use provided or default to 0
            // Determine persistence based on whether messages exist
            isPersisted: mappedMessages.length > 0,
            // isLoading can be defaulted to false or omitted
        };

        // Avoid adding duplicates if the chat/draft already exists (e.g., due to race conditions)
        if (!chats.some(chat => chat.id === newChat.id)) {
            chats = [newChat, ...chats]; // Add to the top (sorting will handle placement)
            chatDB.addChat(newChat); // Update local DB
            console.debug(`[Chats] Added new chat/draft entry: ${newChat.id}`);
        } else {
            console.warn(`[Chats] Chat/Draft with ID ${newChat.id} already exists. Skipping add.`);
            // Optionally update existing entry if needed, though metadata_updated should handle this
            // For now, just prevent duplication.
        }
        // chatDB.addChat(newChat); // Update local DB - Redundant, already called inside the if block
    };

    const handleChatDeleted = (payload: { chatId: string }) => {
        console.debug("[Chats] Handling chat deleted:", payload);
        chats = chats.filter(chat => chat.id !== payload.chatId);
        chatDB.deleteChat(payload.chatId); // Update local DB
        // If the deleted chat was selected, deselect it
        if (currentChatIndex !== -1 && flattenedChats[currentChatIndex]?.id === payload.chatId) {
            currentChatIndex = -1;
            // Optionally select the next/previous chat or dispatch an event
            dispatch('chatDeselected');
        }
    };

    // Update payload type to use ChatListItem
    const handleChatMetadataUpdated = (payload: { chatId: string, updatedFields: Partial<ChatListItem>, version: number }) => {
        console.debug("[Chats] Handling chat metadata updated:", payload);
        chats = chats.map(chat => {
            if (chat.id === payload.chatId) {
                // The backend handles version conflicts for metadata updates.
                // We trust the incoming payload and update the local version.
                const updatedChat: ChatType = {
                    ...chat, // Start with existing chat data
                    ...payload.updatedFields, // Apply updates from payload (e.g., title)
                    version: payload.version, // Update the version number from the payload
                    // Keep existing draft, messages, etc. unless payload specifically updates them
                    // Update updatedAt timestamp
                    // Update updatedAt based on lastMessageTimestamp from ChatListItem payload
                    updatedAt: payload.updatedFields.lastMessageTimestamp ? new Date(payload.updatedFields.lastMessageTimestamp) : new Date(),
                    // Update lastMessageTimestamp if provided
                    lastMessageTimestamp: payload.updatedFields.lastMessageTimestamp ? new Date(payload.updatedFields.lastMessageTimestamp) : chat.lastMessageTimestamp,
                    // Update unreadCount if provided in metadata update
                    unreadCount: payload.updatedFields.hasUnread ? (chat.unreadCount ?? 0) + 1 : (payload.updatedFields.hasUnread === false ? 0 : chat.unreadCount), // Example logic, needs refinement based on how backend sends unread status
                    // isPersisted likely doesn't change on metadata update
                    isPersisted: chat.isPersisted, // Keep existing
                };

                chatDB.updateChat(updatedChat); // Update local DB
                return updatedChat;
            }
            return chat;
        });
        // Re-sort if necessary, e.g., if lastUpdated changed
        chats = [...chats]; // Trigger reactivity
    };

    // Handler for successful draft updates confirmed by the server
    const handleDraftUpdated = (payload: { chatId: string, content: Record<string, any> | null, basedOnVersion: number }) => {
        console.debug("[Chats] Handling draft updated confirmation:", payload);
        chats = chats.map(chat => {
            if (chat.id === payload.chatId) {
                const updatedChat: ChatType = {
                    ...chat,
                    draft: payload.content, // Update draft content (can be null)
                    version: payload.basedOnVersion, // Update version to the new confirmed version
                    updatedAt: new Date() // Update timestamp
                };
                chatDB.updateChat(updatedChat); // Update local DB
                return updatedChat;
            }
            return chat;
        });
         chats = [...chats]; // Trigger reactivity for potential sorting changes
    };

    // Handler for draft update conflicts reported by the server
    const handleDraftConflict = (payload: { chatId: string, draftId?: string }) => {
        console.warn(`[Chats] Draft conflict detected for chat ${payload.chatId}. Local draft might be stale. Payload:`, payload);
        // TODO: Implement more robust conflict handling.
        // Options:
        // 1. Notify user their draft wasn't saved due to conflict.
        // 2. Discard local draft changes for the conflicting chat.
        // 3. Fetch the latest chat state from the server to overwrite local.
        // For now, just log the warning. The user's next save attempt might succeed if they have the latest version.
        const chatIndex = chats.findIndex(c => c.id === payload.chatId);
        if (chatIndex > -1) {
            // Maybe add a visual indicator?
            // chats[chatIndex].hasConflict = true; // Requires adding 'hasConflict' to ChatType
            // chats = [...chats];
        }
    };
    // --- End WebSocket Handlers ---

    onMount(async() => {
        // Remove old event listener
        // window.addEventListener('chatUpdated', handleChatUpdate);

        // Add language change event listener
        languageChangeHandler = () => {
            // Force re-render of the chat groups by triggering a state update
            chats = [...chats];
        };
        window.addEventListener('language-changed', languageChangeHandler);
        
        // Register WebSocket handlers
        webSocketService.on('initial_sync_data', handleInitialSync);
        webSocketService.on('chat_added', handleChatAdded);
        webSocketService.on('chat_deleted', handleChatDeleted);
        webSocketService.on('chat_metadata_updated', handleChatMetadataUpdated);
        webSocketService.on('draft_updated', handleDraftUpdated); // Register new handler
        webSocketService.on('draft_conflict', handleDraftConflict); // Register new handler

        // Attempt to connect WebSocket
        try {
            console.debug("[Chats] Initializing WebSocket connection...");
            // Connect returns a promise, but we don't necessarily need to await it here.
            // The 'initial_sync_data' handler will populate chats when ready.
            // We still need a fallback if WS fails.
            webSocketService.connect().catch(err => {
                console.error("[Chats] WebSocket initial connection failed:", err);
                // Fallback to loading from DB if WS connection fails initially
                loadChatsFromDB();
            });
        } catch (error) {
            console.error("[Chats] Error initiating WebSocket connection:", error);
            loadChatsFromDB(); // Fallback on error
        }

        // Initialize DB in parallel or after WS attempt
        initializeAndLoadDB();

    });

    // Separate function for DB initialization and loading (used as fallback)
    async function initializeAndLoadDB() {
        try {
            console.debug("[Chats] Initializing database");
            await chatDB.init();

            // Load example chats only if DB is truly empty AND WS didn't provide initial data
            const checkChats = await chatDB.getAllChats();
            if (checkChats.length === 0 && chats.length === 0) { // Check both sources
                console.debug("[Chats] No existing chats in DB or from WS. No example chats will be loaded. Waiting for real sync.");
                // No example chats. If WS is not connected, chats array remains empty.
                if (!webSocketService.isConnected()) {
                    chats = await chatDB.getAllChats();
                }
            } else if (chats.length === 0 && !webSocketService.isConnected()) {
                // If WS is not connected and didn't provide data, load from DB
                console.debug("[Chats] Loading chats from DB as fallback.");
                chats = await chatDB.getAllChats();
            }
        } catch (error) {
            console.error("[Chats] Error initializing/loading chats from DB:", error);
        } finally {
            // Only set loading to false if WS hasn't already done so
            if (loading) {
                loading = false;
            }
        }
    }

    // Renamed function for clarity
    async function loadChatsFromDB() {
        // Removed check for private property chatDB.db
        // initializeAndLoadDB ensures init() is called.
        // We only load if chats array is empty, assuming WS or previous load didn't populate it.
        if (chats.length === 0) {
            try {
                console.debug("[Chats] Loading chats from DB...");
                chats = await chatDB.getAllChats();
            } catch (error) {
                console.error("[Chats] Error loading chats from DB:", error);
            } finally {
                loading = false;
            }
        } else {
             // Chats already loaded (likely by WS), ensure loading is false
             loading = false;
        }
    }

    onDestroy(() => {
        // Remove old listener if it was ever added (belt and suspenders)
        // window.removeEventListener('chatUpdated', handleChatUpdate);
        window.removeEventListener('language-changed', languageChangeHandler);

        // Unregister WebSocket handlers
        webSocketService.off('initial_sync_data', handleInitialSync);
        webSocketService.off('chat_added', handleChatAdded);
        webSocketService.off('chat_deleted', handleChatDeleted);
        webSocketService.off('chat_metadata_updated', handleChatMetadataUpdated);
        webSocketService.off('draft_updated', handleDraftUpdated); // Unregister handler
        webSocketService.off('draft_conflict', handleDraftConflict); // Unregister handler

        // Optional: Disconnect WebSocket if component is destroyed?
        // Depends on whether the service should persist globally or per-component instance.
        // Assuming global singleton: webSocketService.disconnect(); might be too aggressive here.
    });

    // Function to navigate to next chat
    async function navigateToNextChat() {
        console.debug("[Chats] Navigating to next chat");
        if (flattenedChats.length === 0) return;

        // If at the end, don't do anything
        if (currentChatIndex === flattenedChats.length - 1) return;

        // If no current chat, select first one
        if (currentChatIndex === -1) {
            currentChatIndex = 0;
        } else {
            currentChatIndex++;
        }

        const nextChat = flattenedChats[currentChatIndex];
        await handleChatClick(nextChat);
    }

    // Function to navigate to previous chat
    async function navigateToPreviousChat() {
        console.debug("[Chats] Navigating to previous chat");
        if (flattenedChats.length === 0) return;

        // If at the beginning, don't do anything
        if (currentChatIndex === 0) return;

        // If no current chat, select last one
        if (currentChatIndex === -1) {
            currentChatIndex = flattenedChats.length - 1;
        } else {
            currentChatIndex--;
        }

        const previousChat = flattenedChats[currentChatIndex];
        await handleChatClick(previousChat);
    }

    // Update currentChatIndex when a chat is clicked directly
    async function handleChatClick(chat: ChatType) {
        console.debug("[Chats] Chat clicked:", chat.id);
        currentChatIndex = flattenedChats.findIndex(c => c.id === chat.id);
        
        // Dispatch a custom event to save any pending draft before switching chats
        const saveDraftEvent = new CustomEvent('saveDraftBeforeSwitch', { bubbles: true });
        window.dispatchEvent(saveDraftEvent);
        
        // Wait a short moment for the draft to be saved
        await new Promise(resolve => setTimeout(resolve, 100));
        
        dispatch('chatSelected', { 
            // Pass the full chat object, draft is already an object or null
            chat: chat
        });
        
        if (window.innerWidth < 730) {
            handleClose();
        }
    }

    // Handle keyboard navigation events
    function handleKeyboardNavigation(event: CustomEvent) {
        if (event.type === 'nextChat') {
            navigateToNextChat();
        } else if (event.type === 'previousChat') {
            navigateToPreviousChat();
        }
    }

    // Function to handle menu close
    const handleClose = () => {
        panelState.toggleChats(); // Use the action from the central store
    };

    // Add method to update chat list
    async function updateChatList() {
        chats = await chatDB.getAllChats();
    }

    // Removed handleChatUpdate function as updates now come via WebSocket

    // Add keydown event handler for individual chat items
    function handleKeyDown(event: KeyboardEvent, chat: ChatType) {
        if (event.key === 'Enter' || event.key === ' ') {
            handleChatClick(chat);
        }
    }
</script>

{#if $authStore.isAuthenticated}
    <div class="activity-history">
        <div class="top-buttons-container">
            <div class="top-buttons">
                <!-- Enable buttons for search & hidden once features are implemented -->
                <!-- <button 
                    class="clickable-icon icon_search top-button left" 
                    aria-label={$_('activity.search.text')}
                    use:tooltip
                ></button>
                <button 
                    class="clickable-icon icon_hidden top-button center" 
                    aria-label={$_('activity.hidden.text')}
                    use:tooltip
                ></button> -->
                <button 
                    class="clickable-icon icon_close top-button right" 
                    aria-label={$_('activity.close.text')}
                    on:click={handleClose}
                    use:tooltip
                ></button>
            </div>
        </div>

        {#if loading}
            <div class="loading-indicator">{$_('activity.loading_chats.text', { default: 'Loading chats...' })}</div>
        {:else}
            <div class="chat-groups">
                {#each Object.entries(groupedChats) as [groupKey, groupChats] (groupKey)}
                    <div class="chat-group">
                        <h2 class="group-title">{getLocalizedGroupTitle(groupKey)}</h2>
                        {#each groupChats as chat (chat.id)}
                            <div 
                                role="button" 
                                tabindex="0" 
                                class="chat-item"
                                class:active={currentChatIndex === flattenedChats.findIndex(c => c.id === chat.id)}
                                on:click={() => handleChatClick(chat)} 
                                on:keydown={(e) => handleKeyDown(e, chat)}
                            >
                                <Chat {chat} />
                            </div>
                        {/each}
                    </div>
                {/each}
            </div>
        {/if}

        <KeyboardShortcuts 
            on:nextChat={handleKeyboardNavigation}
            on:previousChat={handleKeyboardNavigation}
        />
    </div>
{/if}

<style>
    .activity-history {
        padding: 0;
        position: relative;
        overflow-y: auto;
        height: 100%;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }

    .activity-history:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .activity-history::-webkit-scrollbar {
        width: 8px;
    }

    .activity-history::-webkit-scrollbar-track {
        background: transparent;
    }

    .activity-history::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid transparent;
        transition: background-color 0.2s ease;
    }

    .activity-history:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .activity-history::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }

    .top-buttons-container {
        position: sticky;
        top: 0;
        z-index: 10;
        background-color: var(--color-grey-20);
        padding: 20px;
        margin-bottom: 8px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .top-buttons {
        position: relative;
        height: 32px;
    }

    /* Position buttons in the top bar */
    .top-button {
        position: absolute;
        top: 0;
    }

    .top-button.left {
        left: 0;
    }

    .top-button.center {
        left: 50%;
        transform: translateX(-50%);
    }

    .top-button.right {
        right: 0;
    }

    .chat-groups {
        display: flex;
        flex-direction: column;
        gap: 24px;
        position: relative;
        padding: 0 0 16px 0;
    }

    .chat-group {
        display: flex;
        flex-direction: column;
        gap: 0;
    }

    .group-title {
        font-size: 0.9em;
        color: var(--color-grey-60);
        margin: 0;
        padding: 0 16px;
        font-weight: 500;
        margin-bottom: 8px;
    }

    .loading-indicator {
        text-align: center;
        padding: 20px;
        color: var(--color-grey-60);
    }

    .draft-indicator {
        display: inline-block;
        margin-left: 10px;
        padding: 2px 6px;
        background-color: var(--color-yellow-20);
        color: var(--color-yellow-90);
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: 600;
    }

    .chat-item {
        transition: background-color 0.2s ease;
    }

    .chat-item:hover,
    .chat-item.active {
        background-color: var(--color-grey-30);
        border-radius: 8px;
    }
</style>