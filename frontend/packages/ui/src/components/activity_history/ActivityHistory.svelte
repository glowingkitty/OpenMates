<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import Chat from './Chat.svelte';
    import { panelState } from '../../stores/panelStateStore'; // Import the new store
    import { authStore } from '../../stores/authStore';
    import { chatDB } from '../../services/db';
    import { webSocketService } from '../../services/websocketService'; // Import WebSocket service
    import type { Chat as ChatType, ChatListEntry } from '../../types/chat'; // Import ChatListEntry
    import { tooltip } from '../../actions/tooltip';
    import KeyboardShortcuts from '../KeyboardShortcuts.svelte';

    const dispatch = createEventDispatcher();

    let chats: ChatType[] = [];
    let loading = true;

    // Track current chat index
    let currentChatIndex = -1;

    // Modified sorting function to consider draft content
    function sortChatsInGroup(chats: ChatType[]): ChatType[] {
        return chats.sort((a, b) => {
            // Only prioritize drafts that have content
            if (a.isDraft && a.draftContent && (!b.isDraft || !b.draftContent)) return -1;
            if (b.isDraft && b.draftContent && (!a.isDraft || !a.draftContent)) return 1;
            
            // Then unread messages
            if (a.unreadCount && !b.unreadCount) return -1;
            if (!a.unreadCount && b.unreadCount) return 1;
            if (a.unreadCount && b.unreadCount) {
                if (a.unreadCount !== b.unreadCount) {
                    return b.unreadCount - a.unreadCount;
                }
            }
            
            // Finally sort by last updated
            return new Date(b.lastUpdated).getTime() - new Date(a.lastUpdated).getTime();
        });
    }

    // Modified grouping logic to include sorting
    $: groupedChats = chats.reduce<Record<string, ChatType[]>>((groups, chat) => {
        const now = new Date();
        const chatDate = new Date(chat.lastUpdated);
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
    const handleInitialSync = async (payload: { chats: ChatListEntry[], lastOpenChatId?: string }) => {
        console.debug("[ActivityHistory] Handling initial sync data:", payload);
        loading = true; // Set loading true during merge
        try {
            // 1. Fetch all chats from IndexedDB
            const localChats = await chatDB.getAllChats();
            const localChatMap = new Map<string, ChatType>(localChats.map(chat => [chat.id, chat]));
            console.debug(`[ActivityHistory] Found ${localChatMap.size} chats locally.`);

            const mergedChats: ChatType[] = [];

            // 2. Iterate through WebSocket data
            for (const serverEntry of payload.chats) {
                const serverChatId = serverEntry.id;
                const localChat = localChatMap.get(serverChatId);
                const serverLastUpdated = new Date(serverEntry.lastUpdated);

                if (localChat) {
                    // 3a. Chat exists locally - Merge based on lastUpdated
                    const localLastUpdated = new Date(localChat.lastUpdated); // Ensure it's a Date

                    // Prefer server data if it's newer or equal (server is source of truth for metadata)
                    if (serverLastUpdated >= localLastUpdated) {
                        console.debug(`[ActivityHistory] Merging server data for chat ${serverChatId} (Server newer or equal)`);
                        mergedChats.push({
                            ...localChat, // Keep local messages/draft content if any
                            ...serverEntry, // Overwrite metadata with server's
                            lastUpdated: serverLastUpdated, // Ensure Date object
                            // Keep local draft status/content unless server explicitly clears it?
                            // This needs clarification based on backend behavior. Assuming server metadata wins for now.
                            isDraft: serverEntry.isDraft ?? localChat.isDraft,
                            draftContent: serverEntry.isDraft ? localChat.draftContent : null, // Keep local draft content only if server says it's a draft
                        });
                    } else {
                        // Local data is newer? This might indicate an offline edit not yet synced.
                        // Keep local data for now, but log a warning.
                        // TODO: Consider a more robust conflict resolution strategy if needed.
                        console.warn(`[ActivityHistory] Local chat ${serverChatId} is newer than server. Keeping local version for now.`);
                        mergedChats.push(localChat);
                    }
                    localChatMap.delete(serverChatId); // Remove from map as it's processed
                } else {
                    // 3b. Chat doesn't exist locally - Add from server data
                    console.debug(`[ActivityHistory] Adding new chat ${serverChatId} from server.`);
                    mergedChats.push({
                        ...serverEntry,
                        messages: [], // No local messages for new chats
                        draftContent: null, // No local draft content
                        lastUpdated: serverLastUpdated, // Ensure Date object
                        isDraft: serverEntry.isDraft ?? false,
                    } as ChatType); // Assert type
                }
            }

            // 4. Handle chats remaining in the map (local only)
            localChatMap.forEach((localOnlyChat, chatId) => {
                if (localOnlyChat.isDraft && localOnlyChat.draftContent) {
                    // Keep local-only drafts that have content
                    console.debug(`[ActivityHistory] Keeping local-only draft ${chatId}.`);
                    mergedChats.push(localOnlyChat);
                } else {
                    // Chat exists locally but not on server, and isn't a draft with content.
                    // Assume it was deleted on the server or is an empty draft. Remove from local DB.
                    console.debug(`[ActivityHistory] Removing local-only chat ${chatId} (likely deleted on server or empty draft).`);
                    chatDB.deleteChat(chatId).catch(err => console.error(`[ActivityHistory] Failed to delete local-only chat ${chatId}:`, err));
                }
            });

            // 5. Update state (sorting happens reactively via groupedChats)
            chats = mergedChats;
            console.debug(`[ActivityHistory] Merged list contains ${chats.length} chats.`);

            // 6. Handle lastOpenChatId
            if (payload.lastOpenChatId) {
                console.debug(`[ActivityHistory] Initial sync included lastOpenChatId: ${payload.lastOpenChatId}`);
                const chatToSelect = chats.find(c => c.id === payload.lastOpenChatId);
                if (chatToSelect) {
                    console.debug(`[ActivityHistory] Found chat to select: ${chatToSelect.id}. Selecting it.`);
                    // Use setTimeout to ensure the UI has updated with the new chat list
                    // before trying to find the index and dispatching the event.
                    setTimeout(() => {
                        handleChatClick(chatToSelect);
                    }, 0);
                } else {
                    console.warn(`[ActivityHistory] lastOpenChatId ${payload.lastOpenChatId} not found in merged chat list.`);
                }
            }

        } catch (error) {
            console.error("[ActivityHistory] Error during initial sync merge:", error);
            // Fallback: Load directly from payload as before, or from DB?
            // Sticking with payload for now to ensure server state is reflected after error.
            chats = payload.chats.map(entry => ({
                ...entry,
                messages: [],
                isDraft: entry.isDraft ?? false,
                draftContent: null,
                lastUpdated: new Date(entry.lastUpdated),
            })) as ChatType[];
        } finally {
            loading = false;
        }
    };

    const handleChatAdded = (payload: ChatListEntry) => {
        console.debug("[ActivityHistory] Handling chat added:", payload);
        const newChat: ChatType = {
            ...payload,
            messages: [],
            isDraft: false,
            draftContent: null,
            lastUpdated: new Date(payload.lastUpdated),
        } as ChatType;
        chats = [newChat, ...chats]; // Add to the top (or sort later)
        chatDB.addChat(newChat); // Update local DB
    };

    const handleChatDeleted = (payload: { chatId: string }) => {
        console.debug("[ActivityHistory] Handling chat deleted:", payload);
        chats = chats.filter(chat => chat.id !== payload.chatId);
        chatDB.deleteChat(payload.chatId); // Update local DB
        // If the deleted chat was selected, deselect it
        if (currentChatIndex !== -1 && flattenedChats[currentChatIndex]?.id === payload.chatId) {
            currentChatIndex = -1;
            // Optionally select the next/previous chat or dispatch an event
            dispatch('chatDeselected');
        }
    };

    const handleChatMetadataUpdated = (payload: { chatId: string, updatedFields: Partial<ChatListEntry>, version: number }) => {
        console.debug("[ActivityHistory] Handling chat metadata updated:", payload);
        chats = chats.map(chat => {
            if (chat.id === payload.chatId) {
                // TODO: Implement version checking if needed on the client side for metadata?
                // The backend should handle version conflicts primarily.
                // Merge fields, ensuring lastUpdated is always a Date object
                const mergedFields = { ...chat, ...payload.updatedFields };
                const updatedChat: ChatType = {
                    ...mergedFields,
                    // Explicitly convert lastUpdated to Date, using the updated value if present, otherwise the original chat's value
                    lastUpdated: new Date(payload.updatedFields.lastUpdated ?? chat.lastUpdated)
                };

                chatDB.updateChat(updatedChat); // Update local DB
                return updatedChat;
            }
            return chat;
        });
        // Re-sort if necessary, e.g., if lastUpdated changed
        chats = [...chats]; // Trigger reactivity
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

        // Attempt to connect WebSocket
        try {
            console.debug("[ActivityHistory] Initializing WebSocket connection...");
            // Connect returns a promise, but we don't necessarily need to await it here.
            // The 'initial_sync_data' handler will populate chats when ready.
            // We still need a fallback if WS fails.
            webSocketService.connect().catch(err => {
                console.error("[ActivityHistory] WebSocket initial connection failed:", err);
                // Fallback to loading from DB if WS connection fails initially
                loadChatsFromDB();
            });
        } catch (error) {
            console.error("[ActivityHistory] Error initiating WebSocket connection:", error);
            loadChatsFromDB(); // Fallback on error
        }

        // Initialize DB in parallel or after WS attempt
        initializeAndLoadDB();

    });

    // Separate function for DB initialization and loading (used as fallback)
    async function initializeAndLoadDB() {
        try {
            console.debug("[ActivityHistory] Initializing database");
            await chatDB.init();

            // Load example chats only if DB is truly empty AND WS didn't provide initial data
            const checkChats = await chatDB.getAllChats();
            if (checkChats.length === 0 && chats.length === 0) { // Check both sources
                console.debug("[ActivityHistory] No existing chats in DB or from WS, loading examples");
                await chatDB.loadExampleChats();
                // Reload from DB after adding examples if WS didn't connect
                if (!webSocketService.isConnected()) {
                    chats = await chatDB.getAllChats();
                }
            } else if (chats.length === 0 && !webSocketService.isConnected()) {
                // If WS is not connected and didn't provide data, load from DB
                console.debug("[ActivityHistory] Loading chats from DB as fallback.");
                chats = await chatDB.getAllChats();
            }
        } catch (error) {
            console.error("[ActivityHistory] Error initializing/loading chats from DB:", error);
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
                console.debug("[ActivityHistory] Loading chats from DB...");
                chats = await chatDB.getAllChats();
            } catch (error) {
                console.error("[ActivityHistory] Error loading chats from DB:", error);
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

        // Optional: Disconnect WebSocket if component is destroyed?
        // Depends on whether the service should persist globally or per-component instance.
        // Assuming global singleton: webSocketService.disconnect(); might be too aggressive here.
    });

    // Function to navigate to next chat
    async function navigateToNextChat() {
        console.debug("[ActivityHistory] Navigating to next chat");
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
        console.debug("[ActivityHistory] Navigating to previous chat");
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
        console.debug("[ActivityHistory] Chat clicked:", chat.id);
        currentChatIndex = flattenedChats.findIndex(c => c.id === chat.id);
        
        // Dispatch a custom event to save any pending draft before switching chats
        const saveDraftEvent = new CustomEvent('saveDraftBeforeSwitch', { bubbles: true });
        window.dispatchEvent(saveDraftEvent);
        
        // Wait a short moment for the draft to be saved
        await new Promise(resolve => setTimeout(resolve, 100));
        
        dispatch('chatSelected', { 
            chat: {
                ...chat,
                draftContent: chat.draftContent ? 
                    (typeof chat.draftContent === 'string' ? 
                        JSON.parse(chat.draftContent) : 
                        chat.draftContent
                    ) : null
            } 
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
        panelState.toggleActivityHistory(); // Use the action from the central store
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