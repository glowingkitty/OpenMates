<script lang="ts">
	import { onMount, onDestroy, createEventDispatcher } from 'svelte';
	import { _ } from 'svelte-i18n';
	import Chat from './Chat.svelte';
	import { panelState } from '../../stores/panelStateStore';
	import { authStore } from '../../stores/authStore';
	import { chatDB } from '../../services/db';
	import { webSocketService } from '../../services/websocketService';
	import { LOCAL_CHAT_LIST_CHANGED_EVENT, draftState } from '../../services/draftService'; // Corrected import path
	import type { Chat as ChatType, ChatListItem } from '../../types/chat'; // ChatListItem is used here
	import { tooltip } from '../../actions/tooltip';
	import KeyboardShortcuts from '../KeyboardShortcuts.svelte';

	const dispatch = createEventDispatcher();

	let chats: ChatType[] = [];
	let loading = true;
	let selectedChatId: string | null = null;
	let _chatIdToSelectAfterUpdate: string | null = null; // Stores the ID of a newly created chat to select

	// ... (sortChatsInGroup, groupedChats, getLocalizedGroupTitle, flattenedChats remain the same) ...
	function sortChatsInGroup(chatsToSort: ChatType[]): ChatType[] {
        return [...chatsToSort].sort((a, b) => { // Create a shallow copy before sorting
            // Handle potential null/undefined dates gracefully
            const aTime = (a.updatedAt ?? a.createdAt)?.getTime() ?? 0;
            const bTime = (b.updatedAt ?? b.createdAt)?.getTime() ?? 0;

            // Prioritize drafts (non-persisted chats with draft content OR persisted chats with draft content newer than last message)
            // A simpler definition: prioritize any chat with non-null draft content.
            const aHasDraft = a.draft !== null && a.draft !== undefined;
            const bHasDraft = b.draft !== null && b.draft !== undefined;

            if (aHasDraft && !bHasDraft) return -1;
            if (bHasDraft && !aHasDraft) return 1;

            // If both have drafts or both don't, sort by updatedAt/createdAt (most recent first)
            return bTime - aTime;
        });
    }

    $: groupedChats = chats.reduce<Record<string, ChatType[]>>((groups, chat) => {
        const now = new Date();
        const chatDate = chat.updatedAt ?? chat.createdAt;
        if (!chatDate || !(chatDate instanceof Date) || isNaN(chatDate.getTime())) {
            console.warn(`[Chats] Chat ${chat.id} has invalid date for grouping. Placing in 'today'.`);
            const groupKey = 'today';
             if (!groups[groupKey]) { groups[groupKey] = []; }
             groups[groupKey].push(chat);
            return groups;
        }
        const diffDays = Math.floor((now.getTime() - chatDate.getTime()) / (1000 * 60 * 60 * 24));

        let groupKey: string;
        if (diffDays < 0) { groupKey = 'today'; }
        else if (diffDays === 0) { groupKey = 'today'; }
        else if (diffDays === 1) { groupKey = 'yesterday'; }
        else { groupKey = `days_ago_${diffDays}`; }

        if (!groups[groupKey]) { groups[groupKey] = []; }
        groups[groupKey].push(chat);
        return groups;
    }, {});

    function getLocalizedGroupTitle(groupKey: string): string {
        if (groupKey === 'today') { return $_('activity.today.text'); }
        else if (groupKey === 'yesterday') { return $_('activity.yesterday.text'); }
        else if (groupKey.startsWith('days_ago_')) {
            const days = groupKey.split('_')[2];
            return $_('activity.days_ago.text', { values: { days } });
        }
        return groupKey;
    }

    $: flattenedChats = chats;

	let languageChangeHandler: () => void;
	let handleLocalChatListChange: () => void;


	let unsubscribeDraftState: (() => void) | null = null; // Declare here for wider scope

	let handleGlobalChatSelectedEvent: (event: Event) => void;
	let handleGlobalChatDeselectedEvent: (event: Event) => void;

	// --- WebSocket Handlers ---

	const handleInitialSync = async (payload: { chats: ChatListItem[], lastOpenChatId?: string }) => {
		console.debug("[Chats] Handling initial sync data:", payload);
		try {
			const localDbChats = await chatDB.getAllChats();
			const localDbChatMap = new Map<string, ChatType>(localDbChats.map(chat => [chat.id, chat]));
			console.debug(`[Chats] Found ${localDbChatMap.size} chats in DB before sync.`);

			let dbChanged = false;

			for (const serverEntry of payload.chats) { // serverEntry is type ChatListItem
				const serverChatId = serverEntry.id;
				const localChat = localDbChatMap.get(serverChatId);

				// --- START CORRECTION ---
				// Use lastMessageTimestamp from ChatListItem as the server's update time indicator
				const serverUpdateTime = serverEntry.lastMessageTimestamp
					? new Date(serverEntry.lastMessageTimestamp)
					: new Date(0); // Use epoch if null/undefined
                // --- END CORRECTION ---

				if (localChat) {
					// Compare server update time with local update time (use local updatedAt first, fallback to lastMessageTimestamp)
					const localUpdateTime = localChat.updatedAt ?? (localChat.lastMessageTimestamp ?? new Date(0));

					// If server list entry's timestamp is newer or equal, update relevant local metadata
					if (serverUpdateTime >= localUpdateTime) {
						console.debug(`[Chats] Sync: Updating metadata for chat ${serverChatId} from server list entry.`);
						const updatedChat: ChatType = {
							...localChat,
							id: serverEntry.id, // Ensure client UUID is used
							user_id: serverEntry.user_id ?? localChat.user_id, // Update user_id
							title: serverEntry.title ?? localChat.title ?? '',
							updatedAt: serverUpdateTime > new Date(0) ? serverUpdateTime : localChat.updatedAt,
							lastMessageTimestamp: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : localChat.lastMessageTimestamp,
					                       draft: serverEntry.draft !== undefined ? serverEntry.draft : localChat.draft,
						};
						await chatDB.updateChat(updatedChat);
						dbChanged = true;
					} else {
						 console.debug(`[Chats] Sync: Local chat ${serverChatId} is newer than server list entry. Keeping local DB version.`);
					}
					localDbChatMap.delete(serverChatId); // Remove from map as it's processed
				} else {
					// Chat doesn't exist locally - Add minimal entry from server data
					console.debug(`[Chats] Sync: Adding new chat ${serverChatId} to DB from server list entry.`);
					const now = new Date();
					const newChat: ChatType = {
						id: serverEntry.id, // Client UUID
						user_id: serverEntry.user_id, // Server user_id part
						title: serverEntry.title ?? '',
						draft: serverEntry.draft ?? null,
						createdAt: serverUpdateTime > new Date(0) ? serverUpdateTime : now,
						updatedAt: serverUpdateTime > new Date(0) ? serverUpdateTime : now,
						lastMessageTimestamp: serverEntry.lastMessageTimestamp ? new Date(serverEntry.lastMessageTimestamp) : null,
						version: 1,
						messages: [],
						isPersisted: !!serverEntry.user_id, // Persisted if user_id is present
						mates: [],
						unreadCount: 0,
					};
					await chatDB.addChat(newChat);
					dbChanged = true;
				}
			}

			// Handle local-only chats (optional: mark as potentially needing sync up?)
			localDbChatMap.forEach((localOnlyChat, chatId) => {
				console.debug(`[Chats] Sync: Keeping local-only chat ${chatId} in DB.`);
			});

			if (dbChanged) {
				console.debug("[Chats] DB changed during initial sync, reloading list for UI.");
				await updateChatList(); // Reload chats state from DB
			} else {
				console.debug("[Chats] No DB changes during initial sync needed based on timestamps.");
				// Ensure list is still up-to-date even if no DB changes occurred during sync
				await updateChatList();
			}

			// Handle lastOpenChatId after list is potentially updated
			if (payload.lastOpenChatId) {
				console.debug(`[Chats] Initial sync included lastOpenChatId: ${payload.lastOpenChatId}`);
				const chatToSelect = chats.find(c => c.id === payload.lastOpenChatId);
				if (chatToSelect) {
					console.debug(`[Chats] Found chat to select: ${chatToSelect.id}. Selecting it.`);
					requestAnimationFrame(() => { // Use rAF for smoother UI update
						handleChatClick(chatToSelect);
					});
				} else {
					console.warn(`[Chats] lastOpenChatId ${payload.lastOpenChatId} not found in current chat list state.`);
				}
			}

		} catch (error) {
			console.error("[Chats] Error during initial sync DB operations:", error);
			await updateChatList(); // Attempt to load from DB as a fallback
		}
	};

	// ... (handleChatAdded, handleChatDeleted, handleChatMetadataUpdated remain the same) ...
	// Note: handleChatMetadataUpdated correctly expects an intersection type that *can* include updatedAt
	const handleChatAdded = async (payload: ChatType) => { // Assuming payload matches ChatType or is adaptable
        console.debug("[Chats] Handling chat added:", payload);
        try {
            // Adapt payload to ChatType if needed (e.g., convert date strings)
            const newChat: ChatType = {
                ...payload, // payload is ChatType, so id and user_id are already there
                createdAt: new Date(payload.createdAt),
                updatedAt: new Date(payload.updatedAt),
                lastMessageTimestamp: payload.lastMessageTimestamp ? new Date(payload.lastMessageTimestamp) : null,
                messages: payload.messages?.map(msg => ({ ...msg, createdAt: new Date(msg.createdAt) })) ?? [],
                title: payload.title ?? '',
                draft: payload.draft ?? null,
                version: payload.version ?? 1,
                // isPersisted should be true if user_id is present, or based on existing logic
                isPersisted: !!payload.user_id || payload.isPersisted || (payload.messages?.length > 0),
                mates: payload.mates ?? [],
                unreadCount: payload.unreadCount ?? 0,
                // Ensure user_id from payload is preserved
                user_id: payload.user_id,
            };

        	const existingChat = await chatDB.getChat(newChat.id);
        	if (!existingChat) {
        		await chatDB.addChat(newChat);
        		console.debug(`[Chats] Added new chat entry to DB: ${newChat.id}`);
        		await updateChatList(); // Refresh UI from DB
        	} else {
        		console.warn(`[Chats] Chat with ID ${newChat.id} already exists in DB. Updating existing.`);
                // Optionally merge/update if incoming data is newer
                await chatDB.updateChat(newChat); // Overwrite existing with server data
                await updateChatList();
        	}
        } catch (error) {
        	console.error(`[Chats] Error adding/updating chat ${payload.id} to DB:`, error);
        }
    };

    const handleChatDeleted = async (payload: { chatId: string }) => {
        console.debug("[Chats] Handling chat deleted:", payload);
        try {
            const chatToDelete = chats.find(c => c.id === payload.chatId); // Find before deleting
            const chatWasSelected = selectedChatId === payload.chatId;

        	await chatDB.deleteChat(payload.chatId);
        	console.debug(`[Chats] Deleted chat ${payload.chatId} from DB.`);
        	await updateChatList(); // Refresh UI from DB

        	if (chatWasSelected) {
        		console.debug(`[Chats] Deselecting deleted chat ${payload.chatId}.`);
        		selectedChatId = null; // Clear selection
        		dispatch('chatDeselected');
        	}
        } catch (error) {
        	console.error(`[Chats] Error deleting chat ${payload.chatId} from DB:`, error);
        }
    };

    // Assuming server sends: { id: string (clientUUID), user_id?: string, updatedFields: { ... } }
    const handleChatMetadataUpdated = async (payload: { id: string, user_id?: string, updatedFields: Partial<Omit<ChatListItem, 'id'|'user_id'> & { version: number, updatedAt: string | Date, draft?: Record<string, any>|null } >}) => {
    	console.debug("[Chats] Handling chat metadata updated:", payload);
    	try {
    		const existingChat = await chatDB.getChat(payload.id); // Use payload.id (client UUID)
    		if (existingChat) {
    			const updatedChat: ChatType = {
    				...existingChat,
    				id: payload.id, // Ensure client UUID is primary
    				user_id: payload.user_id ?? existingChat.user_id, // Update user_id
    				title: payload.updatedFields.title ?? existingChat.title,
                    updatedAt: payload.updatedFields.updatedAt ? new Date(payload.updatedFields.updatedAt) : (payload.updatedFields.lastMessageTimestamp ? new Date(payload.updatedFields.lastMessageTimestamp) : existingChat.updatedAt),
                    lastMessageTimestamp: payload.updatedFields.lastMessageTimestamp ? new Date(payload.updatedFields.lastMessageTimestamp) : existingChat.lastMessageTimestamp,
                    version: payload.updatedFields.version ?? existingChat.version,
                    draft: payload.updatedFields.draft !== undefined ? payload.updatedFields.draft : existingChat.draft,
                    isPersisted: !!(payload.user_id ?? existingChat.user_id) || existingChat.isPersisted, // Update persisted status
    			};
   
    			await chatDB.updateChat(updatedChat);
    			console.debug(`[Chats] Updated metadata in DB for chat ${payload.id}.`);
    			await updateChatList();
    		} else {
    			console.warn(`[Chats] Received metadata update for non-existent chat ${payload.id}. Ignoring.`);
    		}
    	} catch (error) {
    		console.error(`[Chats] Error updating metadata for chat ${payload.id} in DB:`, error);
    	}
    };

	// ... (handleDraftUpdatedWS, handleDraftConflictWS remain the same - commented out/logging only) ...
    const handleDraftUpdatedWS = async (payload: { chatId: string, content: Record<string, any> | null, basedOnVersion: number }) => {
        console.debug("[Chats] Handling draft updated confirmation via WS:", payload);
        // Relying on draftService event + updateChatList for actual update
    };

    const handleDraftConflictWS = (payload: { chatId: string, draftId?: string }) => {
        console.warn(`[Chats] Draft conflict detected via WS for chat ${payload.chatId}. Local draft might be stale. Payload:`, payload);
        // TODO: Add visual indicator?
    };

	// ... (onMount, initializeAndLoadDB, onDestroy remain the same) ...
	onMount(async () => {
	       languageChangeHandler = () => {
	           console.debug('[Chats] Language changed, updating list.');
	           updateChatList();
	       };
	       window.addEventListener('language-changed', languageChangeHandler);

	       handleLocalChatListChange = () => {
	           console.debug('[Chats] Detected local chat list change via event, updating list.');
	           updateChatList();
	       };
	       window.addEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChange);

	  // Subscribe to draftState to know when a new chat should be selected
	  unsubscribeDraftState = draftState.subscribe(value => { // Assign to the top-level variable
	   if (value.newlyCreatedChatIdToSelect) {
	    console.debug(`[Chats] draftState signals new chat to select: ${value.newlyCreatedChatIdToSelect}`);
	    _chatIdToSelectAfterUpdate = value.newlyCreatedChatIdToSelect;
	    // Reset the value in the store so it's a one-time trigger
	    draftState.update(s => ({ ...s, newlyCreatedChatIdToSelect: null }));
	    // Attempt to select immediately if list might already contain it,
	    // or updateChatList will pick it up.
	    // This also helps if updateChatList was called by LOCAL_CHAT_LIST_CHANGED_EVENT
	    // just before this subscription fired.
	    const chatToSelect = flattenedChats.find(c => c.id === _chatIdToSelectAfterUpdate);
	    if (chatToSelect) {
	     handleChatClick(chatToSelect);
	     _chatIdToSelectAfterUpdate = null; // Consumed
	    } else {
	     // If not found, updateChatList will try to select it after refresh
	     console.debug('[Chats] New chat not in current list, will attempt selection after next list update.');
	    }
	   }
	  });

	       handleGlobalChatSelectedEvent = (event: Event) => {
	           const customEvent = event as CustomEvent<{ chat: ChatType }>;
	           if (customEvent.detail && customEvent.detail.chat && customEvent.detail.chat.id) {
	               const newChatId = customEvent.detail.chat.id;
	               const chatFromEventDetail = customEvent.detail.chat;
	               console.debug(`[Chats] Global chat selected event received for chat ID: ${newChatId}`);

	               const selectAndDispatch = (chatToSelect: ChatType | undefined) => {
	                   if (chatToSelect) {
	                       selectedChatId = chatToSelect.id;
	                       dispatch('chatSelected', { chat: chatToSelect });
	                       console.debug(`[Chats] Dispatched chatSelected for ${chatToSelect.id}`);
	                   } else {
	                       console.warn(`[Chats] Chat ${newChatId} could not be found to select and dispatch.`);
	                       // Fallback to event detail if absolutely necessary, though ideally it should be found
	                       selectedChatId = newChatId;
	                       dispatch('chatSelected', { chat: chatFromEventDetail });
	                       console.debug(`[Chats] Dispatched chatSelected (fallback) for ${newChatId}`);
	                   }
	               };

	               let chatInCurrentList = flattenedChats.find(c => c.id === newChatId);

	               if (!chatInCurrentList) {
	                   console.debug(`[Chats] Chat ${newChatId} not in current list. Updating list...`);
	                   updateChatList().then(() => {
	                       chatInCurrentList = flattenedChats.find(c => c.id === newChatId);
	                       selectAndDispatch(chatInCurrentList);
	                   }).catch(error => {
	                       console.error(`[Chats] Error updating list for global selection:`, error);
	                          // Attempt fallback even on error
	                          selectAndDispatch(undefined); // This will use chatFromEventDetail
	                      });
	               } else {
	                   console.debug(`[Chats] Chat ${newChatId} found in current list. Selecting.`);
	                   selectAndDispatch(chatInCurrentList);
	               }
	           } else {
	               console.warn('[Chats] Global chat selected event received without valid chat detail.');
	           }
	       };
	       window.addEventListener('globalChatSelected', handleGlobalChatSelectedEvent);

	       handleGlobalChatDeselectedEvent = () => {
	           console.debug('[Chats] Global chat deselected event received.');
	           selectedChatId = null;
	           dispatch('chatDeselected'); // Notify other components if needed
	       };
	       window.addEventListener('globalChatDeselected', handleGlobalChatDeselectedEvent);

	       // Register WebSocket handlers
        webSocketService.on('initial_sync_data', handleInitialSync);
        webSocketService.on('chat_added', handleChatAdded);
        webSocketService.on('chat_deleted', handleChatDeleted);
        webSocketService.on('chat_metadata_updated', handleChatMetadataUpdated);
        // webSocketService.on('draft_updated', handleDraftUpdatedWS); // Optional
        webSocketService.on('draft_conflict', handleDraftConflictWS);

        await initializeAndLoadDB();

        if ($authStore.isAuthenticated) {
            try {
                console.debug("[Chats] Initializing WebSocket connection...");
                webSocketService.connect().catch(err => {
                    console.error("[Chats] WebSocket initial connection promise rejected:", err);
                });
            } catch (error) {
                console.error("[Chats] Error initiating WebSocket connection:", error);
            }
        } else {
            console.debug("[Chats] User not authenticated, skipping WebSocket connection.");
        }
    });

    async function initializeAndLoadDB() {
        loading = true;
        try {
            console.debug("[Chats] Initializing database and loading chats...");
            await chatDB.init();
            await updateChatList();
            console.debug(`[Chats] Initial load complete. Found ${chats.length} chats.`);
        } catch (error) {
            console.error("[Chats] Error initializing/loading chats from DB:", error);
            chats = [];
        } finally {
            loading = false;
        }
    }

    onDestroy(() => {
    	window.removeEventListener('language-changed', languageChangeHandler);
    	if (handleLocalChatListChange) {
    		window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChange);
    	}
    	if (unsubscribeDraftState) unsubscribeDraftState(); // Unsubscribe from draftState
   
    	if (handleGlobalChatSelectedEvent) {
    		window.removeEventListener('globalChatSelected', handleGlobalChatSelectedEvent);
    	}
    	if (handleGlobalChatDeselectedEvent) {
    		window.removeEventListener('globalChatDeselected', handleGlobalChatDeselectedEvent);
    	}
   
    	// Unregister WebSocket handlers
        webSocketService.off('initial_sync_data', handleInitialSync);
        webSocketService.off('chat_added', handleChatAdded);
        webSocketService.off('chat_deleted', handleChatDeleted);
        webSocketService.off('chat_metadata_updated', handleChatMetadataUpdated);
        // webSocketService.off('draft_updated', handleDraftUpdatedWS);
        webSocketService.off('draft_conflict', handleDraftConflictWS);
    });

	// ... (navigateToNextChat, navigateToPreviousChat, handleChatClick, handleKeyboardNavigation, handleClose remain the same) ...
	async function navigateToNextChat() {
        console.debug("[Chats] Navigating to next chat");
        if (flattenedChats.length === 0) return;
        if (flattenedChats.length === 0) return;
        const currentIndex = selectedChatId ? flattenedChats.findIndex(c => c.id === selectedChatId) : -1;
        let nextIndex = currentIndex + 1;

        if (currentIndex === -1 && flattenedChats.length > 0) { // If nothing selected, select first
            nextIndex = 0;
        } else if (nextIndex >= flattenedChats.length) {
            nextIndex = flattenedChats.length - 1; // Stay at last item
        }

        if (nextIndex < 0) nextIndex = 0; // Ensure index is not negative

        if (flattenedChats[nextIndex] && flattenedChats[nextIndex].id !== selectedChatId) {
             const nextChat = flattenedChats[nextIndex];
             if (nextChat) await handleChatClick(nextChat);
        }
    }

    async function navigateToPreviousChat() {
        console.debug("[Chats] Navigating to previous chat");
        if (flattenedChats.length === 0) return;
        if (flattenedChats.length === 0) return;
        const currentIndex = selectedChatId ? flattenedChats.findIndex(c => c.id === selectedChatId) : -1;
        let prevIndex = currentIndex - 1;

        if (currentIndex === -1 && flattenedChats.length > 0) { // If nothing selected, select last (or first if preferred)
            prevIndex = 0; // Or flattenedChats.length - 1; let's stick to first for now
        } else if (prevIndex < 0) {
             prevIndex = 0; // Stay at first item
        }

        if (flattenedChats[prevIndex] && flattenedChats[prevIndex].id !== selectedChatId) {
            const previousChat = flattenedChats[prevIndex];
            if (previousChat) await handleChatClick(previousChat);
        }
    }

    async function handleChatClick(chat: ChatType) {
        console.debug("[Chats] Chat clicked:", chat.id);
        selectedChatId = chat.id;
        dispatch('chatSelected', { chat: chat });
        if (window.innerWidth < 730) {
            handleClose();
        }
    }

    function handleKeyboardNavigation(event: CustomEvent) {
        if (event.type === 'nextChat') { navigateToNextChat(); }
        else if (event.type === 'previousChat') { navigateToPreviousChat(); }
    }

    const handleClose = () => { panelState.toggleChats(); };

	// ... (updateChatList, handleKeyDown remain the same) ...
	async function updateChatList() {
        console.debug("[Chats] Updating chat list from DB...");
        const previouslySelectedChatId = selectedChatId;

        try {
            const allChatsFromDb = await chatDB.getAllChats();
            chats = sortChatsInGroup(allChatsFromDb); // Updates reactive `chats` and triggers `flattenedChats` update
            console.debug(`[Chats] Updated chat list state. Count: ${chats.length}`);
         
            // Attempt to select a newly created chat if its ID was signaled
            if (_chatIdToSelectAfterUpdate) {
            	const chatToSelect = flattenedChats.find(c => c.id === _chatIdToSelectAfterUpdate);
            	if (chatToSelect) {
            		console.debug(`[Chats] Selecting newly created chat after list update: ${_chatIdToSelectAfterUpdate}`);
            		await handleChatClick(chatToSelect); // Make sure this is awaited if handleChatClick is async
            		_chatIdToSelectAfterUpdate = null; // Consumed
            		// Early exit here as we've handled selection
            		return;
            	} else {
            		console.warn(`[Chats] Newly created chat ID ${_chatIdToSelectAfterUpdate} not found in list after update.`);
            		_chatIdToSelectAfterUpdate = null; // Reset as it's not found
            	}
            }
         
            // Check if the previously selected chat still exists (and wasn't just selected above)
            if (previouslySelectedChatId && selectedChatId !== previouslySelectedChatId) {
            	const stillExists = flattenedChats.some(c => c.id === previouslySelectedChatId);
            	if (stillExists) {
            		selectedChatId = previouslySelectedChatId;
            	} else {
            		console.debug(`[Chats] Previously selected chat ${previouslySelectedChatId} not found after update. Deselecting.`);
            		selectedChatId = null;
            		dispatch('chatDeselected'); // Inform other components
            	}
            } else if (!selectedChatId) { // If nothing is selected (e.g. initial load, or previous deselected)
            	selectedChatId = null;
            }
           } catch (error) {
            console.error("[Chats] Error updating chat list from DB:", error);
            chats = [];
            selectedChatId = null;
        }
    }

    function handleKeyDown(event: KeyboardEvent, chat: ChatType) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleChatClick(chat);
        }
    }

</script>

<!-- Template remains the same -->
{#if $authStore.isAuthenticated}
    <div class="activity-history">
        <div class="top-buttons-container">
            <div class="top-buttons">
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
                                class:active={selectedChatId === chat.id}
                                on:click={() => handleChatClick(chat)}
                                on:keydown={(e) => handleKeyDown(e, chat)}
                                aria-current={selectedChatId === chat.id ? 'page' : undefined}
                            >
                                <Chat {chat} />
                            </div>
                        {/each}
                    </div>
                {/each}
                {#if chats.length === 0 && !loading}
                     <div class="no-chats-indicator">{$_('activity.no_chats.text', { default: 'No chats yet.' })}</div>
                {/if}
            </div>
        {/if}

        <KeyboardShortcuts
            on:nextChat={handleKeyboardNavigation}
            on:previousChat={handleKeyboardNavigation}
        />
    </div>
{/if}

<!-- Styles remain the same -->
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
        background-color: var(--color-grey-20); /* Or appropriate background */
        padding: 16px 20px; /* Adjusted padding */
        margin-bottom: 8px;
        border-bottom: 1px solid var(--color-grey-30); /* Subtle border */
    }

    .top-buttons {
        position: relative;
        height: 32px; /* Ensure container fits buttons */
        display: flex; /* Use flexbox for easier alignment if needed */
        justify-content: flex-end; /* Align close button to the right */
    }

    .top-button {
        /* Removed absolute positioning if using flexbox */
    }

    .top-button.right {
       /* No specific positioning needed if using flex end */
    }

    .chat-groups {
        display: flex;
        flex-direction: column;
        gap: 20px; /* Slightly reduced gap */
        position: relative;
        padding: 0 8px 16px 8px; /* Add horizontal padding */
    }

    .chat-group {
        display: flex;
        flex-direction: column;
        gap: 4px; /* Reduced gap between title and items */
    }

    .group-title {
        font-size: 0.85em; /* Slightly smaller */
        color: var(--color-grey-60);
        margin: 0;
        padding: 0 8px; /* Match horizontal padding */
        font-weight: 500;
        margin-bottom: 6px; /* Reduced margin */
        text-transform: uppercase; /* Optional: Make titles stand out */
        letter-spacing: 0.5px; /* Optional */
    }

    .loading-indicator,
    .no-chats-indicator {
        text-align: center;
        padding: 20px;
        color: var(--color-grey-60);
        font-style: italic;
    }

    .chat-item {
        transition: background-color 0.15s ease;
        border-radius: 8px; /* Apply border-radius directly */
        cursor: pointer;
    }

    .chat-item:hover {
        background-color: var(--color-grey-25); /* Slightly different hover */
    }

    .chat-item.active {
        background-color: var(--color-grey-30);
    }

    /* Improve focus visibility */
    .chat-item:focus-visible {
        outline: 2px solid var(--color-primary-focus); /* Use your focus color */
        outline-offset: 2px;
        background-color: var(--color-grey-25);
    }

</style>