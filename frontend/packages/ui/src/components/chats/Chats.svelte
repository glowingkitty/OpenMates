<script lang="ts">
	import { onMount, onDestroy, createEventDispatcher, tick } from 'svelte';
	import { _ } from 'svelte-i18n';
	import ChatComponent from './Chat.svelte'; // Renamed to avoid conflict with Chat type
	import { panelState } from '../../stores/panelStateStore';
	import { authStore } from '../../stores/authStore';
	import { chatDB } from '../../services/db';
	import { webSocketService } from '../../services/websocketService';
	import { websocketStatus, type WebSocketStatus } from '../../stores/websocketStatusStore';
	import { draftEditorUIState } from '../../services/drafts/draftState'; // Renamed import
	import { LOCAL_CHAT_LIST_CHANGED_EVENT } from '../../services/drafts/draftConstants';
	import type { Chat as ChatType, Message } from '../../types/chat'; // Removed unused ChatComponentVersions, TiptapJSON
	import { tooltip } from '../../actions/tooltip';
	import KeyboardShortcuts from '../KeyboardShortcuts.svelte';
	import { chatSyncService } from '../../services/chatSyncService';
	import { sortChats } from './utils/chatSortUtils'; // Refactored sorting logic
	import { groupChats, getLocalizedGroupTitle } from './utils/chatGroupUtils'; // Refactored grouping logic
	import { locale as svelteLocaleStore } from 'svelte-i18n'; // For date formatting in getLocalizedGroupTitle
	import { get } from 'svelte/store'; // For reading svelteLocaleStore value

	const dispatch = createEventDispatcher();

	// --- Component State ---
	let allChatsFromDB: ChatType[] = []; // Holds all chats fetched from chatDB
	let loading = true; // Indicates if initial data load/sync is in progress
	let selectedChatId: string | null = null; // ID of the currently selected chat
	let _chatIdToSelectAfterUpdate: string | null = null; // Helper to select a chat after list updates
	let currentServerSortOrder: string[] = []; // Server's preferred sort order for chats

	// Phased Loading State
	let displayLimit = 20; // Initially display up to 20 chats
	let allChatsDisplayed = false; // True if all chats are being displayed (limit is Infinity)

	// --- Reactive Computations for Display ---

	// Sort all chats from DB using the utility function
	$: sortedAllChats = sortChats(allChatsFromDB, currentServerSortOrder);

	// Apply display limit for phased loading. This list is used for rendering groups.
	$: chatsForDisplay = sortedAllChats.slice(0, displayLimit);
	
	// Group the chats intended for display
	// The `$_` (translation function) is passed to `getLocalizedGroupTitle` when it's called in the template
	$: groupedChatsForDisplay = groupChats(chatsForDisplay);

	// Flattened list of ALL sorted chats, used for keyboard navigation and selection logic
	// This ensures navigation can cycle through all available chats, even if not all are rendered yet.
	$: flattenedNavigableChats = sortedAllChats;
	
	// Locale for date formatting, updated reactively
	let currentLocale = get(svelteLocaleStore);
	svelteLocaleStore.subscribe(newLocale => {
		currentLocale = newLocale;
		// Re-trigger grouping if locale affects date strings used as keys (implicitly handled by reactivity of groupedChatsForDisplay)
	});


	// --- Event Handlers & Lifecycle ---

	let languageChangeHandler: () => void; // For UI text updates on language change
	let unsubscribeDraftState: (() => void) | null = null; // To unsubscribe from draftState store
	let handleGlobalChatSelectedEvent: (event: Event) => void; // Handler for global chat selection
	let handleGlobalChatDeselectedEvent: (event: Event) => void; // Handler for global chat deselection

	// --- chatSyncService Event Handlers ---

	/**
	 * Handles the 'syncComplete' event from chatSyncService.
	 * Updates server sort order, refreshes the chat list, and stops the loading indicator.
	 * Expands the display limit to show all chats.
	 */
	const handleSyncComplete = async (event: CustomEvent<{ serverChatOrder: string[] }>) => { // Added async
	 console.debug('[Chats] Sync complete event received.');
	 currentServerSortOrder = event.detail.serverChatOrder;
	 await updateChatListFromDB();
	 loading = false;
	 
	 if (!allChatsDisplayed) {
			displayLimit = Infinity; // Show all chats
			allChatsDisplayed = true;
			console.debug('[Chats] Sync complete, expanded display limit.');
		}
	};

	/**
	 * Handles 'chatUpdated' events from chatSyncService.
	 * Refreshes the chat list from DB and re-dispatches selection if the updated chat was selected.
	 */
	const handleChatUpdatedEvent = async (event: CustomEvent<{ chat_id: string; newMessage?: Message }>) => {
		console.debug(`[Chats] Chat updated event received for chat_id: ${event.detail.chat_id}`);
		await updateChatListFromDB(); // Corrected function name
		// If the updated chat is the currently selected one, re-dispatch to update main view
		if (selectedChatId === event.detail.chat_id) {
			const updatedChat = allChatsFromDB.find(c => c.chat_id === event.detail.chat_id); // Corrected variable name
			if (updatedChat) {
				dispatch('chatSelected', { chat: updatedChat });
			}
		}
	};

	const handleChatDeletedEvent = async (event: CustomEvent<{ chat_id: string }>) => {
		console.debug(`[Chats] Chat deleted event received for chat_id: ${event.detail.chat_id}`);
		const chatWasSelected = selectedChatId === event.detail.chat_id;
		await updateChatListFromDB(); // Refresh list from DB
		if (chatWasSelected) {
			selectedChatId = null; // Deselect if the deleted chat was active
			dispatch('chatDeselected');
		}
	};
	
	/**
		* Handles 'priorityChatReady' events. This means a specific chat's data
		* (likely the one the user intends to view immediately) is loaded in cache by the server.
		* Attempts to select this chat if appropriate.
		*/
	const handlePriorityChatReadyEvent = async (event: CustomEvent<{chat_id: string}>) => { // Added async
		console.debug(`[Chats] Priority chat ready: ${event.detail.chat_id}.`);
		const targetChatId = event.detail.chat_id;
		
		// If no chat is selected, or this priority chat is the one we want to select
		if (!selectedChatId || selectedChatId === targetChatId || _chatIdToSelectAfterUpdate === targetChatId) {
			const chatToSelect = allChatsFromDB.find(c => c.chat_id === targetChatId);
			if (chatToSelect) {
				await handleChatClick(chatToSelect, false); // System-initiated initial selection
			} else {
				// Chat might not be in allChatsFromDB if updateChatListFromDB hasn't run yet
				// after chatSyncService updated the DB. Set it to be selected after next list update.
				_chatIdToSelectAfterUpdate = targetChatId;
				await updateChatListFromDB();
			}
		}
	};

	/**
		* Handles 'cachePrimed' event. Indicates server-side cache is generally ready.
		* Can be used to stop loading indicators if syncComplete is delayed.
		*/
	const handleCachePrimedEvent = () => {
		console.debug("[Chats] Cache primed event received.");
		if (loading) {
			loading = false; // Stop loading indicator if still active
		}
		// Phased loading: At this point, the initial 20 chats should be displayable.
		// Full expansion to all chats is handled by syncComplete.
	};

	// --- Local Draft Event Handlers ---

	/**
	 * Handles local draft updates for immediate UI refresh
	 * This ensures the chat list updates immediately when drafts are saved locally,
	 * without waiting for server round-trip
	 */
	const handleLocalChatListChanged = async (event: Event) => {
		const customEvent = event as CustomEvent<{ chat_id?: string; draftDeleted?: boolean }>;
		console.debug('[Chats] Local chat list changed event received:', customEvent.detail);
		console.debug('[Chats] Starting updateChatListFromDB after draft change');
		await updateChatListFromDB(); // Refresh the chat list from local database
		console.debug('[Chats] Completed updateChatListFromDB after draft change');
	};

	// --- Svelte Lifecycle Functions ---

	onMount(async () => {
		// Subscribe to locale changes for date formatting (already handled by reactive currentLocale)
		// languageChangeHandler for UI text (e.g. static labels, not dynamic group titles)
		languageChangeHandler = () => {
			console.debug('[Chats] Language changed event detected.');
			// Force a re-render of components that use $_ directly if necessary,
			// though reactive group titles should update via `currentLocale` change.
			// Forcing update of allChatsFromDB to trigger reactivity:
			allChatsFromDB = [...allChatsFromDB];
		};
		window.addEventListener('language-changed', languageChangeHandler);

		// Listen to local draft changes for immediate UI updates
		window.addEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChanged);

		// Register event listeners for chatSyncService
		chatSyncService.addEventListener('syncComplete', handleSyncComplete as EventListener);
		chatSyncService.addEventListener('chatUpdated', handleChatUpdatedEvent as EventListener);
		chatSyncService.addEventListener('chatDeleted', handleChatDeletedEvent as EventListener);
		chatSyncService.addEventListener('priorityChatReady', handlePriorityChatReadyEvent as EventListener);
		chatSyncService.addEventListener('cachePrimed', handleCachePrimedEvent as EventListener);

		// Subscribe to draftEditorUIState to select newly created chats
		unsubscribeDraftState = draftEditorUIState.subscribe(async value => { // Use renamed store
			if (value.newlyCreatedChatIdToSelect) {
				console.debug(`[Chats] draftEditorUIState signals new chat to select: ${value.newlyCreatedChatIdToSelect}`);
				_chatIdToSelectAfterUpdate = value.newlyCreatedChatIdToSelect;
				draftEditorUIState.update(s => ({ ...s, newlyCreatedChatIdToSelect: null })); // Use renamed store; Reset trigger
				
				// Attempt selection after ensuring the list is updated
				await updateChatListFromDB();
			}
		});

		// Handle global selection events (e.g., from main chat view)
		handleGlobalChatSelectedEvent = (event: Event) => {
			const customEvent = event as CustomEvent<{ chat: ChatType }>;
			if (customEvent.detail?.chat?.chat_id) {
				const newChatId = customEvent.detail.chat.chat_id;
				if (selectedChatId !== newChatId) {
					console.debug(`[Chats] Global chat selected event received, updating selectedChatId to: ${newChatId}`);
					selectedChatId = newChatId;
				}
			}
		};
		window.addEventListener('globalChatSelected', handleGlobalChatSelectedEvent);

		handleGlobalChatDeselectedEvent = () => {
			selectedChatId = null;
			dispatch('chatDeselected');
		};
		window.addEventListener('globalChatDeselected', handleGlobalChatDeselectedEvent);

		// Perform initial database load
		await initializeAndLoadDataFromDB(); // Corrected function name
		// The chatSyncService is now responsible for starting the sync
		// when the user is authenticated, independently of this component's mount.
		// This component will still react to 'syncComplete', 'chatUpdated', etc.
		// events from chatSyncService to update its view.
	});
	
	/**
		* Initializes the local chatDB and loads the initial list of chats.
		* Called on component mount.
		*/
	async function initializeAndLoadDataFromDB() { // Corrected function name
		loading = true;
		try {
			console.debug("[Chats] Initializing local database...");
			await chatDB.init();
			await updateChatListFromDB(); // Load initial chats from DB
			// After attempting to load from DB, set loading to false.
			// The UI will then show "No chats yet" if list is empty, or the chats.
			// Sync events will update the list reactively.
			loading = false;
		} catch (error) {
			console.error("[Chats] Error initializing/loading chats from DB:", error);
			allChatsFromDB = []; // Reset on error
			loading = false; // Ensure loading is false even on error
		}
		// If not authenticated, loading should be false.
		// This is now handled by the try/catch block setting loading = false.
		// If $authStore.isAuthenticated is false, sync events won't occur,
		// and loading = false after DB load is the correct state.
	}

	onDestroy(() => {
		window.removeEventListener('language-changed', languageChangeHandler);
		window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChanged);
		if (unsubscribeDraftState) unsubscribeDraftState();
		
		chatSyncService.removeEventListener('syncComplete', handleSyncComplete as EventListener);
		chatSyncService.removeEventListener('chatUpdated', handleChatUpdatedEvent as EventListener);
		chatSyncService.removeEventListener('chatDeleted', handleChatDeletedEvent as EventListener);
		chatSyncService.removeEventListener('priorityChatReady', handlePriorityChatReadyEvent as EventListener);
		chatSyncService.removeEventListener('cachePrimed', handleCachePrimedEvent as EventListener);

		if (handleGlobalChatSelectedEvent) {
			window.removeEventListener('globalChatSelected', handleGlobalChatSelectedEvent);
		}
		if (handleGlobalChatDeselectedEvent) {
			window.removeEventListener('globalChatDeselected', handleGlobalChatDeselectedEvent);
		}
	});

	// --- User Interaction Handlers ---

	/**
	 * Navigates to the next chat in the flattened (full) list.
	 */
	async function navigateToNextChat() {
		console.debug("[Chats] Navigating to next chat."); // Message from my thought process
		if (flattenedNavigableChats.length === 0) return; // Corrected variable
		
		const currentIndex = selectedChatId ? flattenedNavigableChats.findIndex(c => c.chat_id === selectedChatId) : -1; // Corrected variable
		let nextIndex = currentIndex + 1;

		if (currentIndex === -1 && flattenedNavigableChats.length > 0) { // If no chat selected, select first // Corrected variable
			nextIndex = 0;
		} else if (nextIndex >= flattenedNavigableChats.length) { // If at end, stay at end (or loop: nextIndex = 0;) // Corrected variable
			nextIndex = flattenedNavigableChats.length - 1; // Corrected variable
		}
		// Ensure index is within bounds if list became shorter
		if (nextIndex < 0) nextIndex = 0;
		if (nextIndex >= flattenedNavigableChats.length && flattenedNavigableChats.length > 0) nextIndex = flattenedNavigableChats.length -1; // Corrected variable


		if (flattenedNavigableChats[nextIndex] && flattenedNavigableChats[nextIndex].chat_id !== selectedChatId) { // Corrected variable
			await handleChatClick(flattenedNavigableChats[nextIndex]); // Corrected variable
		}
	}

	/**
	 * Navigates to the previous chat in the flattened (full) list.
	 */
	async function navigateToPreviousChat() {
		console.debug("[Chats] Navigating to previous chat."); // Message from my thought process
		if (flattenedNavigableChats.length === 0) return; // Corrected variable

		const currentIndex = selectedChatId ? flattenedNavigableChats.findIndex(c => c.chat_id === selectedChatId) : -1; // Corrected variable
		let prevIndex = currentIndex - 1;

		if (currentIndex === -1 && flattenedNavigableChats.length > 0) { // If no chat selected, select first // Corrected variable
			prevIndex = 0;
		} else if (prevIndex < 0) { // If at start, stay at start (or loop: prevIndex = flattenedNavigableChats.length - 1;)
			prevIndex = 0;
		}
		
		if (flattenedNavigableChats[prevIndex] && flattenedNavigableChats[prevIndex].chat_id !== selectedChatId) { // Corrected variable
			await handleChatClick(flattenedNavigableChats[prevIndex]); // Corrected variable
		}
	}

	/**
	 * Handles a click on a chat item. Selects the chat and dispatches an event.
	 * Closes the panel on mobile only if user-initiated.
	 */
	async function handleChatClick(chat: ChatType, userInitiated: boolean = true) {
		console.debug('[Chats] Chat clicked:', chat.chat_id, 'userInitiated:', userInitiated);
		selectedChatId = chat.chat_id;

		// Dispatch event to notify parent components like +page.svelte
		dispatch('chatSelected', { chat: chat });

		// NOTE: A global 'globalChatSelected' event was previously dispatched here.
		// This was removed because it caused a duplicate 'set_active_chat' request,
		// as ActiveChat.svelte has its own listener for this global event.
		// The 'chatSelected' Svelte event, handled by the parent component, is the
		// correct and sufficient way to trigger the chat loading logic.

		// Only close panel on mobile if this was a user-initiated click, not a system auto-selection
		if (userInitiated && window.innerWidth < 730) {
			// Assuming 730 is a breakpoint
			handleClose();
		}
	}

 /** Handles keyboard navigation events from KeyboardShortcuts component. */
    function handleKeyboardNavigation(event: CustomEvent<{ type: 'nextChat' | 'previousChat' }>) { // Type from my thought process
        if (event.detail.type === 'nextChat') navigateToNextChat(); // Use event.detail.type
        else if (event.detail.type === 'previousChat') navigateToPreviousChat(); // Use event.detail.type
    }

 /** Closes the chats panel. */
    const handleClose = () => {
  panelState.toggleChats();
 };

 /**
  * Fetches all chats from IndexedDB and updates the component's state.
  * This function is the main source for populating `allChatsFromDB`.
  * It also handles re-selection logic after updates.
  */
 async function updateChatListFromDB() { // Corrected function name
  console.debug("[Chats] Updating chat list from DB...");
  const previouslySelectedChatId = selectedChatId;
  try {
   const chatsFromDb = await chatDB.getAllChats(); // Renamed for clarity inside function
   allChatsFromDB = chatsFromDb; // This assignment triggers reactive updates for sorted/grouped lists - Corrected variable
   console.debug(`[Chats] Updated internal chat list. Count: ${allChatsFromDB.length}`); // Corrected variable
   
   await tick(); // Allow Svelte to process DOM updates from reactive changes

   // Attempt to re-select a chat if one was queued for selection
   if (_chatIdToSelectAfterUpdate) {
    const chatToSelect = flattenedNavigableChats.find(c => c.chat_id === _chatIdToSelectAfterUpdate); // Corrected variable
    if (chatToSelect) {
    	console.debug(`[Chats] Selecting chat after list update: ${_chatIdToSelectAfterUpdate}`);
    	await handleChatClick(chatToSelect, false); // System-initiated selection, don't close menu
    } else {
    	console.warn(`[Chats] Chat ID ${_chatIdToSelectAfterUpdate} not found for selection after list update.`);
    }
    _chatIdToSelectAfterUpdate = null; // Clear the queued selection ID
   }
   // If no specific chat was queued, try to maintain previous selection
   else if (previouslySelectedChatId) {
    const stillExists = flattenedNavigableChats.some(c => c.chat_id === previouslySelectedChatId); // Corrected variable
    if (stillExists) {
    	selectedChatId = previouslySelectedChatId; // Reselect if it still exists
    } else {
    	selectedChatId = null; // Deselect if it no longer exists
    	dispatch('chatDeselected');
    }
   }
   // Optional: Select the first chat if nothing is selected and the list is not empty
   // else if (!selectedChatId && flattenedNavigableChats.length > 0) { // Corrected variable
   // await handleChatClick(flattenedNavigableChats[0]);
   // }

  } catch (error) {
   console.error("[Chats] Error updating chat list from DB:", error);
   allChatsFromDB = []; // Reset chats on error - Corrected variable
   selectedChatId = null;
  }
 }

 /** Handles keydown events on chat items for accessibility (Enter/Space to select). */
    function handleKeyDown(event: KeyboardEvent, chat: ChatType) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleChatClick(chat);
        }
    }

</script>

<!--
  Chat List Template
  - Shows a loading indicator or "no chats" message.
  - Iterates through grouped chats (respecting displayLimit for phased loading).
  - Renders each chat item using the ChatComponent.
  - Provides a "Load all chats" button if not all chats are displayed.
-->
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

		{#if loading && allChatsFromDB.length === 0} <!-- Show loading only if truly no chats are loaded yet -->
			<div class="loading-indicator">{$_('activity.loading_chats.text', { default: 'Loading chats...' })}</div>
		{:else if !allChatsFromDB || allChatsFromDB.length === 0}
			<div class="no-chats-indicator">{$_('activity.no_chats.text', { default: 'No chats yet.' })}</div>
		{:else}
			<div class="chat-groups">
				{#each Object.entries(groupedChatsForDisplay) as [groupKey, groupItems] (groupKey)}
					{#if groupItems.length > 0}
						<div class="chat-group">
							<!-- Pass the translation function `$_` to the utility -->
							<h2 class="group-title">{getLocalizedGroupTitle(groupKey, $_)}</h2>
							{#each groupItems as chat (chat.chat_id)}
								<div
									role="button"
									tabindex="0"
									class="chat-item"
									class:active={selectedChatId === chat.chat_id}
									on:click={() => handleChatClick(chat)}
									on:keydown={(e) => handleKeyDown(e, chat)}
									aria-current={selectedChatId === chat.chat_id ? 'page' : undefined}
									aria-label={chat.title || 'Unnamed chat'}
								>
									<ChatComponent chat={chat} activeChatId={selectedChatId} />
								</div>
							{/each}
						</div>
					{/if}
				{/each}
				
				{#if !allChatsDisplayed && allChatsFromDB.length > displayLimit}
					<div class="load-more-container">
						<button
							class="load-more-button"
							on:click={() => {
								displayLimit = Infinity;
								allChatsDisplayed = true;
								console.debug('[Chats] User clicked "Load all chats".');
							}}
						>
							{$_('chats.loadMore.button', { default: 'Load all chats' })}
							({allChatsFromDB.length - chatsForDisplay.length} {$_('chats.loadMore.more', { default: 'more'})})
						</button>
					</div>
				{/if}
			</div>
		{/if}

		<KeyboardShortcuts
			on:nextChat={(e) => handleKeyboardNavigation(e)}
			on:previousChat={(e) => handleKeyboardNavigation(e)}
		/>
	</div>
{/if}

<!-- Styles section remains largely the same, with addition of .load-more styles -->
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

    .load-more-container {
        display: flex;
        justify-content: center;
        padding: 10px 0;
        margin-top: 10px; /* Add some space above the button */
    }

    .load-more-button {
        padding: 8px 16px;
        border: 1px solid var(--color-grey-40);
        background-color: var(--color-grey-20); /* Use a subtle background */
        color: var(--color-text);
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.9em;
        transition: background-color 0.2s ease;
    }

    .load-more-button:hover {
        background-color: var(--color-grey-25); /* Slightly darker on hover */
    }

 .load-more-button:focus-visible {
  outline: 2px solid var(--color-primary-focus);
  outline-offset: 1px;
 }
</style>
