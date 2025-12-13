<script lang="ts">
	import { onMount, onDestroy, createEventDispatcher, tick } from 'svelte';
	import { text } from '@repo/ui'; // Import text store for translations
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
	import { chatMetadataCache } from '../../services/chatMetadataCache'; // For cache invalidation
	import { chatListCache } from '../../services/chatListCache'; // Global cache for chat list
	import { phasedSyncState } from '../../stores/phasedSyncStateStore'; // For tracking sync state across component lifecycle
	import { activeChatStore } from '../../stores/activeChatStore'; // For persisting active chat across component lifecycle
	import { userProfile } from '../../stores/userProfile'; // For hidden_demo_chats
	import { DEMO_CHATS, LEGAL_CHATS, type DemoChat, isDemoChat, translateDemoChat, isLegalChat, getDemoMessages, isPublicChat } from '../../demo_chats'; // For demo chats
	import { convertDemoChatToChat } from '../../demo_chats/convertToChat'; // For converting demo chats to Chat type
	import { getAllDraftChatIdsWithDrafts } from '../../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft service
	import { notificationStore } from '../../stores/notificationStore'; // For notifications
	import { incognitoChatService } from '../../services/incognitoChatService'; // Import incognito chat service
	import { incognitoMode } from '../../stores/incognitoModeStore'; // Import incognito mode store
	import { hiddenChatStore } from '../../stores/hiddenChatStore'; // Import hidden chat store
	import { hiddenChatService } from '../../services/hiddenChatService'; // Import hidden chat service
	import HiddenChatUnlock from './HiddenChatUnlock.svelte'; // Import hidden chat unlock component

	const dispatch = createEventDispatcher();

// --- Debounce timer for updateChatListFromDB calls ---
let updateChatListDebounceTimer: NodeJS.Timeout | null = null;
const UPDATE_DEBOUNCE_MS = 300; // 300ms debounce for updateChatListFromDB calls

	// --- Component State ---
	let allChatsFromDB: ChatType[] = $state([]); // Holds all chats fetched from chatDB
	let syncing = $state(true); // Indicates if 3-phase sync is in progress (starts true)
	let syncComplete = $state(false); // Shows "Sync complete" message briefly
	let selectedChatId: string | null = $state(null); // ID of the currently selected chat (synced with activeChatStore)
	let _chatIdToSelectAfterUpdate: string | null = $state(null); // Helper to select a chat after list updates
	let currentServerSortOrder: string[] = $state([]); // Server's preferred sort order for chats
	let sessionStorageDraftUpdateTrigger = $state(0); // Trigger for reactivity when sessionStorage drafts change

	// Phased Loading State
	let displayLimit = $state(20); // Initially display up to 20 chats
	let allChatsDisplayed = $state(false); // True if all chats are being displayed (limit is Infinity)

	// Select Mode State
	let selectMode = $state(false); // Whether we're in multi-select mode
	let selectedChatIds = $state<Set<string>>(new Set()); // Set of selected chat IDs
	let lastSelectedChatId: string | null = $state(null); // Track last selected chat for range selection

	// Hidden Chats State
	let showHiddenChatUnlock = $state(false); // Show unlock modal
	let isFirstTimeUnlock = $state(false); // True if setting code for first time
	let chatIdToHideAfterUnlock: string | null = $state(null); // Chat ID to hide after unlock
	let hiddenChatState = $derived($hiddenChatStore); // Reactive hidden chat state
	
	// Scroll-to-top overscroll state for hidden chats unlock
	let showOverscrollUnlock = $state(false); // Show unlock interface when overscrolling at top
	let overscrollUnlockCode = $state(''); // Code input for overscroll unlock
	let overscrollUnlockError = $state(''); // Error message for overscroll unlock
	let overscrollUnlockLoading = $state(false); // Loading state for overscroll unlock
	let overscrollUnlockInput: HTMLInputElement | null = $state(null); // Reference to input element
	let activityHistoryElement: HTMLDivElement | null = $state(null); // Reference to scrollable container
	let currentScrollTop = $state(0); // Track current scroll position for reactivity
	let chatIdToHideViaOverscroll: string | null = $state(null); // Chat ID to hide via overscroll unlock

	// --- Reactive Computations for Display ---

	// Get filtered public chats (demo + legal) - exclude hidden ones for authenticated users
	// Legal chats are always shown (like demo chats) - they're public content and should be easily accessible
	// Translates demo chats to the user's locale before converting to Chat format
	// Legal chats skip translation (they use plain text)
	let visiblePublicChats = $derived((() => {
		// Reference the locale store to make the derived recalculate when language changes
		// This triggers reactivity whenever the user changes the language
		const currentLocale = $svelteLocaleStore;
		// Don't log every recalculation - only log when locale actually changes (handled elsewhere if needed)
		
		// Get hidden IDs for authenticated users (shared between demo and legal chats)
		const hiddenIds = $authStore.isAuthenticated ? ($userProfile.hidden_demo_chats || []) : [];
		
		// Filter demo chats
		let demoChats: ChatType[] = [];
		if (!$authStore.isAuthenticated) {
			demoChats = DEMO_CHATS
				.map(demo => translateDemoChat(demo)) // Translate to user's locale
				.map(demo => convertDemoChatToChat(demo));
		} else {
			// For authenticated users, filter out hidden demo chats
			demoChats = DEMO_CHATS
				.filter(demo => !hiddenIds.includes(demo.chat_id))
				.map(demo => translateDemoChat(demo)) // Translate to user's locale
				.map(demo => convertDemoChatToChat(demo));
		}
		
		// Always include legal chats for all users (they're public content and should be easily accessible)
		// Filter out hidden legal chats for authenticated users (uses same hidden_demo_chats mechanism)
		// Legal chats skip translation (they use plain text, not translation keys)
		const legalChats: ChatType[] = LEGAL_CHATS
			.filter(legal => !hiddenIds.includes(legal.chat_id)) // Filter out hidden legal chats too
			.map(legal => translateDemoChat(legal)) // Legal chats skip translation but still go through function
			.map(legal => convertDemoChatToChat(legal));
		
		return [...demoChats, ...legalChats];
	})());

	// Combine public chats (demo + legal) with real chats from IndexedDB
	// Also include sessionStorage-only chats for non-authenticated users (new chats with drafts)
	// Also include shared chats for non-authenticated users (loaded from IndexedDB but marked for cleanup)
	// Also include incognito chats (stored in sessionStorage, not IndexedDB)
	// Filter out any duplicates (legal chats might be in IndexedDB if previously opened)
	let incognitoChatsTrigger = $state(0); // Trigger for reactivity when incognito chats change
	let incognitoChats: ChatType[] = $state([]); // Cache for incognito chats
	
	let allChats = $derived((() => {
		const publicChatIds = new Set(visiblePublicChats.map(c => c.chat_id));
		// Only include real chats from IndexedDB (exclude legal chats since they're already in visiblePublicChats)
		const realChatsFromDB = allChatsFromDB.filter(chat => !isLegalChat(chat.chat_id));
		
		// Reference incognitoChatsTrigger to make this reactive to incognito chat changes
		const _incognitoTrigger = incognitoChatsTrigger;
		
		// Load incognito chats (only if incognito mode is enabled)
		// This is async, so we use the cached incognitoChats array which is updated via effect
		const _incognitoChats = incognitoChats;
		
		// CRITICAL: For non-authenticated users, include sessionStorage-only chats (new chats with drafts)
		// These are chats that have drafts in sessionStorage but don't exist in IndexedDB yet
		// Reference sessionStorageDraftUpdateTrigger to make this reactive to draft changes
		const _trigger = sessionStorageDraftUpdateTrigger; // Reference to trigger reactivity
		let sessionStorageChats: ChatType[] = [];
		let sharedChats: ChatType[] = [];
		if (!$authStore.isAuthenticated) {
			const sessionDraftChatIds = getAllDraftChatIdsWithDrafts();
			// Filter out demo/legal chat IDs (they're already in visiblePublicChats)
			// and chat IDs that are already in IndexedDB
			const existingChatIds = new Set([
				...visiblePublicChats.map(c => c.chat_id),
				...realChatsFromDB.map(c => c.chat_id),
				..._incognitoChats.map(c => c.chat_id) // Also exclude incognito chats
			]);
			
			for (const chatId of sessionDraftChatIds) {
				if (!existingChatIds.has(chatId)) {
					// Create a virtual chat object for this sessionStorage-only chat
					const now = Math.floor(Date.now() / 1000);
					const virtualChat: ChatType = {
						chat_id: chatId,
						encrypted_title: null,
						title: null,
						messages_v: 0,
						title_v: 0,
						draft_v: 0,
						encrypted_draft_md: null,
						encrypted_draft_preview: null,
						last_edited_overall_timestamp: now,
						unread_count: 0,
						created_at: now,
						updated_at: now,
						processing_metadata: false,
						waiting_for_metadata: false,
						encrypted_category: null,
						encrypted_icon: null
					};
					sessionStorageChats.push(virtualChat);
					console.debug('[Chats] Added sessionStorage-only chat to list:', chatId);
				}
			}
			
			// Include shared chats from IndexedDB for non-authenticated users
			// These are chats that were loaded via share links and stored in IndexedDB
			// They're tracked in sessionStorage for cleanup on session close
			try {
				const sharedChatIds = JSON.parse(sessionStorage.getItem('shared_chats') || '[]');
				for (const sharedChatId of sharedChatIds) {
					// Check if chat exists in IndexedDB
					const sharedChat = realChatsFromDB.find(c => c.chat_id === sharedChatId);
					if (sharedChat && !existingChatIds.has(sharedChatId)) {
						sharedChats.push(sharedChat);
						console.debug('[Chats] Added shared chat to list:', sharedChatId);
					}
				}
			} catch (e) {
				console.warn('[Chats] Error reading shared chats from sessionStorage:', e);
			}
		}
		
		return [...visiblePublicChats, ...realChatsFromDB, ...sessionStorageChats, ...sharedChats, ..._incognitoChats];
	})());

	// Sort all chats (demo + real) using the utility function
	let sortedAllChats = $derived(sortChats(allChats, currentServerSortOrder));

	// CRITICAL CHANGE: Show all chats immediately, even those waiting for metadata
	// Chats with waiting_for_metadata will display with status indicators (Sending/Processing)
	// instead of being hidden from the sidebar
	// Filter out hidden chats from main list.
	// Hidden chats are identified by decryption failure (no DB flag). Locked hidden chats are marked as `is_hidden_candidate`.
	let sortedAllChatsFiltered = $derived((() => {
		const sorted = sortedAllChats;
		if (!$authStore.isAuthenticated) {
			return sorted;
		}
		return sorted.filter(chat => !(chat as any).is_hidden && !(chat as any).is_hidden_candidate);
	})());

	// CRITICAL FIX: Order group keys so "today" appears before "previous_30_days"
	// Define the order of group keys (most recent first)
	const GROUP_ORDER = ['today', 'yesterday', 'previous_7_days', 'previous_30_days'];

	// Separate list for hidden chats (only shown when unlocked)
	let hiddenChats = $derived((() => {
		if (!hiddenChatState.isUnlocked) {
			return [];
		}
		return sortedAllChats.filter(chat => (chat as any).is_hidden);
	})());

	// Group hidden chats for display
	let groupedHiddenChats = $derived(groupChats(hiddenChats));
	let orderedGroupedHiddenChats = $derived((() => {
		const groups = groupedHiddenChats;
		const orderedEntries: [string, ChatType[]][] = [];
		
		// First, add groups in the defined order
		for (const groupKey of GROUP_ORDER) {
			if (groups[groupKey] && groups[groupKey].length > 0) {
				orderedEntries.push([groupKey, groups[groupKey]]);
			}
		}
		
		// Then, add any remaining groups
		for (const [groupKey, groupItems] of Object.entries(groups)) {
			if (!GROUP_ORDER.includes(groupKey) && groupItems.length > 0) {
				orderedEntries.push([groupKey, groupItems]);
			}
		}
		
		return orderedEntries;
	})());

	// Apply display limit for phased loading. This list is used for rendering groups using Svelte 5 runes
	let chatsForDisplay = $derived(sortedAllChatsFiltered.slice(0, displayLimit));
	
	// Group the chats intended for display using Svelte 5 runes
	// The `$_` (translation function) is passed to `getLocalizedGroupTitle` when it's called in the template
	let groupedChatsForDisplay = $derived(groupChats(chatsForDisplay));
	
	// Get ordered group entries for display
	let orderedGroupedChats = $derived((() => {
		const groups = groupedChatsForDisplay;
		const orderedEntries: [string, ChatType[]][] = [];
		
		// First, add groups in the defined order
		for (const groupKey of GROUP_ORDER) {
			if (groups[groupKey] && groups[groupKey].length > 0) {
				orderedEntries.push([groupKey, groups[groupKey]]);
			}
		}
		
		// Then, add any remaining groups (e.g., month groups) in their original order
		for (const [groupKey, groupItems] of Object.entries(groups)) {
			if (!GROUP_ORDER.includes(groupKey) && groupItems.length > 0) {
				orderedEntries.push([groupKey, groupItems]);
			}
		}
		
		return orderedEntries;
	})());

	// Flattened list of ALL sorted chats (excluding those processing metadata), used for keyboard navigation and selection logic using Svelte 5 runes
	// This ensures navigation can cycle through all available chats, even if not all are rendered yet.
	let flattenedNavigableChats = $derived(sortedAllChatsFiltered);
	
	// CRITICAL FIX: Order group keys so "today" appears before "previous_30_days"
	// Define the order of group keys (most recent first) - MOVED UP to avoid use-before-declaration
	// Note: GROUP_ORDER is now defined above, before its first use
	
	// Locale for date formatting, updated reactively
	let currentLocale = get(svelteLocaleStore);
	svelteLocaleStore.subscribe(newLocale => {
		currentLocale = newLocale;
		// Re-trigger grouping if locale affects date strings used as keys (implicitly handled by reactivity of groupedChatsForDisplay)
	});


	// --- Event Handlers & Lifecycle ---

	let languageChangeHandler: () => void; // For UI text updates on language change
	let unsubscribeDraftState: (() => void) | null = null; // To unsubscribe from draftState store
	let unsubscribeAuth: (() => void) | null = null; // To unsubscribe from authStore
	let handleGlobalChatSelectedEvent: (event: Event) => void; // Handler for global chat selection
	let handleGlobalChatDeselectedEvent: (event: Event) => void; // Handler for global chat deselection
	let handleLogoutEvent: () => void; // Handler for logout event to clear user chats
	let handleContextMenuEnterSelectMode: (event: Event) => void; // Handler for entering select mode from context menu
	let handleContextMenuUnselect: (event: Event) => void; // Handler for unselecting chat from context menu
	let handleContextMenuSelect: (event: Event) => void; // Handler for selecting chat from context menu
	let handleContextMenuBulkAction: (event: Event) => void; // Handler for bulk actions from context menu
	let handleIncognitoChatsDeleted: () => void; // Handler for incognito chats deletion event
	let handleShowHiddenChatUnlock: (event: Event) => void; // Handler for show hidden chat unlock modal
	let handleShowOverscrollUnlockForHide: (event: Event) => void; // Handler for show overscroll unlock for hiding chat
	let handleHiddenChatsAutoLocked: () => void; // Handler for hidden chats auto-locked event
	let handleChatHidden: (event: Event) => void; // Handler for chat hidden event
	let handleChatUnhidden: (event: Event) => void; // Handler for chat unhidden event

	// --- chatSyncService Event Handlers ---

	/**
	 * Handles the 'syncComplete' event from chatSyncService.
	 * Updates server sort order, refreshes the chat list, and stops the loading indicator.
	 * Expands the display limit to show all chats.
	 */
	const handleSyncComplete = async (event: CustomEvent<{ serverChatOrder: string[] }>) => { // Added async
	 console.debug('[Chats] Sync complete event received.');
	 currentServerSortOrder = event.detail.serverChatOrder;
	 chatListCache.markDirty();
	 await updateChatListFromDB(true);
	 
	 syncing = false;
	 syncComplete = true;
	 
	 // Hide the message after 1 second
	 setTimeout(() => {
	 	syncComplete = false;
	 }, 1000);
	 
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
	const handleChatUpdatedEvent = async (event: CustomEvent<{ chat_id: string; newMessage?: Message; type?: string; chat?: ChatType }>) => {
		console.debug(`[Chats] Chat updated event received for chat_id: ${event.detail.chat_id}, type: ${event.detail.type}`);
		
		// Invalidate cache for the updated chat to ensure fresh metadata
		chatMetadataCache.invalidateChat(event.detail.chat_id);
		
		// Invalidate last message cache if a new message was added
		if (event.detail.newMessage || event.detail.type === 'message_added') {
			chatListCache.invalidateLastMessage(event.detail.chat_id);
		}
		
	// If a draft was deleted and we have the updated chat object, patch directly
	if (event.detail.type === 'draft_deleted' && event.detail.chat) {
		const updatedChat = event.detail.chat;
		const chatIndex = allChatsFromDB.findIndex(c => c.chat_id === updatedChat.chat_id);
		if (chatIndex !== -1) {
			allChatsFromDB[chatIndex] = updatedChat;
			allChatsFromDB = [...allChatsFromDB];
		}
		chatListCache.upsertChat(updatedChat);
		// Update local state from cache
		const cached = chatListCache.getCache(false);
		if (cached) {
			allChatsFromDB = cached;
		}
	} else if (event.detail.chat) {
		// If we have the updated chat payload, patch cache and list without full reload
		chatListCache.upsertChat(event.detail.chat);
		const cached = chatListCache.getCache(false);
		if (cached) {
			allChatsFromDB = cached;
		}
	} else {
		// Fallback: mark cache dirty and refresh from DB
		chatListCache.markDirty();
		await updateChatListFromDB();
	}
	
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
		chatListCache.removeChat(event.detail.chat_id);
		const cached = chatListCache.getCache(false);
		if (cached) {
			allChatsFromDB = cached;
		} else {
			allChatsFromDB = allChatsFromDB.filter(c => c.chat_id !== event.detail.chat_id);
			chatListCache.markDirty();
			await updateChatListFromDB();
		}
		if (chatWasSelected) {
			selectedChatId = null; // Deselect if the deleted chat was active
			
			// Clear the persistent store when the active chat is deleted
			activeChatStore.clearActiveChat();
			
			dispatch('chatDeselected');
		}
	};
	
	/**
		* Handles 'phase_1_last_chat_ready' events from the new phased sync system.
		* This means Phase 1 is complete and the last opened chat is ready.
		* Per sync.md: Phase 1 handler saves data to IndexedDB BEFORE dispatching this event,
		* so the chat should be available immediately.
		* 
		* CRITICAL FIX: Only auto-select the Phase 1 chat if the user is not already in a different chat.
		* This prevents Phase 1 from overriding a new chat the user just created.
		*/
	const handlePhase1LastChatReadyEvent = async (event: CustomEvent<{chat_id: string}>) => { // Added async
		console.info(`[Chats] Phase 1 complete - Last chat ready: ${event.detail.chat_id}.`);
		const targetChatId = event.detail.chat_id;
		
		// CRITICAL: Check if we should auto-select this chat
		// Don't auto-select if user is already in a different chat (e.g., a new chat they just created)
		if (!phasedSyncState.shouldAutoSelectPhase1Chat(targetChatId)) {
			console.info(`[Chats] Skipping Phase 1 auto-select - user is in a different chat`);
			// Still update the list to show the synced chat in the sidebar
			await updateChatListFromDB();
			return;
		}
		
		// Queue the chat for selection and update the list
		// The Phase 1 handler has already saved data to IndexedDB
		_chatIdToSelectAfterUpdate = targetChatId;
		chatListCache.markDirty();
		await updateChatListFromDB(true);
	};

	/**
		* Handles 'phase_2_last_20_chats_ready' events from Phase 2 of the new phased sync system.
		* This means the last 20 updated chats are ready for quick access.
		*/
	const handlePhase2Last20ChatsReadyEvent = async (event: CustomEvent<{chat_count: number}>) => {
		console.debug(`[Chats] Phase 2 complete - Last 20 chats ready: ${event.detail.chat_count} chats.`);
		
		// Update the chat list to show the recent chats
		chatListCache.markDirty();
		await updateChatListFromDB(true);
		
		// Expand display limit to show recent chats
		if (!allChatsDisplayed && displayLimit < 20) {
			displayLimit = 20; // Show at least 20 recent chats
		}
	};

	/**
		* Handles 'phase_3_last_100_chats_ready' events from Phase 3 of the new phased sync system.
		* This means the last 100 chats are ready and full sync is complete.
		*/
	const handlePhase3Last100ChatsReadyEvent = async (event: CustomEvent<{chat_count: number}>) => {
		console.info(`[Chats] Phase 3 complete - Last 100 chats ready: ${event.detail.chat_count} chats.`);
		
		// Update the chat list to show all chats
		chatListCache.markDirty();
		await updateChatListFromDB(true);
		
		// CRITICAL: Always expand display limit to show all chats after Phase 3
		// Don't check allChatsDisplayed - ensure it's always set
		displayLimit = Infinity;
		allChatsDisplayed = true;
		console.info(`[Chats] Phase 3 complete - Set displayLimit to Infinity, allChatsFromDB has ${allChatsFromDB.length} chats`);
		
		// Show "Sync complete" message
		syncing = false;
		syncComplete = true;
		
		// Hide the message after 1 second
		setTimeout(() => {
			syncComplete = false;
		}, 1000);
	};

	/**
		* Handles 'phasedSyncComplete' events from the new phased sync system.
		* This indicates the entire 3-phase sync process is complete.
		*/
	const handlePhasedSyncCompleteEvent = async (event: CustomEvent<any>) => {
		console.info(`[Chats] Phased sync complete:`, event.detail);
		
		// Mark that initial phased sync has completed
		// This prevents redundant syncs when Chats component is remounted
		phasedSyncState.markSyncCompleted();
		
		// Final update of the chat list
		chatListCache.markDirty();
		await updateChatListFromDB(true);
		
		syncing = false;
		syncComplete = true;
		
		// Hide the message after 1 second
		setTimeout(() => {
			syncComplete = false;
		}, 1000);
		
		// CRITICAL: Always ensure all chats are displayed after sync complete
		displayLimit = Infinity;
		allChatsDisplayed = true;
		console.info(`[Chats] Phased sync complete - Set displayLimit to Infinity, allChatsFromDB has ${allChatsFromDB.length} chats`);
	};

	/**
		* Handles 'cachePrimed' event. Indicates server-side cache is generally ready.
		* This means the 3-phase sync is complete.
		*/
	const handleCachePrimedEvent = () => {
		console.debug("[Chats] Cache primed event received.");
		syncing = false;
		syncComplete = true;
		
		// Hide the message after 1 second
		setTimeout(() => {
			syncComplete = false;
		}, 1000);
	};

	/**
		* Handles 'syncStatusResponse' event. Indicates server-side cache status.
		* If cache is already primed, stop syncing.
		*/
	const handleSyncStatusResponse = (event: CustomEvent<{cache_primed: boolean, chat_count: number, timestamp: number}>) => {
		console.debug("[Chats] Sync status response received:", event.detail);
		if (event.detail.cache_primed) {
			syncing = false;
			syncComplete = true;
			
			// Hide the message after 1 second
			setTimeout(() => {
				syncComplete = false;
			}, 1000);
		}
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
		
		// Invalidate cache for the specific chat if provided, to ensure fresh preview data
		if (customEvent.detail?.chat_id) {
			chatMetadataCache.invalidateChat(customEvent.detail.chat_id);
		}
		
		// CRITICAL: For non-authenticated users, trigger reactivity by updating sessionStorageDraftUpdateTrigger
		// This ensures sessionStorage-only chats appear in the list and demo chat drafts update
		// For authenticated users, update from database as usual
		if (!$authStore.isAuthenticated) {
			// Increment trigger to force reactivity in $derived allChats
			// This will cause allChats to recalculate and include sessionStorage chats
			sessionStorageDraftUpdateTrigger++;
			console.debug('[Chats] Triggered reactivity update for sessionStorage drafts, trigger:', sessionStorageDraftUpdateTrigger);
		} else {
			// For authenticated users, prefer an incremental update to avoid a full DB read on every draft save.
			// This also fixes "new draft chat not shown" when the chat list is served from cache.
			const chatId = customEvent.detail?.chat_id;
			if (chatId) {
				try {
					const updatedChat = await chatDB.getChat(chatId);
					if (updatedChat) {
						const chatIndex = allChatsFromDB.findIndex(c => c.chat_id === updatedChat.chat_id);
						if (chatIndex !== -1) {
							allChatsFromDB[chatIndex] = updatedChat;
						} else {
							allChatsFromDB = [...allChatsFromDB, updatedChat];
						}
						// Force reactivity for derived sorting/grouping
						allChatsFromDB = [...allChatsFromDB];
						// Keep global cache in sync so subsequent refreshes don't "miss" the new chat
						chatListCache.upsertChat(updatedChat);
						console.debug('[Chats] Updated chat list incrementally from local draft change:', { chatId });
						return;
					}
				} catch (error) {
					console.error('[Chats] Error fetching updated chat after local draft change:', error);
				}
			}

			// Fallback: full refresh (force to bypass global cache)
			chatListCache.markDirty();
			await updateChatListFromDB(true);
		}
	};

	// --- Svelte Lifecycle Functions ---

	// Load incognito chats when incognito mode is enabled
	// Avoid using subscriptions or $effect to prevent infinite loops
	let incognitoChatsLoading = $state(false);
	
	// Function to load incognito chats
	async function loadIncognitoChats() {
		if (incognitoChatsLoading) return;
		
		const isIncognitoEnabled = incognitoMode.get();
		incognitoChatsLoading = true;
		
		try {
			if (isIncognitoEnabled) {
				await incognitoChatService.init();
				const chats = await incognitoChatService.getAllChats();
				incognitoChats = chats;
				incognitoChatsTrigger++; // Trigger reactivity
				console.debug('[Chats] Loaded incognito chats:', chats.length);
			} else {
				// Clear incognito chats when mode is disabled
				incognitoChats = [];
				incognitoChatsTrigger++;
			}
		} catch (error) {
			console.error('[Chats] Error loading incognito chats:', error);
			incognitoChats = [];
		} finally {
			incognitoChatsLoading = false;
		}
	}

	onMount(async () => {
		// CRITICAL: Check auth state FIRST before loading chats
		// If user is not authenticated, clear any stale chat data immediately
		if (!$authStore.isAuthenticated) {
			console.debug('[Chats] User not authenticated on mount - clearing user chats');
			allChatsFromDB = []; // Clear user chats immediately
			selectedChatId = null;
			_chatIdToSelectAfterUpdate = null;
			currentServerSortOrder = [];
			syncing = false;
			syncComplete = false;
			activeChatStore.clearActiveChat();
		}
		
		// Initialize selectedChatId from the persistent store on mount
		// This ensures the active chat remains highlighted when the panel is reopened
		const currentActiveChat = $activeChatStore;
		if (currentActiveChat) {
			selectedChatId = currentActiveChat;
			console.debug('[Chats] Restored active chat from store:', currentActiveChat);
		}
		
		// CHANGED: For non-authenticated users, don't show syncing indicator
		// Demo chats are loaded synchronously, no sync needed
		if (!$authStore.isAuthenticated) {
			syncing = false;
			console.debug('[Chats] Non-authenticated user - skipping sync indicator');
			
			// CRITICAL: For non-auth users, ensure the welcome demo chat is selected if no chat is active yet
			// This handles the case where the sidebar mounts before +page.svelte sets the active chat
			// FIXED: Dispatch chatSelected to ensure the chat actually loads (important for SEO and user experience)
			if (!currentActiveChat && visiblePublicChats.length > 0) {
				const welcomeChat = visiblePublicChats.find(chat => chat.chat_id === 'demo-welcome');
				if (welcomeChat) {
					console.debug('[Chats] Auto-selecting welcome demo chat for non-authenticated user');
					selectedChatId = 'demo-welcome';
					activeChatStore.setActiveChat('demo-welcome');
					// Dispatch chatSelected to ensure the chat loads in ActiveChat component
					// This is critical for SEO scrapers and user experience
					dispatch('chatSelected', { chat: welcomeChat });
					console.debug('[Chats] Dispatched chatSelected for welcome demo chat');
				}
			}
		}
		
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

		// Listen for logout event to clear user chats and reset state
		handleLogoutEvent = async () => {
			console.debug('[Chats] Logout event received - clearing user chats and resetting state immediately');
			
			// CRITICAL: Clear all user chats from state IMMEDIATELY (keep only demo/legal chats)
			// This ensures the UI updates right away, even if database deletion is still in progress
			allChatsFromDB = [];
			selectedChatId = null;
			_chatIdToSelectAfterUpdate = null;
			currentServerSortOrder = [];
			syncing = false;
			syncComplete = false;
			
			// Clear the persistent store
			activeChatStore.clearActiveChat();
			
			// Reset display limit to show all demo chats
			displayLimit = Infinity;
			allChatsDisplayed = true;
			
			// Force a reactive update to ensure UI reflects the cleared state
			// This is especially important if chats were already loaded before logout
			console.debug('[Chats] User chats cleared immediately, demo chats will be shown');
			
			// CRITICAL: After clearing user chats, select the welcome demo chat
			// This ensures the welcome chat is highlighted in the sidebar after logout
			// Use tick() to ensure reactive updates have processed (visiblePublicChats should be updated)
			await tick();
			
			// Find and select the welcome demo chat
			if (visiblePublicChats.length > 0) {
				const welcomeChat = visiblePublicChats.find(chat => chat.chat_id === 'demo-welcome');
				if (welcomeChat) {
					console.debug('[Chats] Auto-selecting welcome demo chat after logout');
					selectedChatId = 'demo-welcome';
					activeChatStore.setActiveChat('demo-welcome');
					// Dispatch chatSelected to ensure the chat is marked as active
					// Note: ActiveChat component also loads the chat, but we need to mark it as selected here
					dispatch('chatSelected', { chat: welcomeChat });
					console.debug('[Chats] Dispatched chatSelected for welcome demo chat after logout');
				} else {
					console.warn('[Chats] Welcome demo chat not found in visiblePublicChats after logout');
				}
			} else {
				console.warn('[Chats] No visible public chats available after logout');
			}
		};
		window.addEventListener('userLoggingOut', handleLogoutEvent);
		
		// CRITICAL: Listen to authStore changes to handle offline-first authentication
		// - Clear chats when auth becomes false (logout)
		// - Load chats when auth becomes true (offline-first: optimistic auth restored)
		// This handles the case where logout happens before Chats component mounts,
		// and also supports offline-first mode where optimistic auth is set after mount
		// Store the unsubscribe function so we can clean it up in onDestroy
		unsubscribeAuth = authStore.subscribe(async (authState) => {
			if (!authState.isAuthenticated && allChatsFromDB.length > 0) {
				console.debug('[Chats] Auth state changed to unauthenticated - clearing user chats immediately');
				allChatsFromDB = [];
				selectedChatId = null;
				_chatIdToSelectAfterUpdate = null;
				currentServerSortOrder = [];
				activeChatStore.clearActiveChat();
				// Clear global cache on logout to prevent stale data
				chatListCache.clear();
				// Force UI update by triggering reactivity
				allChatsFromDB = [];
				
				// FALLBACK: Select welcome demo chat if not already selected
				// This ensures the welcome chat is highlighted even if 'userLoggingOut' event doesn't fire
				// Use tick() to ensure reactive updates have processed
				await tick();
				if (!selectedChatId && visiblePublicChats.length > 0) {
					const welcomeChat = visiblePublicChats.find(chat => chat.chat_id === 'demo-welcome');
					if (welcomeChat) {
						console.debug('[Chats] Auto-selecting welcome demo chat after auth state change (fallback)');
						selectedChatId = 'demo-welcome';
						activeChatStore.setActiveChat('demo-welcome');
						dispatch('chatSelected', { chat: welcomeChat });
					}
				}
			} else if (authState.isAuthenticated && allChatsFromDB.length === 0) {
				// OFFLINE-FIRST FIX: When auth becomes true (e.g., optimistic auth restored),
				// load chats from IndexedDB if we haven't loaded them yet
				console.debug('[Chats] Auth state changed to authenticated - loading user chats from IndexedDB (offline-first mode)');
				await initializeAndLoadDataFromDB();
			}
		});

		// Register event listeners for chatSyncService
		chatSyncService.addEventListener('syncComplete', handleSyncComplete as EventListener);
		chatSyncService.addEventListener('chatUpdated', handleChatUpdatedEvent as EventListener);
		chatSyncService.addEventListener('chatDeleted', handleChatDeletedEvent as EventListener);
		chatSyncService.addEventListener('phase_1_last_chat_ready', handlePhase1LastChatReadyEvent as EventListener);
		chatSyncService.addEventListener('cachePrimed', handleCachePrimedEvent as EventListener);
		chatSyncService.addEventListener('syncStatusResponse', handleSyncStatusResponse as EventListener);
		
		// Register new phased sync event listeners
		chatSyncService.addEventListener('phase_2_last_20_chats_ready', handlePhase2Last20ChatsReadyEvent as EventListener);
		chatSyncService.addEventListener('phase_3_last_100_chats_ready', handlePhase3Last100ChatsReadyEvent as EventListener);
		chatSyncService.addEventListener('phasedSyncComplete', handlePhasedSyncCompleteEvent as EventListener);

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
					
					// Update the persistent store so the selection survives component unmount/remount
					activeChatStore.setActiveChat(newChatId);
				}
			}
		};
		window.addEventListener('globalChatSelected', handleGlobalChatSelectedEvent);

		handleGlobalChatDeselectedEvent = () => {
			selectedChatId = null;
			
			// Clear the persistent store when a chat is deselected
			activeChatStore.clearActiveChat();
			
			dispatch('chatDeselected');
		};
		window.addEventListener('globalChatDeselected', handleGlobalChatDeselectedEvent);

		// Listen to context menu events from Chat components
		handleContextMenuEnterSelectMode = () => {
			selectMode = true;
			selectedChatIds = new Set(); // Create new Set to trigger reactivity and clear selection
			console.debug('[Chats] Entered select mode from context menu');
		};
		window.addEventListener('chatContextMenuEnterSelectMode', handleContextMenuEnterSelectMode);

		handleContextMenuUnselect = (event: Event) => {
			const customEvent = event as CustomEvent<string>;
			if (customEvent.detail && selectedChatIds.has(customEvent.detail)) {
				selectedChatIds.delete(customEvent.detail);
				selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
			}
		};
		window.addEventListener('chatContextMenuUnselect', handleContextMenuUnselect);

		handleContextMenuSelect = (event: Event) => {
			const customEvent = event as CustomEvent<string>;
			if (customEvent.detail) {
				selectedChatIds.add(customEvent.detail);
				selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
			}
		};
		window.addEventListener('chatContextMenuSelect', handleContextMenuSelect);

		// Listen to bulk actions from Chat components (when in select mode)
		handleContextMenuBulkAction = (event: Event) => {
			const customEvent = event as CustomEvent<string>;
			const action = customEvent.detail;
			console.debug('[Chats] Bulk action received from context menu:', action);
			
			// Call the appropriate bulk handler (functions defined later in file)
			if (action === 'download') {
				handleBulkDownload().catch(err => console.error('[Chats] Error in bulk download:', err));
			} else if (action === 'copy') {
				handleBulkCopy().catch(err => console.error('[Chats] Error in bulk copy:', err));
			} else if (action === 'delete') {
				handleBulkDelete().catch(err => console.error('[Chats] Error in bulk delete:', err));
			}
		};
		window.addEventListener('chatContextMenuBulkAction', handleContextMenuBulkAction);

		// Listen for incognito chats deletion event (when incognito mode is disabled)
		handleIncognitoChatsDeleted = async () => {
			console.debug('[Chats] Incognito chats deleted event received');
			// Clear incognito chats from state
			incognitoChats = [];
			incognitoChatsTrigger++;
			
			// If the currently selected chat is an incognito chat, deselect it
			// Check before clearing (since we just cleared the array)
			const currentChat = allChats.find(c => c.chat_id === selectedChatId);
			if (currentChat?.is_incognito) {
				selectedChatId = null;
				activeChatStore.clearActiveChat();
				dispatch('chatDeselected');
			}
		};
		window.addEventListener('incognitoChatsDeleted', handleIncognitoChatsDeleted);

		// Listen for show hidden chat unlock modal event
		handleShowHiddenChatUnlock = (event: Event) => {
			const customEvent = event as CustomEvent<{ chatId?: string }>;
			const chatId = customEvent.detail.chatId || null;
			chatIdToHideAfterUnlock = chatId;
			
			// Always show unlock interface (no need to check if code was set)
			// The unlock will try to decrypt and show what works
			isFirstTimeUnlock = false; // Not used anymore, but keep for backward compatibility
			showHiddenChatUnlock = true;
		};
		window.addEventListener('showHiddenChatUnlock', handleShowHiddenChatUnlock);

		// Listen for show overscroll unlock interface for hiding a chat
		handleShowOverscrollUnlockForHide = (event: Event) => {
			const customEvent = event as CustomEvent<{ chatId: string }>;
			chatIdToHideViaOverscroll = customEvent.detail.chatId;
			
			showOverscrollUnlock = true;
			// Scroll to top to show the unlock interface
			if (activityHistoryElement) {
				activityHistoryElement.scrollTop = 0;
			}
			// Focus input after a brief delay
			setTimeout(() => {
				overscrollUnlockInput?.focus();
			}, 100);
		};
		window.addEventListener('showOverscrollUnlockForHide', handleShowOverscrollUnlockForHide);

		// Listen for hidden chats auto-locked event
		handleHiddenChatsAutoLocked = () => {
			notificationStore.info($text('chats.hidden_chats.auto_locked.text'));
			// Refresh chat list so hidden chats re-lock and disappear from unlocked list
			chatListCache.markDirty();
			updateChatListFromDB(true);
		};
		window.addEventListener('hiddenChatsAutoLocked', handleHiddenChatsAutoLocked);

		// Listen for hidden chats manually locked event
		const handleHiddenChatsLocked = async () => {
			// Refresh chat list so hidden chats disappear from unlocked list
			chatListCache.markDirty();
			await updateChatListFromDB(true);
		};
		window.addEventListener('hiddenChatsLocked', handleHiddenChatsLocked);

		// Listen for chat hidden event
		handleChatHidden = async (event: Event) => {
			const customEvent = event as CustomEvent<{ chat_id: string }>;
			console.debug('[Chats] Chat hidden event received:', customEvent.detail.chat_id);
			// Refresh chat list to update visibility
			chatListCache.markDirty();
			await updateChatListFromDB(true);
		};
		window.addEventListener('chatHidden', handleChatHidden);
		
		// Listen for chat unhidden event (when a hidden chat is unhidden)
		handleChatUnhidden = async (event: Event) => {
			const customEvent = event as CustomEvent<{ chat_id: string }>;
			const chatId = customEvent.detail.chat_id;
			console.debug('[Chats] Chat unhidden event received:', chatId);
			
			// Mark cache as dirty to force reload
			chatListCache.markDirty();
			
			// Also clear the specific chat from any in-memory caches to ensure fresh load
			// Find and remove the chat from allChatsFromDB if it exists (it will be reloaded)
			const chatIndex = allChatsFromDB.findIndex(c => c.chat_id === chatId);
			if (chatIndex >= 0) {
				// Remove the old chat object (it has stale is_hidden flags)
				allChatsFromDB = allChatsFromDB.filter(c => c.chat_id !== chatId);
			}
			
			// Force refresh from DB - this will reload the chat with correct flags
			await updateChatListFromDB(true);
			
			// Reset overscroll unlock state to ensure it can be triggered again
			// This allows the user to scroll up to open hidden chats section after unhiding
			showOverscrollUnlock = false;
			overscrollUnlockCode = '';
			overscrollUnlockError = '';
			
			// Reset scroll position to top to allow overscroll detection
			// Use requestAnimationFrame to ensure DOM is updated first
			requestAnimationFrame(() => {
				if (activityHistoryElement) {
					activityHistoryElement.scrollTop = 0;
					currentScrollTop = 0;
				}
			});
		};
		window.addEventListener('chatUnhidden', handleChatUnhidden);
		
		// Initial load of incognito chats (only if mode is enabled)
		// Don't use subscription to avoid reactive loops - just check on mount
		await loadIncognitoChats();

		// Perform initial database load - loads and displays chats from IndexedDB immediately
		await initializeAndLoadDataFromDB();
		
		// CRITICAL FIX: Phased sync is now started in +page.svelte to ensure it works on mobile
		// where the sidebar (Chats component) is closed by default and this component never mounts.
		// This component only handles UI updates (loading indicators, list updates) from sync events.
		// Check if sync has already completed - if so, don't show loading indicator
		if ($phasedSyncState.initialSyncCompleted) {
			syncing = false;
			
			// CRITICAL: Expand display limit to show all chats since sync is already done
			// Without this, only the first 20 chats would be visible until the user closes/reopens the sidebar
			if (!allChatsDisplayed) {
				displayLimit = Infinity;
				allChatsDisplayed = true;
				console.debug('[Chats] Sync was already complete on mount, expanded display limit to show all chats');
			}
			
			// CRITICAL: If sync completed before this component mounted, ensure we have the latest data
			// This handles the case where the sidebar was closed during sync (common on mobile)
			await updateChatListFromDB();
		}
	});
	
	/**
		* Initializes the local chatDB and loads the initial list of chats.
		* Called on component mount. Loads and displays chats immediately.
		* NON-BLOCKING: Does not wait for DB init if it's still in progress.
		* Handles database deletion gracefully (e.g., during logout).
		* CRITICAL: Only loads chats if user is authenticated.
		*/
	async function initializeAndLoadDataFromDB() {
		// CRITICAL: Check global cache first to avoid unnecessary DB reads on remount
		// This cache persists across component instances (when sidebar closes/opens)
		const cached = chatListCache.getCache(false);
		if (cached) {
			console.debug("[Chats] Using cached chats on initialize, skipping DB read");
			allChatsFromDB = cached;
			return;
		}
		
		// CRITICAL: For non-authenticated users, load shared chats from IndexedDB
		// For authenticated users, load all chats normally
		if (!$authStore.isAuthenticated) {
			console.debug("[Chats] User not authenticated - loading shared chats from IndexedDB");
			// Call updateChatListFromDB which handles shared chat loading for non-auth users
			await updateChatListFromDB();
			return;
		}
		
		try {
			console.debug("[Chats] Ensuring local database is initialized...");
			// chatDB.init() is idempotent - safe to call multiple times
			// If already initialized, this returns immediately
			try {
				await chatDB.init();
			} catch (initError: any) {
				// If database is being deleted (e.g., during logout), skip database access
				if (initError?.message?.includes('being deleted') || initError?.message?.includes('cannot be initialized')) {
					console.debug("[Chats] Database is being deleted, skipping initialization - demo/legal chats will be shown");
					allChatsFromDB = []; // Clear user chats, keep only demo/legal chats
					return; // Exit early - demo/legal chats are already in visiblePublicChats
				}
				// Re-throw other errors
				throw initError;
			}
			await updateChatListFromDB(); // Load and display chats from IndexedDB
			console.debug("[Chats] Loaded chats from IndexedDB:", allChatsFromDB.length);
		} catch (error) {
			console.error("[Chats] Error initializing/loading chats from DB:", error);
			allChatsFromDB = []; // Reset on error - demo/legal chats will still be shown
		}
	}

	onDestroy(() => {
		window.removeEventListener('language-changed', languageChangeHandler);
		window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChanged);
		window.removeEventListener('userLoggingOut', handleLogoutEvent);
		if (unsubscribeDraftState) unsubscribeDraftState();
		if (unsubscribeAuth) unsubscribeAuth();
		
		chatSyncService.removeEventListener('syncComplete', handleSyncComplete as EventListener);
		chatSyncService.removeEventListener('chatUpdated', handleChatUpdatedEvent as EventListener);
		chatSyncService.removeEventListener('chatDeleted', handleChatDeletedEvent as EventListener);
		chatSyncService.removeEventListener('phase_1_last_chat_ready', handlePhase1LastChatReadyEvent as EventListener);
		chatSyncService.removeEventListener('cachePrimed', handleCachePrimedEvent as EventListener);
		chatSyncService.removeEventListener('syncStatusResponse', handleSyncStatusResponse as EventListener);
		
		// Remove new phased sync event listeners
		chatSyncService.removeEventListener('phase_2_last_20_chats_ready', handlePhase2Last20ChatsReadyEvent as EventListener);
		chatSyncService.removeEventListener('phase_3_last_100_chats_ready', handlePhase3Last100ChatsReadyEvent as EventListener);
		chatSyncService.removeEventListener('phasedSyncComplete', handlePhasedSyncCompleteEvent as EventListener);

		if (handleGlobalChatSelectedEvent) {
			window.removeEventListener('globalChatSelected', handleGlobalChatSelectedEvent);
		}
		if (handleGlobalChatDeselectedEvent) {
			window.removeEventListener('globalChatDeselected', handleGlobalChatDeselectedEvent);
		}

		// Remove context menu event listeners
		if (handleContextMenuEnterSelectMode) {
			window.removeEventListener('chatContextMenuEnterSelectMode', handleContextMenuEnterSelectMode);
		}
		if (handleContextMenuUnselect) {
			window.removeEventListener('chatContextMenuUnselect', handleContextMenuUnselect);
		}
		if (handleContextMenuSelect) {
			window.removeEventListener('chatContextMenuSelect', handleContextMenuSelect);
		}
		window.removeEventListener('chatContextMenuBulkAction', handleContextMenuBulkAction);
		if (handleIncognitoChatsDeleted) {
			window.removeEventListener('incognitoChatsDeleted', handleIncognitoChatsDeleted);
		}

		// Clean up hidden chats event listeners
        if (handleShowHiddenChatUnlock) {
			window.removeEventListener('showHiddenChatUnlock', handleShowHiddenChatUnlock);
		}
		if (handleShowOverscrollUnlockForHide) {
			window.removeEventListener('showOverscrollUnlockForHide', handleShowOverscrollUnlockForHide);
		}
		if (handleHiddenChatsAutoLocked) {
			window.removeEventListener('hiddenChatsAutoLocked', handleHiddenChatsAutoLocked);
		}
		if (handleChatHidden) {
			window.removeEventListener('chatHidden', handleChatHidden);
			if (handleChatUnhidden) {
				window.removeEventListener('chatUnhidden', handleChatUnhidden);
			}
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

		// Update last selected for potential range selection (even when not in select mode)
		lastSelectedChatId = chat.chat_id;

		// CRITICAL: Always save last_opened to IndexedDB when switching chats (before updating UI stores)
		// This ensures tab reload opens the correct chat even if the component unmounts during the update
		// IndexedDB update happens for all users (authenticated and non-authenticated) for tab reload persistence
		// Server sync (via WebSocket) only happens for authenticated users (handled by sendSetActiveChatImpl)
		// SECURITY: Don't store hidden chats as last_opened - they require passcode after page reload
		if (!(chat as any).is_hidden) {
			try {
				const { chatSyncService } = await import('../../services/chatSyncService');
				await chatSyncService.sendSetActiveChat(chat.chat_id);
				console.debug('[Chats] ✅ Updated last_opened in IndexedDB for chat:', chat.chat_id);
			} catch (error) {
				console.error('[Chats] Error updating last_opened in IndexedDB:', error);
				// Don't fail the whole operation if IndexedDB update fails, continue to update UI
			}
		} else {
			console.debug('[Chats] Skipped storing hidden chat as last_opened:', chat.chat_id);
		}

		// Update the persistent store so the selection survives component unmount/remount
		// This happens AFTER IndexedDB is updated to ensure data consistency
		activeChatStore.setActiveChat(chat.chat_id);

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

	/** Handles next chat keyboard shortcut */
	function handleNextChatShortcut() {
		console.debug('[Chats] handleNextChatShortcut called');
		navigateToNextChat();
	}

	/** Handles previous chat keyboard shortcut */
	function handlePreviousChatShortcut() {
		console.debug('[Chats] handlePreviousChatShortcut called');
		navigateToPreviousChat();
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
async function updateChatListFromDB(force = false) { // Corrected function name
	// Debounce rapid calls to prevent multiple simultaneous DB reads
	if (updateChatListDebounceTimer) {
		clearTimeout(updateChatListDebounceTimer);
	}
	
	return new Promise<void>((resolve) => {
		updateChatListDebounceTimer = setTimeout(async () => {
			updateChatListDebounceTimer = null;
			await updateChatListFromDBInternal(force);
			resolve();
		}, UPDATE_DEBOUNCE_MS);
	});
}

async function updateChatListFromDBInternal(force = false) {
	const cacheStats = chatListCache.getStats();
	console.debug("[Chats] Updating chat list from DB...", { force, cacheStats, inProgress: chatListCache.isUpdateInProgress() });

	// Prevent concurrent DB reads
	if (chatListCache.isUpdateInProgress()) {
		console.debug("[Chats] DB read already in progress, skipping duplicate call");
		return;
	}

	// Serve from global cache when possible (unless forced or dirty)
	if (!force) {
		const cached = chatListCache.getCache(false);
		if (cached) {
			console.debug("[Chats] Using cached chats, skipping DB read");
			allChatsFromDB = cached;
			return;
		}
	}

	chatListCache.setUpdateInProgress(true);
	try {
		// CRITICAL: For non-authenticated users, only load shared chats (tracked in sessionStorage)
		// For authenticated users, load all chats normally
		if (!$authStore.isAuthenticated) {
			console.debug("[Chats] User not authenticated - loading only shared chats from IndexedDB");
			
			try {
				// Check if database is being deleted (e.g., during logout)
				try {
					await chatDB.init();
				} catch (initError: any) {
					if (initError?.message?.includes('being deleted') || initError?.message?.includes('cannot be initialized')) {
						console.debug("[Chats] Database unavailable, skipping shared chat load");
						allChatsFromDB = [];
						return;
					}
					throw initError;
				}
				
				// Get shared chat IDs from sessionStorage
				const sharedChatIds = JSON.parse(sessionStorage.getItem('shared_chats') || '[]');
				
				if (sharedChatIds.length > 0) {
					// Load only the shared chats from IndexedDB
					const sharedChats: ChatType[] = [];
					for (const chatId of sharedChatIds) {
						try {
							const chat = await chatDB.getChat(chatId);
							if (chat) {
								sharedChats.push(chat);
							}
						} catch (error) {
							console.warn(`[Chats] Error loading shared chat ${chatId}:`, error);
						}
					}
				allChatsFromDB = sharedChats;
				chatListCache.setCache(sharedChats);
				console.debug(`[Chats] Loaded ${sharedChats.length} shared chat(s) from IndexedDB`);
			} else {
				allChatsFromDB = [];
				chatListCache.setCache([]);
			}
			} catch (error) {
				console.error("[Chats] Error loading shared chats from DB:", error);
				allChatsFromDB = [];
			}
			return; // Exit early - shared chats are now in allChatsFromDB, will be included in allChats derived
		}
		
		const previouslySelectedChatId = selectedChatId;
		// CRITICAL: Check if database is being deleted (e.g., during logout)
		// If so, skip database access and keep only demo/legal chats
		// This prevents errors during logout
		try {
			// Ensure DB is initialized before attempting to read
			await chatDB.init();
		} catch (initError: any) {
			// If database is being deleted or unavailable, skip database access
			if (initError?.message?.includes('being deleted') || initError?.message?.includes('cannot be initialized')) {
				console.debug("[Chats] Database is being deleted, skipping database access - keeping only demo/legal chats");
				// Clear user chats from state (keep only demo/legal chats which are already in visiblePublicChats)
				allChatsFromDB = [];
				// Don't try to re-select chats if database is unavailable
				return;
			}
			// Re-throw other errors
			throw initError;
		}
		console.debug("[Chats] chatDB.init() complete, fetching chats...");
		
		// CRITICAL: Double-check auth state after DB init (auth might have changed during init)
		if (!$authStore.isAuthenticated) {
			console.debug("[Chats] User became unauthenticated during DB init - clearing user chats");
			allChatsFromDB = [];
			selectedChatId = null;
			return;
		}
		
		const chatsFromDb = await chatDB.getAllChats(); // Renamed for clarity inside function
		console.debug(`[Chats] chatDB.getAllChats() returned ${chatsFromDb.length} chats`);
		
		allChatsFromDB = chatsFromDb; // This assignment triggers reactive updates for sorted/grouped lists - Corrected variable
		chatListCache.setCache(chatsFromDb); // Update global cache
		console.debug(`[Chats] Updated internal chat list. Count: ${allChatsFromDB.length}`); // Corrected variable
		
		// Debug: Log first few chat IDs if available
		if (allChatsFromDB.length > 0) {
				const chatIds = allChatsFromDB.slice(0, 3).map(c => c.chat_id).join(', ');
				console.debug(`[Chats] First chat IDs: ${chatIds}${allChatsFromDB.length > 3 ? '...' : ''}`);
		}
		
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
	} finally {
		chatListCache.setUpdateInProgress(false);
	}
}

 /** Handles keydown events on chat items for accessibility (Enter/Space to select). */
    function handleKeyDown(event: KeyboardEvent, chat: ChatType) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleChatClick(chat);
        }
    }

    /**
     * Handle chat item click with keyboard modifier support
     * Supports:
     * - Shift+Click: Select range from last selected (or active chat) to clicked chat
     * - Cmd/Ctrl+Click: Toggle individual selection, enter select mode if needed
     * - Normal click: In select mode, toggle selection; otherwise open chat
     * 
     * Compatible with OS multi-select patterns:
     * - Windows/Linux: Ctrl+Click (toggle), Shift+Click (range)
     * - macOS: Cmd+Click (toggle), Shift+Click (range)
     * These are mouse events and don't interfere with keyboard shortcuts
     */
    function handleChatItemClick(chat: ChatType, event: MouseEvent) {
        const isShift = event.shiftKey;
        const isCmdOrCtrl = event.metaKey || event.ctrlKey; // metaKey for Mac, ctrlKey for Windows/Linux

        // Shift+Click: Select range from last selected (or active chat) to clicked chat
        if (isShift) {
            // Use lastSelectedChatId if available, otherwise fall back to currently active chat
            const rangeStartChatId = lastSelectedChatId || selectedChatId;
            
            if (rangeStartChatId) {
                const allChatsList = flattenedNavigableChats;
                const startIndex = allChatsList.findIndex(c => c.chat_id === rangeStartChatId);
                const currentIndex = allChatsList.findIndex(c => c.chat_id === chat.chat_id);

                if (startIndex !== -1 && currentIndex !== -1) {
                    // Enter select mode if not already in it
                    if (!selectMode) {
                        selectMode = true;
                        selectedChatIds.clear();
                    }

                    // Select all chats in the range
                    const rangeStart = Math.min(startIndex, currentIndex);
                    const rangeEnd = Math.max(startIndex, currentIndex);
                    
                    // Clear existing selection and select only the range
                    selectedChatIds.clear();
                    for (let i = rangeStart; i <= rangeEnd; i++) {
                        selectedChatIds.add(allChatsList[i].chat_id);
                    }
                    selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
                    
                    // Update last selected to the clicked chat
                    lastSelectedChatId = chat.chat_id;
                    
                    console.debug('[Chats] Shift+Click: Selected range from', startIndex, 'to', currentIndex, '(', rangeEnd - rangeStart + 1, 'chats)');
                    return;
                }
            }
        }

        // Cmd/Ctrl+Click: Toggle individual selection, enter select mode if needed
        if (isCmdOrCtrl) {
            // Enter select mode if not already in it
            if (!selectMode) {
                selectMode = true;
                // If we're starting with Cmd+Click, also select the currently active chat if any
                if (selectedChatId) {
                    selectedChatIds.add(selectedChatId);
                    lastSelectedChatId = selectedChatId;
                }
            }

            // Toggle the clicked chat
            if (selectedChatIds.has(chat.chat_id)) {
                selectedChatIds.delete(chat.chat_id);
                // Update lastSelectedChatId to another selected chat if available
                if (lastSelectedChatId === chat.chat_id) {
                    const remaining = Array.from(selectedChatIds);
                    lastSelectedChatId = remaining.length > 0 ? remaining[remaining.length - 1] : null;
                }
            } else {
                selectedChatIds.add(chat.chat_id);
                lastSelectedChatId = chat.chat_id;
            }
            selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
            
            console.debug('[Chats] Cmd/Ctrl+Click: Toggled selection for', chat.chat_id);
            return;
        }

        // Normal click behavior
        if (selectMode) {
            // In select mode: toggle selection
            if (selectedChatIds.has(chat.chat_id)) {
                selectedChatIds.delete(chat.chat_id);
                if (lastSelectedChatId === chat.chat_id) {
                    const remaining = Array.from(selectedChatIds);
                    lastSelectedChatId = remaining.length > 0 ? remaining[remaining.length - 1] : null;
                }
            } else {
                selectedChatIds.add(chat.chat_id);
                lastSelectedChatId = chat.chat_id;
            }
            selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
        } else {
            // Not in select mode: open chat
            handleChatClick(chat);
            // Update lastSelectedChatId for potential future range selection
            lastSelectedChatId = chat.chat_id;
        }
    }

    /**
     * Handle scroll event to detect overscroll at top
     * Shows unlock interface when user scrolls to top and tries to scroll further
     * Closes unlock interface when user scrolls down
     */
    function handleScroll(event: Event) {
        if (!activityHistoryElement) return;
        
        // Update reactive scroll position
        currentScrollTop = activityHistoryElement.scrollTop;
        
        // CRITICAL: Always close unlock interface when scrolling down (scrollTop > 0)
        // This ensures the interface closes immediately when user scrolls away from top
        if (currentScrollTop > 0 && showOverscrollUnlock) {
            showOverscrollUnlock = false;
            overscrollUnlockCode = '';
            overscrollUnlockError = '';
        }
    }
    
    // Reactive effect to close unlock interface when scrolling down
    // This provides a more reliable way to detect scroll changes
    $effect(() => {
        if (currentScrollTop > 0 && showOverscrollUnlock) {
            showOverscrollUnlock = false;
            overscrollUnlockCode = '';
            overscrollUnlockError = '';
        }
    });
    
    /**
     * Handle wheel event to detect overscroll at top (more reliable than scroll event)
     */
    function handleWheel(event: WheelEvent) {
        if (!activityHistoryElement) return;
        
        const scrollTop = activityHistoryElement.scrollTop;
        currentScrollTop = scrollTop; // Update reactive scroll position
        
        // If at top and scrolling up (negative deltaY), show unlock interface
        if (scrollTop === 0 && event.deltaY < 0 && !hiddenChatState.isUnlocked) {
            if (!showOverscrollUnlock) {
                showOverscrollUnlock = true;
                event.preventDefault(); // Prevent default scroll behavior
                setTimeout(() => {
                    overscrollUnlockInput?.focus();
                }, 100);
            }
        }
        // Note: Closing on scroll down is handled by the reactive effect
    }
    
    /**
     * Handle touch events for mobile overscroll detection
     */
    let touchStartY = 0;
    function handleTouchStart(event: TouchEvent) {
        touchStartY = event.touches[0].clientY;
    }
    
    function handleTouchMove(event: TouchEvent) {
        if (!activityHistoryElement) return;
        
        const scrollTop = activityHistoryElement.scrollTop;
        currentScrollTop = scrollTop; // Update reactive scroll position
        
        const touchY = event.touches[0].clientY;
        const deltaY = touchY - touchStartY;
        
        // If at top and pulling down (positive deltaY), show unlock interface
        if (scrollTop === 0 && deltaY > 0 && !hiddenChatState.isUnlocked) {
            if (!showOverscrollUnlock) {
                showOverscrollUnlock = true;
                setTimeout(() => {
                    overscrollUnlockInput?.focus();
                }, 100);
            }
        }
        // Note: Closing on scroll down is handled by the reactive effect
    }
    
    /**
     * Handle code input for overscroll unlock
     */
    function handleOverscrollCodeInput(event: Event) {
        const target = event.target as HTMLInputElement;
        let value = target.value.replace(/[^0-9]/g, ''); // Only allow digits
        value = value.slice(0, 6); // Max 6 digits
        overscrollUnlockCode = value;
        overscrollUnlockError = ''; // Clear error on input
    }
    
    /**
     * Handle overscroll unlock submission
     */
    async function handleOverscrollUnlock(event: Event) {
        event.preventDefault();
        
        if (overscrollUnlockLoading || overscrollUnlockCode.length < 4) return;
        
        overscrollUnlockLoading = true;
        overscrollUnlockError = '';
        
        try {
            // If we're hiding a chat, we need to encrypt it first, then unlock
            // This ensures unlock succeeds even if no existing chats are encrypted with this code
            if (chatIdToHideViaOverscroll) {
                const chatId = chatIdToHideViaOverscroll;
                
                // First, encrypt the chat with the code
                // Import services
                const { hiddenChatService } = await import('../../services/hiddenChatService');
                const { chatDB } = await import('../../services/db');
                
                // Get the chat to hide
                const chatToHide = await chatDB.getChat(chatId);
                if (!chatToHide) {
                    overscrollUnlockError = $text('chats.hidden_chats.unlock_error.text');
                    overscrollUnlockLoading = false;
                    return;
                }
                
                // Get the chat key (decrypt from encrypted_chat_key if needed)
                let chatKey = chatDB.getChatKey(chatId);
                if (!chatKey && chatToHide.encrypted_chat_key) {
                    const { decryptChatKeyWithMasterKey } = await import('../../services/cryptoService');
                    try {
                        chatKey = await decryptChatKeyWithMasterKey(chatToHide.encrypted_chat_key);
                    } catch (error) {
                        console.error('[Chats] Error decrypting chat key for hiding:', error);
                        overscrollUnlockError = $text('chats.hidden_chats.unlock_error.text');
                        overscrollUnlockLoading = false;
                        return;
                    }
                }
                
                if (!chatKey) {
                    overscrollUnlockError = $text('chats.hidden_chats.unlock_error.text');
                    overscrollUnlockLoading = false;
                    return;
                }
                
                // Encrypt chat key with the code (this doesn't unlock, just encrypts)
                const encryptedChatKey = await hiddenChatService.encryptChatKeyWithCode(chatKey, overscrollUnlockCode);
                if (!encryptedChatKey) {
                    overscrollUnlockError = $text('chats.hidden_chats.unlock_error.text');
                    overscrollUnlockLoading = false;
                    return;
                }
                
                // Update chat in database
                const updatedChat = {
                    ...chatToHide,
                    encrypted_chat_key: encryptedChatKey,
                    is_hidden: true
                };
                await chatDB.updateChat(updatedChat);
                
                // Sync to server
                const { chatSyncService } = await import('../../services/chatSyncService');
                await chatSyncService.sendUpdateEncryptedChatKey(chatId, encryptedChatKey);
                
                // Now unlock with the code, passing the encrypted chat key we just created
                // This allows unlock to verify the chat can be decrypted even if getAllChats() hasn't picked it up yet
                const result = await hiddenChatStore.unlock(overscrollUnlockCode, encryptedChatKey);
                
                if (result.success) {
                    showOverscrollUnlock = false;
                    overscrollUnlockCode = '';
                    overscrollUnlockError = '';
                    chatIdToHideViaOverscroll = null;
                    
                    // Refresh chat list to show hidden chats
                    chatListCache.markDirty();
                    await updateChatListFromDB(true);
                } else {
                    // Unlock failed - this shouldn't happen since we just encrypted a chat with this code
                    overscrollUnlockError = $text('chats.hidden_chats.unlock_error.text');
                    overscrollUnlockCode = '';
                    overscrollUnlockInput?.focus();
                }
            } else {
                // Normal unlock flow (not hiding a chat)
                const result = await hiddenChatStore.unlock(overscrollUnlockCode);
                
                if (result.success) {
                    showOverscrollUnlock = false;
                    overscrollUnlockCode = '';
                    overscrollUnlockError = '';
                    
                    // Refresh chat list to show hidden chats
                    chatListCache.markDirty();
                    await updateChatListFromDB(true);
                } else {
                    // Show appropriate error message
                    if (result.decryptedCount === 0) {
                        overscrollUnlockError = $text('chats.hidden_chats.no_hidden_chats_unlocked.text', {
                            default: 'No hidden chats unlocked. The code may be incorrect or no chats are encrypted with this code.'
                        });
                    } else {
                        overscrollUnlockError = $text('chats.hidden_chats.incorrect_code.text');
                    }
                    overscrollUnlockCode = ''; // Clear code on error
                    overscrollUnlockInput?.focus();
                }
            }
        } catch (error) {
            console.error('[Chats] Error unlocking hidden chats:', error);
            overscrollUnlockError = $text('chats.hidden_chats.unlock_error.text');
            overscrollUnlockCode = '';
        } finally {
            overscrollUnlockLoading = false;
        }
    }

    /**
     * Handle unlock modal close
     */
    function handleUnlockModalClose() {
        showHiddenChatUnlock = false;
        isFirstTimeUnlock = false;
        chatIdToHideAfterUnlock = null;
    }

    /**
     * Handle unlock success
     * Note: The unlock result and chat hiding is handled in HiddenChatUnlock component,
     * this is called after successful unlock
     */
    async function handleUnlockSuccess() {
        showHiddenChatUnlock = false;
        
        // Clear the chat ID to hide (it was already handled in HiddenChatUnlock component)
        chatIdToHideAfterUnlock = null;
        
        // Refresh chat list to show hidden chats
        chatListCache.markDirty();
        await updateChatListFromDB(true);
    }

    /**
     * Handle context menu actions from ChatContextMenu
     * Handles entering select mode and individual chat selection/unselection
     * Bulk actions (download/copy/delete) are handled via the 'chatContextMenuBulkAction' event
     */
    function handleContextMenuAction(event: CustomEvent<string>) {
        const action = event.detail;
        console.debug('[Chats] Context menu action received:', action);

        if (action === 'enterSelectMode') {
            selectMode = true;
            selectedChatIds = new Set(); // Create new Set to trigger reactivity and clear selection
            lastSelectedChatId = null; // Clear last selected
            console.debug('[Chats] Entered select mode');
        } else if (action === 'unselect') {
            const chatId = (event as any).detail;
            if (chatId && selectedChatIds.has(chatId)) {
                selectedChatIds.delete(chatId);
                selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
                // Update lastSelectedChatId if needed
                if (lastSelectedChatId === chatId) {
                    const remaining = Array.from(selectedChatIds);
                    lastSelectedChatId = remaining.length > 0 ? remaining[remaining.length - 1] : null;
                }
            }
        } else if (action === 'selectChat') {
            const chatId = (event as any).detail;
            if (chatId) {
                selectedChatIds.add(chatId);
                selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
                lastSelectedChatId = chatId; // Update last selected
            }
        }
    }

    /**
     * Get chat data and messages for a chat ID
     * Handles public chats (demo/legal), regular chats, and incognito chats
     */
    async function getChatDataAndMessages(chatId: string): Promise<{ chat: ChatType | null; messages: Message[] }> {
        // Check if this is a public chat
        if (isPublicChat(chatId)) {
            // Find the chat in visiblePublicChats
            const chat = visiblePublicChats.find(c => c.chat_id === chatId);
            if (chat) {
                const messages = getDemoMessages(chatId, DEMO_CHATS, LEGAL_CHATS);
                return { chat, messages };
            }
            return { chat: null, messages: [] };
        }

        // Check if this is an incognito chat
        const incognitoChat = incognitoChats.find(c => c.chat_id === chatId);
        if (incognitoChat) {
            try {
                const messages = await incognitoChatService.getMessagesForChat(chatId);
                return { chat: incognitoChat, messages };
            } catch (error) {
                console.error(`[Chats] Error getting incognito chat data for ${chatId}:`, error);
                return { chat: null, messages: [] };
            }
        }

        // For regular chats, get from database
        try {
            const chat = await chatDB.getChat(chatId);
            if (!chat) {
                return { chat: null, messages: [] };
            }
            
            const messages = await chatDB.getMessagesForChat(chatId);
            return { chat, messages };
        } catch (error: any) {
            // If database is being deleted, return empty
            if (error?.message?.includes('being deleted') || error?.message?.includes('cannot be initialized')) {
                console.debug(`[Chats] Database unavailable for chat ${chatId}`);
                return { chat: null, messages: [] };
            }
            console.error(`[Chats] Error getting chat data for ${chatId}:`, error);
            return { chat: null, messages: [] };
        }
    }

    /**
     * Handle bulk copy - combine all selected chats into one code block
     * Creates a valid YAML structure with a 'chats' key containing a list of chat objects
     */
    async function handleBulkCopy() {
        if (selectedChatIds.size === 0) return;

        try {
            console.debug('[Chats] Starting bulk copy for', selectedChatIds.size, 'chats');
            const { convertChatToYaml } = await import('../../services/chatExportService');
            
            const chatObjects: any[] = [];
            
            // Process each selected chat
            for (const chatId of selectedChatIds) {
                const { chat, messages } = await getChatDataAndMessages(chatId);
                if (!chat) {
                    console.warn(`[Chats] Chat ${chatId} not found for bulk copy`);
                    continue;
                }

                // Convert to YAML with link (for clipboard) - this returns a string
                // We need to parse it back to an object to combine into a proper structure
                const yamlContent = await convertChatToYaml(chat, messages, true);
                
                // Create chat object structure for the combined YAML
                const { generateChatLink } = await import('../../services/chatExportService');
                const chatData: any = {
                    chat: {
                        title: null,
                        exported_at: new Date().toISOString(),
                        message_count: messages.length,
                        draft: null,
                        link: generateChatLink(chat.chat_id)
                    },
                    messages: []
                };
                
                // Get decrypted title
                const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
                if (metadata?.title) {
                    chatData.chat.title = metadata.title;
                }
                
                // Add draft if present
                if (chat.encrypted_draft_md) {
                    try {
                        const isCleartextDraft = !chat.encrypted_draft_md.includes('encrypted:') && 
                                                 !chat.encrypted_draft_md.startsWith('v1:') &&
                                                 chat.encrypted_draft_md.length < 1000;
                        if (isCleartextDraft) {
                            chatData.chat.draft = chat.encrypted_draft_md;
                        } else {
                            const { decryptWithMasterKey } = await import('../../services/cryptoService');
                            const decryptedDraft = decryptWithMasterKey(chat.encrypted_draft_md);
                            if (decryptedDraft) {
                                chatData.chat.draft = decryptedDraft;
                            }
                        }
                    } catch (error) {
                        console.error('[Chats] Error processing draft:', error);
                    }
                }
                
                // Add messages
                for (const message of messages) {
                    const messageData: any = {
                        role: message.role,
                        completed_at: new Date(message.created_at * 1000).toISOString()
                    };
                    
                    if (message.role === 'assistant' && message.category) {
                        messageData.assistant_category = message.category;
                    }
                    
                    if (typeof message.content === 'string') {
                        messageData.content = message.content;
                    } else if (message.content && typeof message.content === 'object') {
                        const { tipTapToCanonicalMarkdown } = await import('../../message_parsing/serializers');
                        const markdown = tipTapToCanonicalMarkdown(message.content);
                        messageData.content = markdown;
                    } else {
                        messageData.content = '';
                    }
                    
                    chatData.messages.push(messageData);
                }
                
                chatObjects.push(chatData);
            }

            if (chatObjects.length === 0) {
                notificationStore.error('No chats could be copied');
                return;
            }

            // Create proper YAML structure with chats list
            const yamlData = {
                chats: chatObjects
            };
            
            // Convert to YAML string using local converter
            const yamlString = convertObjectToYamlString(yamlData);
            const codeBlock = `\`\`\`yaml\n${yamlString}\n\`\`\``;

            // Copy to clipboard
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(codeBlock);
            } else {
                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = codeBlock;
                textArea.style.position = 'fixed';
                textArea.style.opacity = '0';
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
            }

            console.debug('[Chats] Bulk copy completed:', chatObjects.length, 'chats');
            notificationStore.success(`Copied ${chatObjects.length} chat${chatObjects.length > 1 ? 's' : ''} to clipboard`);
        } catch (error) {
            console.error('[Chats] Error in bulk copy:', error);
            notificationStore.error('Failed to copy chats. Please try again.');
        }
    }

    /**
     * Convert JavaScript object to YAML string
     * Simple YAML conversion for chat export
     */
    function convertObjectToYamlString(data: any): string {
        const yamlLines: string[] = [];
        
        function convertValue(key: string, value: any, indent: number = 0): void {
            const spaces = '  '.repeat(indent);
            
            if (value === null || value === undefined) {
                yamlLines.push(`${spaces}${key}: null`);
            } else if (typeof value === 'string') {
                // Handle multiline strings
                if (value.includes('\n')) {
                    yamlLines.push(`${spaces}${key}: |`);
                    const lines = value.split('\n');
                    for (const line of lines) {
                        yamlLines.push(`${spaces}  ${line}`);
                    }
                } else {
                    // Escape quotes in strings
                    const escaped = value.replace(/"/g, '\\"');
                    yamlLines.push(`${spaces}${key}: "${escaped}"`);
                }
            } else if (typeof value === 'number' || typeof value === 'boolean') {
                yamlLines.push(`${spaces}${key}: ${value}`);
            } else if (Array.isArray(value)) {
                yamlLines.push(`${spaces}${key}:`);
                for (const item of value) {
                    if (typeof item === 'object') {
                        yamlLines.push(`${spaces}  -`);
                        for (const [itemKey, itemValue] of Object.entries(item)) {
                            convertValue(itemKey, itemValue, indent + 2);
                        }
                    } else {
                        yamlLines.push(`${spaces}  - ${item}`);
                    }
                }
            } else if (typeof value === 'object') {
                yamlLines.push(`${spaces}${key}:`);
                for (const [objKey, objValue] of Object.entries(value)) {
                    convertValue(objKey, objValue, indent + 1);
                }
            }
        }
        
        for (const [key, value] of Object.entries(data)) {
            convertValue(key, value);
        }
        
        return yamlLines.join('\n');
    }

    /**
     * Handle bulk download - create zip file with folders for each chat (YAML, Markdown, and code files)
     */
    async function handleBulkDownload() {
        if (selectedChatIds.size === 0) return;

        try {
            console.debug('[Chats] Starting bulk download for', selectedChatIds.size, 'chats');
            const { downloadChatsAsZip } = await import('../../services/zipExportService');

            const chats: (typeof allChats)[number][] = [];
            const messagesMap = new Map<string, Message[]>();

            // Collect all chat data
            for (const chatId of selectedChatIds) {
                const { chat, messages } = await getChatDataAndMessages(chatId);
                if (!chat) {
                    console.warn(`[Chats] Chat ${chatId} not found for bulk download`);
                    continue;
                }
                chats.push(chat);
                messagesMap.set(chatId, messages);
            }

            if (chats.length === 0) {
                notificationStore.error('No chats could be downloaded');
                return;
            }

            // Download all chats as zip
            await downloadChatsAsZip(chats, messagesMap);

            console.debug('[Chats] Bulk download completed:', chats.length, 'chats');
            notificationStore.success(`Downloaded ${chats.length} chat${chats.length > 1 ? 's' : ''} as ZIP`);
        } catch (error) {
            console.error('[Chats] Error in bulk download:', error);
            notificationStore.error('Failed to download chats. Please try again.');
        }
    }

    /**
     * Handle bulk delete - delete all selected chats
     */
    async function handleBulkDelete() {
        if (selectedChatIds.size === 0) return;

        // Confirm deletion
        const chatCount = selectedChatIds.size;
        const confirmed = confirm(`Are you sure you want to delete ${chatCount} chat${chatCount > 1 ? 's' : ''}? This action cannot be undone.`);
        if (!confirmed) {
            return;
        }

        try {
            console.debug('[Chats] Starting bulk delete for', selectedChatIds.size, 'chats');
            
            const chatIdsToDelete = Array.from(selectedChatIds);
            let deletedCount = 0;
            const errors: string[] = [];

            // Delete each chat
            for (const chatId of chatIdsToDelete) {
                try {
                    // Check if this is an incognito chat
                    const isIncognitoChat = incognitoChats.find(c => c.chat_id === chatId);
                    if (isIncognitoChat) {
                        // Delete incognito chat from service
                        await incognitoChatService.deleteChat(chatId);
                        // Remove from local state
                        incognitoChats = incognitoChats.filter(c => c.chat_id !== chatId);
                        incognitoChatsTrigger++;
                        chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatId } }));
                        deletedCount++;
                    }
                    // Check if this is a public chat (demo/legal)
                    else if (isDemoChat(chatId) || isLegalChat(chatId)) {
                        if (!$authStore.isAuthenticated) {
                            errors.push(`${chatId}: Please sign up to customize your experience`);
                            continue;
                        }
                        
                        // Hide public chat instead of deleting
                        const currentHidden = $userProfile.hidden_demo_chats || [];
                        if (!currentHidden.includes(chatId)) {
                            const updatedHidden = [...currentHidden, chatId];
                            userProfile.update(profile => ({
                                ...profile,
                                hidden_demo_chats: updatedHidden
                            }));
                            
                            const { userDB } = await import('../../services/userDB');
                            await userDB.updateUserData({ hidden_demo_chats: updatedHidden });
                        }
                        deletedCount++;
                    } else if (!$authStore.isAuthenticated) {
                        // SessionStorage-only chat - delete draft
                        const { deleteSessionStorageDraft } = await import('../../services/drafts/sessionStorageDraftService');
                        deleteSessionStorageDraft(chatId);
                        
                        window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { 
                            detail: { chat_id: chatId, draftDeleted: true } 
                        }));
                        
                        chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatId } }));
                        deletedCount++;
                    } else {
                        // Real chat - delete from IndexedDB and server
                        await chatDB.deleteChat(chatId);
                        chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatId } }));
                        await chatSyncService.sendDeleteChat(chatId);
                        deletedCount++;
                    }
                } catch (error) {
                    console.error(`[Chats] Error deleting chat ${chatId}:`, error);
                    errors.push(`${chatId}: ${error instanceof Error ? error.message : 'Unknown error'}`);
                }
            }

            // Clear selection after deletion
            selectedChatIds = new Set();
            
            if (errors.length > 0) {
                notificationStore.error(`Deleted ${deletedCount} chat${deletedCount > 1 ? 's' : ''}, but ${errors.length} failed`);
            } else {
                notificationStore.success(`Deleted ${deletedCount} chat${deletedCount > 1 ? 's' : ''} successfully`);
            }

            console.debug('[Chats] Bulk delete completed:', deletedCount, 'chats deleted');
        } catch (error) {
            console.error('[Chats] Error in bulk delete:', error);
            notificationStore.error('Failed to delete chats. Please try again.');
        }
    }

</script>

<!--
  Chat List Template
  - Shows a loading indicator or "no chats" message.
  - Iterates through grouped chats (respecting displayLimit for phased loading).
  - Renders each chat item using the ChatComponent.
  - Provides a "Load all chats" button if not all chats are displayed.
  - Shows demo chats for both authenticated and non-authenticated users.
-->
<div class="activity-history-wrapper">
		<!-- Fixed top buttons container -->
		<div class="top-buttons-container">
			<div class="top-buttons">
				{#if selectMode}
					<!-- Select mode controls -->
					<button
						class="select-mode-button"
						onclick={() => {
							// Select all visible chats
							const allVisibleChatIds = new Set(chatsForDisplay.map(c => c.chat_id));
							selectedChatIds = new Set(allVisibleChatIds);
							console.debug('[Chats] Selected all chats:', selectedChatIds.size);
						}}
					>
						{$text('chats.select_all.text')}
					</button>
					<button
						class="select-mode-button"
						onclick={() => {
							selectedChatIds = new Set(); // Create new Set to trigger reactivity
							lastSelectedChatId = null; // Clear last selected to reset range selection
							console.debug('[Chats] Unselected all chats');
						}}
					>
						{$text('chats.unselect_all.text')}
					</button>
					<button
						class="select-mode-button cancel"
						onclick={() => {
							selectMode = false;
							selectedChatIds = new Set(); // Create new Set to trigger reactivity and clear selection
							lastSelectedChatId = null; // Clear last selected to reset range selection
							console.debug('[Chats] Exited select mode and cleared selection');
						}}
					>
						{$text('chats.cancel.text')}
					</button>
				{:else}
					<button
						class="clickable-icon icon_close top-button right"
						aria-label={$text('activity.close.text')}
						onclick={handleClose}
						use:tooltip
					></button>
				{/if}
			</div>
		</div>
		
		<!-- Scrollable content area -->
		<div 
			class="activity-history"
			bind:this={activityHistoryElement}
			onscroll={handleScroll}
			onwheel={handleWheel}
			ontouchstart={handleTouchStart}
			ontouchmove={handleTouchMove}
		>
			{#if syncing}
			<div class="syncing-indicator">{$text('activity.syncing.text')}</div>
		{:else if syncComplete}
			<div class="sync-complete-indicator">{$text('activity.sync_complete.text')}</div>
		{/if}
		
		{#if !allChats || allChats.length === 0}
			<div class="no-chats-indicator">{$text('activity.no_chats.text')}</div>
		{:else}
			<!-- Overscroll unlock interface (shown when user overscrolls at top) -->
			{#if showOverscrollUnlock && !hiddenChatState.isUnlocked}
				<div class="overscroll-unlock-container">
					<div class="overscroll-unlock-content">
						{#if $authStore.isAuthenticated}
							<p class="overscroll-unlock-label">
								<span class="clickable-icon icon_hidden"></span>
								<span>{$text('chats.hidden_chats.show_hidden_chats.text')}</span>
							</p>
							<form onsubmit={handleOverscrollUnlock}>
								<div class="overscroll-unlock-input-wrapper">
									<input
										bind:this={overscrollUnlockInput}
										type="password"
										inputmode="numeric"
										pattern="[0-9]*"
										autocomplete="one-time-code"
										class="overscroll-unlock-input"
										class:error={!!overscrollUnlockError}
										bind:value={overscrollUnlockCode}
										oninput={handleOverscrollCodeInput}
										placeholder={$text('chats.hidden_chats.code_placeholder.text')}
										maxlength="6"
										disabled={overscrollUnlockLoading}
										style="font-family: monospace; letter-spacing: 0.1em;"
									/>
									{#if overscrollUnlockError}
										<div class="overscroll-unlock-error">{overscrollUnlockError}</div>
									{/if}
								</div>
							<button
								type="submit"
								class="overscroll-unlock-button"
								disabled={overscrollUnlockLoading || overscrollUnlockCode.length < 4}
							>
								{#if overscrollUnlockLoading}
									<span class="loading-spinner"></span>
								{:else if chatIdToHideViaOverscroll}
									{$text('chats.hidden_chats.unlock_and_hide_button.text')}
								{:else}
									{$text('chats.hidden_chats.unlock_button.text')}
								{/if}
							</button>
							</form>
							<button
								type="button"
								class="clickable-icon icon_close_up overscroll-unlock-close"
								onclick={() => {
									showOverscrollUnlock = false;
									overscrollUnlockCode = '';
									overscrollUnlockError = '';
									chatIdToHideViaOverscroll = null;
								}}
								aria-label={$text('activity.close.text')}
							></button>
						{:else}
							<p class="overscroll-unlock-info">
								<span class="clickable-icon icon_hidden"></span>
								<span>{$text('chats.hidden_chats.login_required.text')}</span>
							</p>
							<button
								type="button"
								class="clickable-icon icon_close_up overscroll-unlock-close"
								onclick={() => {
									showOverscrollUnlock = false;
									chatIdToHideViaOverscroll = null;
								}}
								aria-label={$text('activity.close.text')}
							></button>
						{/if}
					</div>
				</div>
			{/if}
			<!-- Hidden chats section (shown when unlocked) - reusing overscroll-unlock-container styling -->
			{#if hiddenChatState.isUnlocked && hiddenChats.length > 0}
				<div class="overscroll-unlock-container">
					<div class="overscroll-unlock-content">
						<p class="overscroll-unlock-label">
							<span class="clickable-icon icon_hidden"></span>
							<span>{$text('chats.hidden_chats.title.text')}:</span>
						</p>
						<div class="chat-groups">
							{#each orderedGroupedHiddenChats as [groupKey, groupItems] (groupKey)}
								{#if groupItems.length > 0}
									<div class="chat-group">
										<h2 class="group-title">{getLocalizedGroupTitle(groupKey, $text)}</h2>
										{#each groupItems as chat (chat.chat_id)}
											<div
												role="button"
												tabindex="0"
												class="chat-item hidden-chat-item"
												class:active={selectedChatId === chat.chat_id}
												onclick={(event) => {
													handleChatItemClick(chat, event);
													hiddenChatStore.recordActivity();
												}}
												onkeydown={(e) => {
													if (e.key === 'Enter' || e.key === ' ') {
														e.preventDefault();
														// Create a synthetic mouse event for keyboard navigation
														const syntheticEvent = new MouseEvent('click', {
															bubbles: true,
															cancelable: true
														});
														handleChatItemClick(chat, syntheticEvent);
														hiddenChatStore.recordActivity();
													}
												}}
											>
												<ChatComponent
													{chat}
													activeChatId={selectedChatId}
													{selectMode}
													{selectedChatIds}
												/>
											</div>
										{/each}
									</div>
								{/if}
							{/each}
						</div>
						<!-- Single lock button at the bottom -->
						<button
							type="button"
							class="overscroll-unlock-button"
							onclick={() => {
								hiddenChatStore.lock();
								chatListCache.markDirty();
								updateChatListFromDB(true);
							}}
						>
							<div class="clickable-icon icon_lock"></div>
							<span>{$text('chats.hidden_chats.lock.text')}</span>
						</button>
					</div>
				</div>
			{/if}
			
			<!-- DEBUG: Rendering {allChats.length} chats (demo + real), display limit: {displayLimit}, grouped chats: {Object.keys(groupedChatsForDisplay).length} groups -->
			<div class="chat-groups">
				{#each orderedGroupedChats as [groupKey, groupItems] (groupKey)}
					{#if groupItems.length > 0}
						<div class="chat-group">
							<!-- Pass the translation function `$_` to the utility -->
							<h2 class="group-title">{getLocalizedGroupTitle(groupKey, $text)}</h2>
							{#each groupItems as chat (chat.chat_id)}
								<div
									role="button"
									tabindex="0"
									class="chat-item"
									class:active={selectedChatId === chat.chat_id}
									class:incognito={chat.is_incognito}
									onclick={(event) => {
										handleChatItemClick(chat, event);
									}}
									onkeydown={(e) => {
										// Handle keyboard selection with modifiers
										const isShift = e.shiftKey;
										const isCmdOrCtrl = e.metaKey || e.ctrlKey;
										
										if ((selectMode || isShift || isCmdOrCtrl) && (e.key === 'Enter' || e.key === ' ')) {
											e.preventDefault();
											
											// Shift+Space/Enter: Select range
											if (isShift && lastSelectedChatId) {
												const allChatsList = flattenedNavigableChats;
												const lastIndex = allChatsList.findIndex(c => c.chat_id === lastSelectedChatId);
												const currentIndex = allChatsList.findIndex(c => c.chat_id === chat.chat_id);

												if (lastIndex !== -1 && currentIndex !== -1) {
													if (!selectMode) {
														selectMode = true;
														selectedChatIds.clear();
													}

													const startIndex = Math.min(lastIndex, currentIndex);
													const endIndex = Math.max(lastIndex, currentIndex);
													
													for (let i = startIndex; i <= endIndex; i++) {
														selectedChatIds.add(allChatsList[i].chat_id);
													}
													selectedChatIds = new Set(selectedChatIds);
													lastSelectedChatId = chat.chat_id;
													return;
												}
											}
											
											// Cmd/Ctrl+Space/Enter: Toggle selection
											if (isCmdOrCtrl) {
												if (!selectMode) {
													selectMode = true;
													if (selectedChatId) {
														selectedChatIds.add(selectedChatId);
														lastSelectedChatId = selectedChatId;
													}
												}

												if (selectedChatIds.has(chat.chat_id)) {
													selectedChatIds.delete(chat.chat_id);
													if (lastSelectedChatId === chat.chat_id) {
														const remaining = Array.from(selectedChatIds);
														lastSelectedChatId = remaining.length > 0 ? remaining[remaining.length - 1] : null;
													}
												} else {
													selectedChatIds.add(chat.chat_id);
													lastSelectedChatId = chat.chat_id;
												}
												selectedChatIds = new Set(selectedChatIds);
												return;
											}
											
											// Normal Space/Enter in select mode: toggle selection
											if (selectMode) {
												if (selectedChatIds.has(chat.chat_id)) {
													selectedChatIds.delete(chat.chat_id);
													if (lastSelectedChatId === chat.chat_id) {
														const remaining = Array.from(selectedChatIds);
														lastSelectedChatId = remaining.length > 0 ? remaining[remaining.length - 1] : null;
													}
												} else {
													selectedChatIds.add(chat.chat_id);
													lastSelectedChatId = chat.chat_id;
												}
												selectedChatIds = new Set(selectedChatIds);
												return;
											}
										}
										
										// Fallback to normal keyboard navigation
										handleKeyDown(e, chat);
									}}
									aria-current={selectedChatId === chat.chat_id ? 'page' : undefined}
									aria-label={chat.encrypted_title || 'Unnamed chat'}
								>
									<ChatComponent 
										chat={chat} 
										activeChatId={selectedChatId}
										selectMode={selectMode}
										selectedChatIds={selectedChatIds}
										onToggleSelection={(chatId: string) => {
											if (selectedChatIds.has(chatId)) {
												selectedChatIds.delete(chatId);
												selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
											} else {
												selectedChatIds.add(chatId);
												selectedChatIds = new Set(selectedChatIds); // Trigger reactivity
											}
										}}
									/>
								</div>
							{/each}
						</div>
					{/if}
				{/each}
				
				{#if !allChatsDisplayed && allChats.length > displayLimit}
					<div class="load-more-container">
						<button
							class="load-more-button"
							onclick={() => {
								displayLimit = Infinity;
								allChatsDisplayed = true;
								console.debug('[Chats] User clicked "Load all chats".');
							}}
						>
							{$text('chats.loadMore.button.text')}
							({allChats.length - chatsForDisplay.length} {$text('chats.loadMore.more.text')})
						</button>
					</div>
				{/if}
			</div>
		{/if}

		<KeyboardShortcuts
			on:nextChat={handleNextChatShortcut}
			on:previousChat={handlePreviousChatShortcut}
		/>
	</div>
</div>

<style>
    .activity-history-wrapper {
        display: flex;
        flex-direction: column;
        height: 100%;
        width: 100%;
        overflow: hidden;
        position: relative;
    }

    .activity-history {
        flex: 1;
        padding: 0;
        position: relative;
        overflow-y: auto;
        overflow-x: hidden;
        min-height: 0; /* Important for flex child to enable scrolling */
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
        flex-shrink: 0;
        z-index: 10;
        background-color: var(--color-grey-20);
        padding: 16px 20px;
        border-bottom: 1px solid var(--color-grey-30);
    }

    .top-buttons {
        position: relative;
        height: 32px; /* Ensure container fits buttons */
        display: flex; /* Use flexbox for easier alignment if needed */
        justify-content: flex-end; /* Align close button to the right */
    }

    .top-button {
        /* Removed absolute positioning if using flexbox */
        display: flex;
        align-items: center;
    }

    .top-button.right {
       /* No specific positioning needed if using flex end */
       margin-left: auto;
    }

    .select-mode-button {
        padding: 8px 16px;
        border: 1px solid var(--color-grey-40);
        background-color: var(--color-grey-20);
        color: var(--color-text);
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.9em;
        transition: background-color 0.2s ease;
        margin-right: 8px;
    }

    .select-mode-button:hover {
        background-color: var(--color-grey-25);
    }

    .select-mode-button.cancel {
        margin-left: auto;
        color: var(--color-grey-60);
    }

    .select-mode-button:focus-visible {
        outline: 2px solid var(--color-primary-focus);
        outline-offset: 1px;
    }

    .chat-groups {
        display: flex;
        flex-direction: column;
        gap: 20px; /* Slightly reduced gap */
        position: relative;
        padding: 16px 8px 16px 8px; /* Add horizontal padding */
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

    .no-chats-indicator,
    .syncing-indicator,
    .sync-complete-indicator {
        text-align: center;
        padding: 12px 20px;
        color: var(--color-grey-60);
        font-style: italic;
    }

    .syncing-indicator,
    .sync-complete-indicator {
        background-color: var(--color-grey-15);
        border-radius: 8px;
        margin: 8px;
        font-weight: 500;
        font-size: 0.9em;
    }

    .sync-complete-indicator {
        background-color: var(--color-success-bg, var(--color-grey-15));
        color: var(--color-success-text, var(--color-grey-70));
        animation: fadeOut 1s ease-in-out;
    }

    @keyframes fadeOut {
        0% { opacity: 1; }
        70% { opacity: 1; }
        100% { opacity: 0; }
    }

    .chat-item {
        transition: background-color 0.15s ease;
        border-radius: 8px; /* Apply border-radius directly */
        cursor: pointer;
    }

    /*
    Only apply hover styles on devices that support true hover (not touch devices).
    On touch devices, the :hover pseudo-class can be falsely triggered during scrolling,
    causing unwanted visual feedback. The (hover: hover) media query only matches devices
    that support true hover interactions (e.g., desktop with mouse), not touch devices.
    This prevents false highlights when scrolling on phones/tablets while preserving
    the hover effect on desktop where it's intentional user feedback.
    */
    @media (hover: hover) {
        .chat-item:hover {
            background-color: var(--color-grey-25); /* Slightly different hover */
        }
    }

    .chat-item.active {
        background-color: var(--color-grey-30);
    }

    /* Incognito chat styling */
    .chat-item.incognito {
        background-color: var(--color-grey-30); /* Darker background */
        border-left: 3px solid var(--color-grey-50);
    }

    .chat-item.incognito.active {
        background-color: var(--color-grey-35);
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

    /* Hidden chat items */
    .hidden-chat-item {
        opacity: 0.9;
    }

    /* Overscroll unlock interface */
    .overscroll-unlock-container {
        padding: 20px;
        background: var(--color-grey-10);
        border-bottom: 1px solid var(--color-grey-30);
        animation: slideDown 0.3s ease-out;
    }

    @keyframes slideDown {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .overscroll-unlock-content {
        display: flex;
        flex-direction: column;
        gap: 12px;
        max-width: 400px;
        margin: 0 auto;
    }

    .overscroll-unlock-label,
    .overscroll-unlock-info {
        margin: 0;
        color: var(--color-grey-70);
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .overscroll-unlock-label .clickable-icon,
    .overscroll-unlock-info .clickable-icon {
        flex-shrink: 0;
    }

    .overscroll-unlock-input-wrapper {
        display: flex;
        flex-direction: column;
        padding-bottom: 10px;
    }

    .overscroll-unlock-input {
        width: auto;
    }

    .overscroll-unlock-error {
        color: var(--color-error);
        font-size: 0.85em;
        margin-top: 4px;
    }

    .overscroll-unlock-button {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }
    
    .overscroll-unlock-button .clickable-icon {
        flex-shrink: 0;
    }


    .overscroll-unlock-button:disabled {
        background-color: var(--color-grey-40);
        cursor: not-allowed;
        opacity: 0.6;
    }

    .loading-spinner {
        width: 16px;
        height: 16px;
        border: 2px solid var(--color-grey-30);
        border-top-color: var(--color-button-text);
        border-radius: 50%;
        animation: spin 0.6s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }

    .overscroll-unlock-close {
        margin: 8px auto 0;
        transition: transform 0.2s ease, opacity 0.2s ease, scale 0.2s ease;
    }

    .overscroll-unlock-close:hover {
        transform: scale(1.1), rotate(90deg);
        opacity: 0.8;
    }
</style>

<!-- Hidden chat unlock modal -->
<HiddenChatUnlock
    show={showHiddenChatUnlock}
    isFirstTime={isFirstTimeUnlock}
    chatIdToHide={chatIdToHideAfterUnlock}
    onClose={handleUnlockModalClose}
    onUnlock={handleUnlockSuccess}
/>
