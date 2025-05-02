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
    // Assuming backend sends data compatible with ChatListItem for the list part.
    const handleInitialSync = async (payload: { chats: ChatListItem[], lastOpenChatId?: string }) => {
    	console.debug("[Chats] Handling initial sync data:", payload);
    	try {
    		// 1. Get IDs of chats currently in the DB for efficient checking
    		const localDbChats = await chatDB.getAllChats(); // Fetch once for efficiency
    		const localDbChatMap = new Map<string, ChatType>(localDbChats.map(chat => [chat.id, chat]));
    		console.debug(`[Chats] Found ${localDbChatMap.size} chats in DB before sync.`);
   
    		let dbChanged = false; // Track if any DB operation occurred
   
    		// 2. Iterate through WebSocket data
    		for (const serverEntry of payload.chats) {
    			const serverChatId = serverEntry.id;
    			const localChat = localDbChatMap.get(serverChatId);
    			const serverTimestamp = serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : new Date(0);
   
    			if (localChat) {
    				// 3a. Chat exists locally - Merge based on timestamp
    				const localTimestamp = localChat.updatedAt ?? (localChat.lastMessageTimestamp ?? new Date(0));
   
    				if (serverTimestamp >= localTimestamp) {
    					console.debug(`[Chats] Updating DB for chat ${serverChatId} from server list entry (Server newer or equal)`);
    					const updatedChat: ChatType = {
    						...localChat, // Keep local messages, draft, version etc.
    						id: serverEntry.id,
    						title: serverEntry.title, // Update title from server list entry
    						lastMessageTimestamp: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : null,
    						updatedAt: serverTimestamp > localTimestamp ? serverTimestamp : localTimestamp,
    						// Keep existing isPersisted status unless explicitly updated by another event
    						isPersisted: localChat.isPersisted,
    						// Keep existing version, messages, draft, mates, unreadCount etc.
    					};
    					await chatDB.updateChat(updatedChat); // Update DB
    					dbChanged = true;
    				} else {
    					console.warn(`[Chats] Local chat ${serverChatId} is newer than server list entry. Keeping local DB version.`);
    				}
    				localDbChatMap.delete(serverChatId); // Remove from map as it's processed
    			} else {
    				// 3b. Chat doesn't exist locally - Add minimal entry to DB from server data
    				console.debug(`[Chats] Adding new chat ${serverChatId} to DB from server list entry.`);
    				const now = new Date();
    				const newChat: ChatType = {
    					id: serverEntry.id,
    					title: serverEntry.title,
    					draft: null,
    					version: 1, // Assume version 1 for list entry sync
    					messages: [],
    					createdAt: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : now,
    					updatedAt: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : now,
    					lastMessageTimestamp: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : null,
    					isPersisted: false, // Assume not persisted if just from list entry
    					mates: [],
    					unreadCount: 0,
    				};
    				await chatDB.addChat(newChat); // Add to DB
    				dbChanged = true;
    			}
    		}
   
    		// 4. Handle chats remaining in the map (local only in DB)
    		localDbChatMap.forEach((localOnlyChat, chatId) => {
    			console.debug(`[Chats] Keeping local-only chat ${chatId} in DB (not present in initial sync).`);
    			// No DB action needed, they remain in the DB.
    		});
   
    		// 5. Update UI state from DB if changes occurred
    		if (dbChanged) {
    			console.debug("[Chats] DB changed during initial sync, reloading list for UI.");
    			await updateChatList(); // Reload chats state from DB
    		} else {
    			console.debug("[Chats] No DB changes during initial sync.");
    		}
   
    		// 6. Handle lastOpenChatId (check against the potentially updated list)
    		if (payload.lastOpenChatId) {
    			console.debug(`[Chats] Initial sync included lastOpenChatId: ${payload.lastOpenChatId}`);
    			// Use the 'chats' state variable which might have been updated by updateChatList()
    			const chatToSelect = chats.find(c => c.id === payload.lastOpenChatId);
    			if (chatToSelect) {
    				console.debug(`[Chats] Found chat to select: ${chatToSelect.id}. Selecting it.`);
    				setTimeout(() => {
    					handleChatClick(chatToSelect);
    				}, 0); // setTimeout still useful for UI updates
    			} else {
    				console.warn(`[Chats] lastOpenChatId ${payload.lastOpenChatId} not found in current chat list state.`);
    			}
    		}
   
    	} catch (error) {
    		console.error("[Chats] Error during initial sync DB operations:", error);
    		// Attempt to load from DB as a fallback if sync fails badly
    		await updateChatList();
    	}
    };

    // Adjust payload type to align with ChatResponse from backend spec
    // Assuming the backend sends a ChatResponse object for 'chat_added' events
    const handleChatAdded = async (payload: { // <<< Added async
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

        try {
        	// Avoid adding duplicates by checking the DB first
        	const existingChat = await chatDB.getChat(newChat.id);
        	if (!existingChat) {
        		await chatDB.addChat(newChat); // Add to local DB
        		console.debug(`[Chats] Added new chat/draft entry to DB: ${newChat.id}`);
        		await updateChatList(); // Refresh UI from DB
        	} else {
        		console.warn(`[Chats] Chat/Draft with ID ${newChat.id} already exists in DB. Skipping add.`);
        		// Optionally, update the existing DB entry if the incoming data is newer/better
        		// For now, just prevent duplication.
        	}
        } catch (error) {
        	console.error(`[Chats] Error adding chat ${newChat.id} to DB:`, error);
        }
       };
      
       const handleChatDeleted = async (payload: { chatId: string }) => { // <<< Added async
        console.debug("[Chats] Handling chat deleted:", payload);
        try {
        	// Check if the deleted chat is currently selected *before* deleting from DB and updating list
        	const chatWasSelected = currentChatIndex !== -1 && flattenedChats[currentChatIndex]?.id === payload.chatId;
      
        	await chatDB.deleteChat(payload.chatId); // Delete from local DB
        	console.debug(`[Chats] Deleted chat ${payload.chatId} from DB.`);
        	await updateChatList(); // Refresh UI from DB
      
        	// If the deleted chat was selected, deselect it
        	if (chatWasSelected) {
        		console.debug(`[Chats] Deselecting deleted chat ${payload.chatId}.`);
        		currentChatIndex = -1;
        		dispatch('chatDeselected');
        		// Optionally select the next/previous chat here if needed
        	}
        } catch (error) {
        	console.error(`[Chats] Error deleting chat ${payload.chatId} from DB:`, error);
        }
       };
      
       // Update payload type to use ChatListItem
       const handleChatMetadataUpdated = async (payload: { chatId: string, updatedFields: Partial<ChatListItem>, version: number }) => { // <<< Added async
        console.debug("[Chats] Handling chat metadata updated:", payload);
        try {
        	const existingChat = await chatDB.getChat(payload.chatId);
        	if (existingChat) {
        		// The backend handles version conflicts for metadata updates.
        		// We trust the incoming payload and update the local version.
        		const updatedChat: ChatType = {
        			...existingChat, // Start with existing DB chat data
        			// Apply specific updatable fields from ChatListItem structure in payload.updatedFields
        			title: payload.updatedFields.title ?? existingChat.title, // Update title if provided
        			// Update updatedAt based on lastMessageTimestamp from ChatListItem payload, fallback to now
        			updatedAt: payload.updatedFields.lastMessageTimestamp ? new Date(payload.updatedFields.lastMessageTimestamp) : new Date(),
        			// Update lastMessageTimestamp if provided
        			lastMessageTimestamp: payload.updatedFields.lastMessageTimestamp ? new Date(payload.updatedFields.lastMessageTimestamp) : existingChat.lastMessageTimestamp,
        			// Update unreadCount based on hasUnread flag if provided
        			// Note: This logic might need refinement based on exact backend behavior for hasUnread
        			unreadCount: payload.updatedFields.hasUnread !== undefined
        				? (payload.updatedFields.hasUnread ? (existingChat.unreadCount ?? 0) + 1 : 0)
        				: existingChat.unreadCount,
        			// Update the version number from the payload
        			version: payload.version,
        			// Keep existing draft, messages, mates, isPersisted, createdAt etc.
        		};
      
        		await chatDB.updateChat(updatedChat); // Update local DB
        		console.debug(`[Chats] Updated metadata in DB for chat ${payload.chatId}.`);
        		await updateChatList(); // Refresh UI from DB
        	} else {
        		console.warn(`[Chats] Received metadata update for non-existent chat ${payload.chatId}. Ignoring.`);
        		// Optionally, could treat this as a 'chat_added' event if appropriate
        	}
        } catch (error) {
        	console.error(`[Chats] Error updating metadata for chat ${payload.chatId} in DB:`, error);
        }
       };
      
       // Handler for successful draft updates confirmed by the server
       const handleDraftUpdated = async (payload: { chatId: string, content: Record<string, any> | null, basedOnVersion: number }) => { // <<< Added async
       	console.debug("[Chats] Handling draft updated confirmation:", payload);
       	try {
       		const existingChat = await chatDB.getChat(payload.chatId);
        	if (existingChat) {
        		const updatedChat: ChatType = {
        			...existingChat,
        			draft: payload.content, // Update draft content (can be null)
        			version: payload.basedOnVersion, // Update version to the new confirmed version
        			updatedAt: new Date() // Update timestamp
        		};
        		await chatDB.updateChat(updatedChat); // Update local DB
        		console.debug(`[Chats] Updated draft in DB for chat ${payload.chatId} to version ${payload.basedOnVersion}.`);
        		await updateChatList(); // Refresh UI from DB
        	} else {
        		console.warn(`[Chats] Received draft update confirmation for non-existent chat ${payload.chatId}. Ignoring.`);
        	}
        } catch (error) {
        	console.error(`[Chats] Error updating draft for chat ${payload.chatId} in DB:`, error);
        }
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

    onMount(async () => {
        // Remove old event listener
        // window.addEventListener('chatUpdated', handleChatUpdate);

        // Add language change event listener
        languageChangeHandler = () => {
            // Force re-render of the chat groups by triggering a state update
            chats = [...chats];
        };
        window.addEventListener('language-changed', languageChangeHandler);

        // Register WebSocket handlers *before* connecting
        webSocketService.on('initial_sync_data', handleInitialSync);
        webSocketService.on('chat_added', handleChatAdded);
        webSocketService.on('chat_deleted', handleChatDeleted);
        webSocketService.on('chat_metadata_updated', handleChatMetadataUpdated);
        webSocketService.on('draft_updated', handleDraftUpdated); // Register new handler
        webSocketService.on('draft_conflict', handleDraftConflict); // Register new handler

        // 1. Initialize DB and load initial chats from it FIRST
        await initializeAndLoadDB();

        // 2. Attempt to connect WebSocket AFTER DB load
        if ($authStore.isAuthenticated) { // Only connect if authenticated
            try {
                console.debug("[Chats] Initializing WebSocket connection...");
                // Connect returns a promise. We don't necessarily need to await it here,
                // as the 'initial_sync_data' handler will merge data when it arrives.
                // Error handling within connect() manages retries and status updates.
                webSocketService.connect().catch(err => {
                    // The connect method itself handles logging and setting status to 'failed'
                    console.error("[Chats] WebSocket initial connection promise rejected:", err);
                    // No need to call loadChatsFromDB here, as it was already called by initializeAndLoadDB
                });
            } catch (error) {
                console.error("[Chats] Error initiating WebSocket connection:", error);
                // No need to call loadChatsFromDB here
            }
        } else {
            console.debug("[Chats] User not authenticated, skipping WebSocket connection.");
        }
    });

    // Simplified function for DB initialization and loading
    async function initializeAndLoadDB() {
        loading = true; // Set loading true at the start of DB load
        try {
            console.debug("[Chats] Initializing database and loading chats...");
            await chatDB.init();
            // Always load chats from DB initially
            chats = await chatDB.getAllChats();
            console.debug(`[Chats] Loaded ${chats.length} chats from DB.`);
        } catch (error) {
            console.error("[Chats] Error initializing/loading chats from DB:", error);
            chats = []; // Ensure chats is an empty array on error
        } finally {
            loading = false; // Set loading false after DB load attempt (success or fail)
        }
    }

    // loadChatsFromDB function is no longer needed as a separate fallback,
    // initializeAndLoadDB handles the primary load.
    // async function loadChatsFromDB() { ... } // REMOVED

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