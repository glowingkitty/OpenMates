<script lang="ts">
	import { onMount, onDestroy, createEventDispatcher, tick } from 'svelte';
	import { text } from '@repo/ui'; // Import text store for translations
	import ChatComponent from './Chat.svelte'; // Renamed to avoid conflict with Chat type
	import { panelState } from '../../stores/panelStateStore';
	import { authStore } from '../../stores/authStore';
	import { chatDB } from '../../services/db';
	import { draftEditorUIState } from '../../services/drafts/draftState'; // Renamed import
	import { LOCAL_CHAT_LIST_CHANGED_EVENT } from '../../services/drafts/draftConstants';
	import type { Chat as ChatType, Message } from '../../types/chat'; // Removed unused ChatComponentVersions, TiptapJSON
	import { tooltip } from '../../actions/tooltip';
	import KeyboardShortcuts from '../KeyboardShortcuts.svelte';
	import { chatSyncService } from '../../services/chatSyncService';
	import { sortChats } from './utils/chatSortUtils'; // Refactored sorting logic
	import { groupChats, getLocalizedGroupTitle } from './utils/chatGroupUtils'; // Refactored grouping logic
	import { locale as svelteLocaleStore, waitLocale } from 'svelte-i18n'; // For date formatting in getLocalizedGroupTitle
	import { get } from 'svelte/store'; // For reading svelteLocaleStore value
	import { chatMetadataCache } from '../../services/chatMetadataCache'; // For cache invalidation
	import { chatListCache } from '../../services/chatListCache'; // Global cache for chat list
	import { phasedSyncState } from '../../stores/phasedSyncStateStore'; // For tracking sync state across component lifecycle
	import { activeChatStore } from '../../stores/activeChatStore'; // For persisting active chat across component lifecycle
	import { userProfile } from '../../stores/userProfile'; // For hidden_demo_chats
	import { INTRO_CHATS, LEGAL_CHATS, isDemoChat, translateDemoChat, isLegalChat, getDemoMessages, isPublicChat, addCommunityDemo, getAllCommunityDemoChats, communityDemoStore, getLocalContentHashes } from '../../demo_chats'; // For demo/intro chats
	import { convertDemoChatToChat } from '../../demo_chats/convertToChat'; // For converting demo chats to Chat type
	import { getAllDraftChatIdsWithDrafts } from '../../services/drafts/sessionStorageDraftService'; // Import sessionStorage draft service
	import { notificationStore } from '../../stores/notificationStore'; // For notifications
	import { incognitoChatService } from '../../services/incognitoChatService'; // Import incognito chat service
	import { incognitoMode } from '../../stores/incognitoModeStore'; // Import incognito mode store
	import { hiddenChatStore } from '../../stores/hiddenChatStore'; // Import hidden chat store
	import HiddenChatUnlock from './HiddenChatUnlock.svelte'; // Import hidden chat unlock component
	import { getApiEndpoint } from '../../config/api'; // For API calls
	import { isSelfHosted } from '../../stores/serverStatusStore'; // For self-hosted detection (initialized once at app load)
	// NOTE: Demo chats are now decrypted server-side, so decryptShareKeyBlob is no longer needed here

	const dispatch = createEventDispatcher();

// --- Debounce timer for updateChatListFromDB calls ---
let updateChatListDebounceTimer: any = null;
const UPDATE_DEBOUNCE_MS = 300; // 300ms debounce for updateChatListFromDB calls

	// --- Component State ---
	let allChatsFromDB: ChatType[] = $state([]); // Holds all chats fetched from chatDB
	// Syncing indicator: true when authenticated AND sync has not completed yet
	// Using $derived ensures reactivity to both authStore and phasedSyncState changes
	let syncing = $derived($authStore.isAuthenticated && !$phasedSyncState.initialSyncCompleted);
	let syncComplete = $state(false); // Shows "Sync complete" message briefly
	let selectedChatId: string | null = $state(null); // ID of the currently selected chat (synced with activeChatStore)
	let _chatIdToSelectAfterUpdate: string | null = $state(null); // Helper to select a chat after list updates
	let currentServerSortOrder: string[] = $state([]); // Server's preferred sort order for chats
	let sessionStorageDraftUpdateTrigger = $state(0); // Trigger for reactivity when sessionStorage drafts change

	// Phased Loading State — 3-tier progressive display:
	// Tier 1 ('initial'): Show first 20 chats from IndexedDB (fast initial render during sync)
	// Tier 2 ('all_local'): Show all ~100 chats from IndexedDB (after sync or user clicks "Show more")
	// Tier 3 ('loading_server'): Fetching additional older chats from server on demand
	let loadTier: 'initial' | 'all_local' | 'loading_server' = $state('initial');
	let olderChatsFromServer: ChatType[] = $state([]); // Chats beyond initial 100, in-memory only (NOT in IndexedDB)
	let hasMoreOnServer = $state(false); // Whether the server has more chats beyond what's been loaded
	let serverPaginationOffset = $state(100); // Next offset for fetching older chats from server
	let loadingMoreChats = $state(false); // True while a "load more" request is in-flight
	let totalServerChatCount = $state(0); // Total chat count reported by the server

	// Select Mode State
	let selectMode = $state(false); // Whether we're in multi-select mode
	let selectedChatIds = $state<Set<string>>(new Set()); // Set of selected chat IDs
	let lastSelectedChatId: string | null = $state(null); // Track last selected chat for range selection

	// Hidden Chats State
	let showHiddenChatUnlock = $state(false); // Show unlock modal (for context menu hide action)
	let isFirstTimeUnlock = $state(false); // True if setting code for first time
	let chatIdToHideAfterUnlock: string | null = $state(null); // Chat ID to hide after unlock
	let hiddenChatState = $derived($hiddenChatStore); // Reactive hidden chat state
	
	// Inline unlock form state (shown when "Show hidden chats" button is clicked or when hiding a chat)
	let showInlineUnlock = $state(false); // Show inline unlock form
	let inlineUnlockCode = $state(''); // Code input for inline unlock
	let inlineUnlockError = $state(''); // Error message for inline unlock
	let inlineUnlockLoading = $state(false); // Loading state for inline unlock
	let inlineUnlockInput: HTMLInputElement | null = $state(null); // Reference to input element
	let chatIdToHideAfterInlineUnlock: string | null = $state(null); // Chat ID to hide after inline unlock
	
	// Scroll state for ensuring scroll can reach 0 when hidden chats are unlocked
	let activityHistoryElement: HTMLDivElement | null = $state(null); // Reference to scrollable container
	
	// Self-hosted mode state is now managed by serverStatusStore
	// isSelfHosted is imported from the store (initialized once at app load to prevent UI flashing)
	// When true, legal chats (privacy, terms, imprint) are hidden from the sidebar.

	// --- Reactive Effects ---
	
	// Reactive sync: Update selectedChatId when activeChatStore changes (e.g., from deep links)
	// This ensures the chat gets highlighted when loaded via deep link after component mount
	// IMPORTANT: $effect must be at the top level, not inside onMount (Svelte 5 requirement)
	$effect(() => {
		const activeChat = $activeChatStore;
		console.debug('[Chats] $effect triggered - activeChat:', activeChat, 'selectedChatId:', selectedChatId);
		if (activeChat && activeChat !== selectedChatId) {
			console.debug('[Chats] Syncing selectedChatId with activeChatStore:', activeChat);
			selectedChatId = activeChat;
		} else if (activeChat && activeChat === selectedChatId) {
			console.debug('[Chats] selectedChatId already matches activeChat:', activeChat);
		} else if (!activeChat) {
			console.debug('[Chats] activeChat is null/empty');
		}
	});

	// --- Reactive Computations for Display ---

	// Get filtered public chats (intro + community demos + legal) - exclude hidden ones for authenticated users
	// 
	// ARCHITECTURE:
	// - INTRO_CHATS: Static intro chats bundled with the app (welcome, what-makes-different)
	// - Community demos: Dynamic demo chats fetched from server, stored in communityDemoStore (in-memory)
	// - Legal chats: Legal documents (privacy, terms, imprint) - only for non-self-hosted
	//
	// Legal chats are shown only for non-self-hosted instances - they're OpenMates-specific documents
	// For self-hosted instances, legal chats are excluded because operators should provide their own legal docs
	// Translates demo chats to the user's locale before converting to Chat format
	// Legal chats skip translation (they use plain text)
	let visiblePublicChats = $derived((() => {
		// Reference the locale store to make the derived recalculate when language changes
		// This triggers reactivity whenever the user changes the language
		void $svelteLocaleStore;
		
		// Reference the text store to ensure reactivity when translations are loaded
		void $text;
		
		// Reference the communityDemoStore to trigger reactivity when community demos are loaded
		void $communityDemoStore;
		
		console.debug('[Chats] Recalculating visiblePublicChats. Community demos count:', getAllCommunityDemoChats().length);
		
		// Get hidden IDs for authenticated users (shared between demo and legal chats)
		const hiddenIds = $authStore.isAuthenticated ? ($userProfile.hidden_demo_chats || []) : [];
		
		// 1. Static intro chats (bundled with app)
		let introChats: ChatType[] = [];
		if (!$authStore.isAuthenticated) {
			introChats = INTRO_CHATS
				.map(demo => translateDemoChat(demo)) // Translate to user's locale
				.map(demo => {
					const chat = convertDemoChatToChat(demo);
					chat.group_key = 'intro';
					return chat;
				});
		} else {
			// For authenticated users, filter out hidden intro chats
			introChats = INTRO_CHATS
				.filter(demo => !hiddenIds.includes(demo.chat_id))
				.map(demo => translateDemoChat(demo)) // Translate to user's locale
				.map(demo => {
					const chat = convertDemoChatToChat(demo);
					chat.group_key = 'intro';
					return chat;
				});
		}
		
		// 2. Community demo chats (fetched from server, stored in-memory)
		// These are shown for all users (authenticated and non-authenticated)
		let communityChats: ChatType[] = [];
		communityChats = getAllCommunityDemoChats()
			.filter(chat => !hiddenIds.includes(chat.chat_id))
			.map(chat => ({
				...chat,
				group_key: 'examples' // Community demos go in "Examples" group
			}));
		
		// 3. Legal chats (ONLY for non-self-hosted instances)
		// Self-hosted edition is for personal/internal team use only, so legal docs aren't needed:
		// - No imprint: only required for commercial/public-facing websites
		// - No privacy policy: GDPR "household exemption" applies to personal/private use
		// - No terms of service: no third-party service relationship exists
		let legalChats: ChatType[] = [];
		if (!$isSelfHosted) {
			// Filter out hidden legal chats for authenticated users (uses same hidden_demo_chats mechanism)
			// Legal chats skip translation (they use plain text, not translation keys)
			legalChats = LEGAL_CHATS
				.filter(legal => !hiddenIds.includes(legal.chat_id)) // Filter out hidden legal chats too
				.map(legal => translateDemoChat(legal)) // Legal chats skip translation but still go through function
				.map(legal => {
					const chat = convertDemoChatToChat(legal);
					chat.group_key = 'legal';
					return chat;
				});
		}
		
		return [...introChats, ...communityChats, ...legalChats];
	})());

	// Combine public chats (intro + community demos + legal) with real chats from IndexedDB
	// Also include sessionStorage-only chats for non-authenticated users (new chats with drafts)
	// Also include shared chats for non-authenticated users (loaded from IndexedDB but marked for cleanup)
	// Also include incognito chats (stored in sessionStorage, not IndexedDB)
	// Filter out any duplicates (legal chats might be in IndexedDB if previously opened)
	//
	// ARCHITECTURE:
	// - Intro chats: Static, bundled with app, stored in INTRO_CHATS array (in-memory)
	// - Community demos: Dynamic, fetched from server, stored in communityDemoStore (in-memory)
	// - Legal chats: Static, bundled with app, stored in LEGAL_CHATS array (in-memory)
	// - Real chats: User's actual chats, stored in IndexedDB
	// - Shared chats: Chats shared with user, stored in IndexedDB (temporary for viewing)
	// - Incognito chats: Ephemeral chats, stored in sessionStorage
	let incognitoChatsTrigger = $state(0); // Trigger for reactivity when incognito chats change
	let incognitoChats: ChatType[] = $state([]); // Cache for incognito chats
	
	let allChats = $derived((() => {
		void visiblePublicChats;

		// 1. Process real chats from IndexedDB (exclude public chats - they come from visiblePublicChats)
		const processedRealChats = allChatsFromDB
			.filter(chat => !isLegalChat(chat.chat_id) && !isPublicChat(chat.chat_id));

		// 2. Identify which visiblePublicChats should be excluded (already in IndexedDB for some reason)
		// CRITICAL: We don't filter out public chats from visiblePublicChats even if they are in the DB,
		// because they are already filtered out of processedRealChats. This ensures they always show up.
		const filteredPublicChats = visiblePublicChats;
		
		// Reference incognitoChatsTrigger to make this reactive to incognito chat changes
		void incognitoChatsTrigger;
		
		// Load incognito chats (only if incognito mode is enabled)
		// This is async, so we use the cached incognitoChats array which is updated via effect
		const _incognitoChats = incognitoChats;
		
		// CRITICAL: For non-authenticated users, include sessionStorage-only chats (new chats with drafts)
		// These are chats that have drafts in sessionStorage but don't exist in IndexedDB yet
		// Reference sessionStorageDraftUpdateTrigger to make this reactive to draft changes
		void sessionStorageDraftUpdateTrigger; // Reference to trigger reactivity
		let sessionStorageChats: ChatType[] = [];
		let sharedChats: ChatType[] = [];
		if (!$authStore.isAuthenticated) {
			const sessionDraftChatIds = getAllDraftChatIdsWithDrafts();
			// Filter out demo/legal chat IDs (they're already in visiblePublicChats)
			// and chat IDs that are already in IndexedDB
			const existingChatIds = new Set([
				...filteredPublicChats.map(c => c.chat_id),
				...processedRealChats.map(c => c.chat_id),
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
			// Shared chat keys are now stored in IndexedDB (sharedChatKeyStorage) instead of sessionStorage
			// The sharedChats array will be populated asynchronously via loadSharedChatsForNonAuth()
			// For now, include any chats that have keys in the memory cache (chatDB.chatKeys)
			for (const chat of processedRealChats) {
				if (!existingChatIds.has(chat.chat_id)) {
					// Check if we have a key for this chat (indicating it's a shared chat we can decrypt)
					const hasKey = chatDB.getChatKey(chat.chat_id) !== null;
					if (hasKey) {
						sharedChats.push(chat);
						console.debug('[Chats] Added shared chat to list (has key in cache):', chat.chat_id);
					}
				}
			}
		}
		
		// CRITICAL SAFEGUARD: Deduplicate the final array by chat_id
		// ORDER MATTERS: We put processedRealChats first so that dynamic demo chats (which have group_key='examples')
		// are preferred over hardcoded visiblePublicChats (which might have group_key='intro')
		// olderChatsFromServer are appended last — these are in-memory-only older chats loaded on demand
		const combinedChats = [...processedRealChats, ...filteredPublicChats, ...sessionStorageChats, ...sharedChats, ..._incognitoChats, ...olderChatsFromServer];
		const seenIds = new Set<string>();
		const deduplicatedChats: ChatType[] = [];
		for (const chat of combinedChats) {
			if (!seenIds.has(chat.chat_id)) {
				seenIds.add(chat.chat_id);
				deduplicatedChats.push(chat);
			} else {
				// Only log if it's not an expected overlap (like a public chat already in list)
				if (!isPublicChat(chat.chat_id)) {
					console.warn(`[Chats] DUPLICATE CHAT DETECTED AND FILTERED: ${chat.chat_id} - this indicates a bug in chat creation`);
				}
			}
		}
		
		// Final log for debugging community demo categorization
		const communityDemoCount = deduplicatedChats.filter(c => c.group_key === 'examples').length;
		if (communityDemoCount > 0) {
			console.debug(`[Chats] Found ${communityDemoCount} community demo chat(s) in 'examples' group`);
		}
		
		return deduplicatedChats;
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
		
		// 1. First, add standard time groups in the defined order (Today, Yesterday, etc.)
		const timeGroups = ['today', 'yesterday', 'previous_7_days', 'previous_30_days'];
		for (const groupKey of timeGroups) {
			if (groups[groupKey] && groups[groupKey].length > 0) {
				orderedEntries.push([groupKey, groups[groupKey]]);
			}
		}
		
		// 2. Then, add any remaining time groups (e.g., month groups) in their order
		// CRITICAL: Include 'shared_by_others' in static groups - these are chats shared with user by others
		const staticGroups = ['shared_by_others', 'intro', 'examples', 'legal'];
		for (const [groupKey, groupItems] of Object.entries(groups)) {
			if (!timeGroups.includes(groupKey) && !staticGroups.includes(groupKey) && groupItems.length > 0) {
				orderedEntries.push([groupKey, groupItems]);
			}
		}

		// 3. Finally, add the static sections in the specified order
		// shared_by_others comes first (before intro/examples/legal) since these are chats from real users
		for (const groupKey of staticGroups) {
			if (groups[groupKey] && groups[groupKey].length > 0) {
				orderedEntries.push([groupKey, groups[groupKey]]);
			}
		}
		
		return orderedEntries;
	})());

	// Static group keys — chats in these groups (intro, examples, legal, shared_by_others) are always shown,
	// regardless of the phased loading tier. Only user chats (time-based groups) are subject to the display limit.
	const STATIC_GROUP_KEYS = ['shared_by_others', 'intro', 'examples', 'legal'];

	// Apply display limit for phased loading. This list is used for rendering groups using Svelte 5 runes
	// Tier 1 ('initial'): Show first 20 USER chats (fast render during sync), plus all static chats (intro, examples, legal)
	// Tier 2+ ('all_local', 'loading_server'): Show all chats (IndexedDB + server-loaded)
	// IMPORTANT: The limit of 20 applies only to user chats — intro, example, and legal chats are always shown
	let chatsForDisplay = $derived((() => {
		if (loadTier !== 'initial') {
			return sortedAllChatsFiltered;
		}
		// Tier 1: Separate user chats from static chats, limit only user chats to 20
		const userChats: ChatType[] = [];
		const staticChats: ChatType[] = [];
		for (const chat of sortedAllChatsFiltered) {
			if (chat.group_key && STATIC_GROUP_KEYS.includes(chat.group_key)) {
				staticChats.push(chat);
			} else {
				userChats.push(chat);
			}
		}
		return [...userChats.slice(0, 20), ...staticChats];
	})());
	
	// Determine if "Show more" button should be visible
	// Tier 1 ('initial'): Show if there are more than 20 USER chats (excludes intro/example/legal)
	// Tier 2 ('all_local'): Show if server has more chats beyond what's loaded
	// Tier 3 ('loading_server'): Keep visible (disabled) while fetching
	let showMoreButtonVisible = $derived((() => {
		if (loadTier === 'initial') {
			const userChatCount = sortedAllChatsFiltered.filter(
				c => !c.group_key || !STATIC_GROUP_KEYS.includes(c.group_key)
			).length;
			return userChatCount > 20;
		}
		if (loadTier === 'loading_server') {
			return true; // Keep button visible while loading
		}
		// 'all_local' — show if server has more chats
		return hasMoreOnServer;
	})());

	// Group the chats intended for display using Svelte 5 runes
	// The `$_` (translation function) is passed to `getLocalizedGroupTitle` when it's called in the template
	let groupedChatsForDisplay = $derived(groupChats(chatsForDisplay));
	
	// Get ordered group entries for display
	// Split grouped chats into user groups (time-based) and static groups (intro, examples, legal).
	// This allows the "Show more" button to be rendered between user chats and static sections,
	// so users don't have to scroll past intro/example/legal chats to find it.
	// NOTE: STATIC_GROUP_KEYS is declared earlier (before chatsForDisplay) since it's also used for phased loading.
	
	let orderedUserChatGroups = $derived((() => {
		const groups = groupedChatsForDisplay;
		const orderedEntries: [string, ChatType[]][] = [];
		
		// 1. First, add standard time groups in the defined order (Today, Yesterday, etc.)
		const timeGroups = ['today', 'yesterday', 'previous_7_days', 'previous_30_days'];
		for (const groupKey of timeGroups) {
			if (groups[groupKey] && groups[groupKey].length > 0) {
				orderedEntries.push([groupKey, groups[groupKey]]);
			}
		}
		
		// 2. Then, add any remaining time groups (e.g., month groups) in their order
		for (const [groupKey, groupItems] of Object.entries(groups)) {
			if (!timeGroups.includes(groupKey) && !STATIC_GROUP_KEYS.includes(groupKey) && groupItems.length > 0) {
				orderedEntries.push([groupKey, groupItems]);
			}
		}
		
		return orderedEntries;
	})());
	
	let orderedStaticChatGroups = $derived((() => {
		const groups = groupedChatsForDisplay;
		const orderedEntries: [string, ChatType[]][] = [];
		
		// Add static sections in the specified order
		// shared_by_others comes first (before intro/examples/legal) since these are chats from real users
		for (const groupKey of STATIC_GROUP_KEYS) {
			if (groups[groupKey] && groups[groupKey].length > 0) {
				orderedEntries.push([groupKey, groups[groupKey]]);
			}
		}
		
		return orderedEntries;
	})());
	


	// Flattened list of ALL sorted chats (excluding those processing metadata), used for keyboard navigation and selection logic using Svelte 5 runes
	// This ensures navigation can cycle through all available chats, even if not all are rendered yet.
	let flattenedNavigableChats = $derived(sortedAllChatsFiltered);
	
	// --- Event Handlers & Lifecycle ---

	let languageChangeHandler: () => void; // For UI text updates on language change
	let handleLanguageChangeForDemos: () => void; // For reloading demo chats on language change
	let languageChangeDemoDebounceTimer: ReturnType<typeof setTimeout> | null = null; // Debounce timer for demo reload on language change
	let demoReloadAbortController: AbortController | null = null; // Abort controller to cancel in-flight demo reload on language change
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
	 
	 // Note: syncing is now derived from phasedSyncState.initialSyncCompleted
	 // The phasedSyncState.markSyncCompleted() call happens in handlePhasedSyncCompleteEvent
	 syncComplete = true;
	 
	 // Hide the message after 1 second
	 setTimeout(() => {
	 	syncComplete = false;
	 }, 1000);
	 
	 // Sync complete — no auto-expansion needed. User stays at current tier.
		 // They can click "Show more" to see remaining chats.
		 console.debug('[Chats] Sync complete, loadTier remains:', loadTier);
	};

	/**
	 * Handles 'chatUpdated' events from chatSyncService.
	 * Refreshes the chat list from DB and re-dispatches selection if the updated chat was selected.
	 */
	const handleChatUpdatedEvent = async (event: CustomEvent<{ chat_id: string; newMessage?: Message; type?: string; chat?: ChatType }>) => {
		const detail = event.detail as any;
		console.debug(`[Chats] Chat updated event received for chat_id: ${detail.chat_id}, type: ${detail.type}`);
		
		// Invalidate decrypted metadata cache only when metadata may have changed.
		// Invalidating on every message update causes visible flicker (e.g., reverting briefly to "Sending...").
		const shouldInvalidateMetadata =
			detail.type === 'title_updated' ||
			detail.type === 'draft' ||
			detail.type === 'draft_deleted' ||
			detail.type === 'post_processing_metadata' ||
			detail.messagesUpdated === true;
		if (shouldInvalidateMetadata) {
			chatMetadataCache.invalidateChat(detail.chat_id);
		}
		
		// Invalidate last message cache if a new message was added
		if (detail.newMessage || detail.type === 'message_added') {
			chatListCache.invalidateLastMessage(detail.chat_id);
		}
		
	// If a draft was deleted and we have the updated chat object, patch directly
	if (detail.type === 'draft_deleted' && detail.chat) {
		const updatedChat = detail.chat;
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
	} else if (detail.chat) {
		// If we have the updated chat payload, patch cache and list without full reload
		chatListCache.upsertChat(detail.chat);
		const cached = chatListCache.getCache(false);
		if (cached) {
			allChatsFromDB = cached;
		}
	} else {
		// Fallback: mark cache dirty and refresh from DB
		chatListCache.markDirty();
		await updateChatListFromDB();
	}
	
	// NOTE: We intentionally do NOT dispatch 'chatSelected' here for the currently selected chat.
	// ActiveChat.svelte already listens directly to 'chatUpdated' events from chatSyncService
	// and handles updates to the current chat internally. Dispatching 'chatSelected' here would
	// cause page.svelte to call loadChat(), which reloads messages from IndexedDB and wipes out
	// any streaming state. This is especially problematic during AI message streaming where
	// chunks are being rendered in real-time - a loadChat() call would reset the display.
	// 
	// The chatSelected event should ONLY be dispatched when:
	// 1. User clicks on a chat (user-initiated selection in handleChatClick)
	// 2. A new chat is created and needs to be selected (handled separately)
	// NOT when the current chat is simply updated with new messages/metadata.
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
		* NEW BEHAVIOR: Instead of auto-selecting the Phase 1 chat, we store it in the
		* resume state. The UI shows "Resume last chat?" above new chat suggestions,
		* and the user can click to resume or start fresh.
		*/
	const handlePhase1LastChatReadyEvent = async (event: CustomEvent<{chat_id: string}>) => {
		console.info(`[Chats] Phase 1 complete - Last chat ready: ${event.detail.chat_id}.`);
		const targetChatId = event.detail.chat_id;
		
		// CRITICAL: Check if we should show the resume UI for this chat
		// Don't show if user is already in a different chat (e.g., a new chat they just created)
		if (!phasedSyncState.shouldAutoSelectPhase1Chat(targetChatId)) {
			console.info(`[Chats] Skipping Phase 1 resume UI - user is in a different chat`);
			// Still update the list to show the synced chat in the sidebar
			await updateChatListFromDB();
			return;
		}
		
		// NEW: Instead of auto-selecting, store the chat in resume state for the "Resume last chat?" UI
		// Get the chat from IndexedDB (Phase 1 handler already saved it)
		try {
			const chat = await chatDB.getChat(targetChatId);
			if (chat) {
				// Decrypt title, category, and icon for the resume card display
				let decryptedTitle: string | null = null;
				let decryptedCategory: string | null = null;
				let decryptedIcon: string | null = null;

				try {
					const { decryptWithChatKey, decryptChatKeyWithMasterKey } = await import('../../services/cryptoService');
					// First decrypt the chat key if we have it encrypted
					let chatKey = chatDB.getChatKey(targetChatId);
					if (!chatKey && chat.encrypted_chat_key) {
						chatKey = await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
						if (chatKey) {
							chatDB.setChatKey(targetChatId, chatKey);
						}
					}
					if (chatKey) {
						// Decrypt title
						if (chat.encrypted_title) {
							try {
								decryptedTitle = await decryptWithChatKey(chat.encrypted_title, chatKey);
							} catch { /* Title decryption failed – fall through to default */ }
						}
						// Decrypt category
						if (chat.encrypted_category) {
							try {
								decryptedCategory = await decryptWithChatKey(chat.encrypted_category, chatKey);
							} catch { /* Category decryption failed – will use fallback */ }
						}
						// Decrypt icon
						if (chat.encrypted_icon) {
							try {
								decryptedIcon = await decryptWithChatKey(chat.encrypted_icon, chatKey);
							} catch { /* Icon decryption failed – will use fallback */ }
						}
					}
				} catch (decryptError) {
					console.warn('[Chats] Failed to decrypt Phase 1 chat fields:', decryptError);
				}
				
				// Skip draft chats (no title and no messages) — only show resume card for real chats
				const hasTitle = !!(chat.title || decryptedTitle);
				if (!hasTitle) {
					const lastMessage = await chatDB.getLastMessageForChat(chat.chat_id);
					if (!lastMessage) {
						console.info(`[Chats] Skipping Phase 1 draft chat (no title, no messages): ${targetChatId}`);
						// Still update the chat list, but don't show resume card
						chatListCache.markDirty();
						await updateChatListFromDB(true);
						return;
					}
				}
				
				// Use cleartext fields for demo chats, decrypted values otherwise
				const displayTitle = chat.title || decryptedTitle || 'Untitled Chat';
				const displayCategory = chat.category || decryptedCategory || null;
				const displayIcon = chat.icon || decryptedIcon || null;
				
				// Store in resume state for the UI (ActiveChat subscribes to this store)
				phasedSyncState.setResumeChatData(chat, displayTitle, displayCategory, displayIcon);
				console.info(`[Chats] Phase 1 chat stored in resume state: "${displayTitle}" (${targetChatId}), category: ${displayCategory}, icon: ${displayIcon}`);
			} else {
				console.warn(`[Chats] Phase 1 chat ${targetChatId} not found in IndexedDB after sync`);
			}
		} catch (error) {
			console.error('[Chats] Error loading Phase 1 chat for resume state:', error);
		}
		
		// Update the chat list to show the synced chat in the sidebar
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
		
		// Phase 2 ensures at least 20 chats are available — tier 'initial' already shows 20
		// No state change needed here; loadTier 'initial' already shows first 20
	};

	/**
		* Handles 'phase_3_last_100_chats_ready' events from Phase 3 of the new phased sync system.
		* This means the last 100 chats are ready and full sync is complete.
		*/
	const handlePhase3Last100ChatsReadyEvent = async (event: CustomEvent<{chat_count: number; total_chat_count?: number}>) => {
		console.info(`[Chats] Phase 3 complete - Last 100 chats ready: ${event.detail.chat_count} chats, total on server: ${event.detail.total_chat_count || 'unknown'}.`);
		
		// Update the chat list to show all chats
		chatListCache.markDirty();
		await updateChatListFromDB(true);
		
		// Phase 3 complete — stay on current tier (user clicks "Show more" to expand).
		// Only track server-side pagination metadata.
		if (event.detail.total_chat_count) {
			totalServerChatCount = event.detail.total_chat_count;
			hasMoreOnServer = event.detail.total_chat_count > 100;
			serverPaginationOffset = 100; // Next fetch starts after the initial 100
			console.info(`[Chats] Phase 3: total_chat_count=${totalServerChatCount}, hasMoreOnServer=${hasMoreOnServer}`);
		}
		
		console.info(`[Chats] Phase 3 complete - loadTier=${loadTier}, allChatsFromDB has ${allChatsFromDB.length} chats`);
		
		// Show "Sync complete" message (syncing is derived from phasedSyncState)
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
		
		// CRITICAL: Update chat list FIRST, before marking sync complete
		// This ensures the syncing indicator stays visible until chats are actually displayed
		chatListCache.markDirty();
		await updateChatListFromDB(true);
		
		// Sync complete — stay on current tier. User clicks "Show more" to expand.
		console.info(`[Chats] Phased sync complete - loadTier=${loadTier}, allChatsFromDB has ${allChatsFromDB.length} chats`);
		
		// NOW mark sync as completed (this hides the syncing indicator)
		// This prevents redundant syncs when Chats component is remounted
		phasedSyncState.markSyncCompleted();
		
		// Show "Sync complete" message briefly
		syncComplete = true;
		
		// Hide the message after 1 second
		setTimeout(() => {
			syncComplete = false;
		}, 1000);
	};

	/**
	 * Handles "Show more" button click — 3-tier progressive loading:
	 * Tier 1 → 2: Expands from 20 to all ~100 local chats from IndexedDB
	 * Tier 2 → 3: Requests additional older chats from the server (20 at a time, in-memory only)
	 */
	const handleShowMoreClick = async () => {
		if (loadTier === 'initial') {
			// Tier 1 → Tier 2: Show all local chats
			loadTier = 'all_local';
			console.debug('[Chats] User clicked "Show more" — expanding to show all local chats.');
			return;
		}

		// Tier 2 → Tier 3: Fetch older chats from server
		if (hasMoreOnServer && !loadingMoreChats) {
			loadingMoreChats = true;
			loadTier = 'loading_server';
			console.debug(`[Chats] User clicked "Show more" — requesting older chats from server (offset=${serverPaginationOffset}).`);
			try {
				await chatSyncService.sendLoadMoreChats(serverPaginationOffset, 20);
			} catch (error) {
				console.error('[Chats] Error requesting more chats:', error);
				loadingMoreChats = false;
			}
		}
	};

	/**
	 * Handles 'load_more_chats_ready' events from chatSyncService.
	 * These are older chats fetched from the server on demand — stored in memory only (NOT IndexedDB).
	 */
	const handleLoadMoreChatsReadyEvent = (event: CustomEvent<{
		chats: ChatType[];
		has_more: boolean;
		total_count: number;
		offset: number;
	}>) => {
		const { chats, has_more, total_count, offset } = event.detail;
		console.info(`[Chats] Received ${chats.length} older chats from server (offset=${offset}, has_more=${has_more}, total=${total_count}).`);

		if (chats.length > 0) {
			// Deduplicate against existing chats before appending
			const existingIds = new Set(allChats.map(c => c.chat_id));
			const newChats = chats.filter(c => !existingIds.has(c.chat_id));
			
			if (newChats.length > 0) {
				olderChatsFromServer = [...olderChatsFromServer, ...newChats];
				console.debug(`[Chats] Added ${newChats.length} new older chats (${chats.length - newChats.length} duplicates filtered).`);
			}
		}

		// Update pagination state
		hasMoreOnServer = has_more;
		totalServerChatCount = total_count;
		serverPaginationOffset = offset + chats.length;
		loadingMoreChats = false;
		loadTier = 'all_local'; // Reset from 'loading_server' back to 'all_local'
	};

	/**
		* Handles 'cachePrimed' event. Indicates server-side cache is generally ready.
		* This means the 3-phase sync is complete.
		*/
	const handleCachePrimedEvent = async () => {
		console.debug("[Chats] Cache primed event received.");
		
		// Update chat list first to ensure UI is current before hiding syncing indicator
		chatListCache.markDirty();
		await updateChatListFromDB(true);
		
		// NOW mark sync as complete (this hides the syncing indicator)
		phasedSyncState.markSyncCompleted();
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
	const handleSyncStatusResponse = async (event: CustomEvent<{cache_primed: boolean, chat_count: number, timestamp: number}>) => {
		console.debug("[Chats] Sync status response received:", event.detail);
		if (event.detail.cache_primed) {
			// Update chat list first to ensure UI is current before hiding syncing indicator
			chatListCache.markDirty();
			await updateChatListFromDB(true);
			
			// NOW mark sync as complete (this hides the syncing indicator)
			phasedSyncState.markSyncCompleted();
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
		const customEvent = event as CustomEvent<{ chat_id?: string; draftDeleted?: boolean; sharedChatAdded?: boolean }>;
		console.debug('[Chats] Local chat list changed event received:', customEvent.detail);
		
		// Invalidate caches for the specific chat if provided, to ensure fresh preview data
		// CRITICAL: Invalidate BOTH metadata cache AND last message cache
		// The last message cache may contain stale status (e.g., 'processing' instead of 'synced')
		// which causes isWaitingForTitle to remain true and show "Sending..." incorrectly
		if (customEvent.detail?.chat_id) {
			chatMetadataCache.invalidateChat(customEvent.detail.chat_id);
			chatListCache.invalidateLastMessage(customEvent.detail.chat_id);
		}
		
		// CRITICAL: For non-authenticated users, trigger reactivity by updating sessionStorageDraftUpdateTrigger
		// This ensures sessionStorage-only chats appear in the list and demo chat drafts update
		// For authenticated users, update from database as usual
		if (!$authStore.isAuthenticated) {
			// CRITICAL: If a shared chat was added, we need to reload from IndexedDB
			// Shared chats are stored in IndexedDB (not sessionStorage), so incrementing
			// sessionStorageDraftUpdateTrigger alone is not sufficient
			if (customEvent.detail?.sharedChatAdded) {
				const sharedChatId = customEvent.detail.chat_id;
				console.debug('[Chats] Shared chat added - reloading chat list from IndexedDB:', sharedChatId);
				
				// Queue the shared chat for selection after the list updates
				// This ensures the chat is highlighted in the sidebar
				if (sharedChatId) {
					_chatIdToSelectAfterUpdate = sharedChatId;
				}
				
				chatListCache.markDirty();
				await updateChatListFromDB(true);
				return;
			}
			
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
		// NOTE: Server status (isSelfHosted) is now managed by serverStatusStore
		// and initialized once at app load in +layout.svelte to prevent UI flashing
		
		// CRITICAL: Check auth state FIRST before loading chats
		// If user is not authenticated, clear any stale chat data immediately
		if (!$authStore.isAuthenticated) {
			console.debug('[Chats] User not authenticated on mount - clearing user chats');
			allChatsFromDB = []; // Clear user chats immediately
			selectedChatId = null;
			_chatIdToSelectAfterUpdate = null;
			currentServerSortOrder = [];
			// Note: syncing is now derived from authStore and phasedSyncState
			// For non-authenticated users, syncing will be false automatically
			syncComplete = false;

			// CRITICAL: Don't clear URL hash if one exists - deep links need to be processed first
			// Only clear the store state for non-chat hashes, let +page.svelte handle the hash
			const hasHash = typeof window !== 'undefined' && window.location.hash &&
				(window.location.hash.startsWith('#chat-id=') || window.location.hash.startsWith('#chat-id=') ||
				 window.location.hash.startsWith('#settings') || window.location.hash.startsWith('#embed') ||
				 window.location.hash.startsWith('#signup'));
			
			// Check if this is specifically a chat hash - if so, DON'T clear the store
			// The activeChatStore was already set by +page.svelte before Chats.svelte mounted
			// Clearing it here would break shared chat selection (timing issue)
			const hasChatHash = typeof window !== 'undefined' && window.location.hash &&
				window.location.hash.startsWith('#chat-id=');

			if (hasChatHash) {
				// CRITICAL: Don't clear the store for chat hashes - the active chat was already set
				// by +page.svelte's deep link processing. Clearing it here causes a timing issue
				// where the chat shows up in the list but isn't selected.
				console.debug('[Chats] Preserving activeChatStore for chat deep link:', window.location.hash);
			} else if (hasHash) {
				console.debug('[Chats] Preserving URL hash for deep link processing:', window.location.hash);
				// Only clear the store state without touching the URL hash
				activeChatStore.setWithoutHashUpdate(null);
			} else {
				// No hash present, safe to clear everything including URL
				activeChatStore.clearActiveChat();
			}
		}
		
		// Initialize selectedChatId from the persistent store on mount
		// This ensures the active chat remains highlighted when the panel is reopened
		const currentActiveChat = $activeChatStore;
		if (currentActiveChat) {
			selectedChatId = currentActiveChat;
			console.debug('[Chats] Restored active chat from store:', currentActiveChat);
		}

		// NOTE: Reactive sync of selectedChatId with activeChatStore is handled by
		// the $effect at the top level of the script (Svelte 5 requires $effect at top level)
		
		// CHANGED: For non-authenticated users, syncing is automatically false (derived state)
		// Demo chats are loaded synchronously, no sync needed
		if (!$authStore.isAuthenticated) {
			console.debug('[Chats] Non-authenticated user - syncing indicator disabled (derived state)');

			// CRITICAL: For non-auth users, ensure the welcome demo chat is selected if no chat is active yet
			// This handles the case where the sidebar mounts before +page.svelte sets the active chat
			// FIXED: Dispatch chatSelected to ensure the chat actually loads (important for SEO and user experience)
			// CRITICAL: URL hash chat has priority - skip welcome chat if active chat is already set by deep link handler
			// Use activeChatStore instead of checking hash directly to avoid race conditions
			const hasActiveChatSet = currentActiveChat !== null;

			// DISABLED: Auto-selection now handled by unified deep link system in +page.svelte
			// This prevents conflicts with deep link processing and ensures consistent behavior
			console.debug('[Chats] Skipping auto-selection - chat loading handled by unified deep link system');
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

		// Language change handler for demo chats - reload demos in new language
		// DEBOUNCED: The 'language-changed' event fires multiple times in quick succession
		// (once from updateNavigationAndBreadcrumbs, once from setTimeout in SettingsLanguage).
		// Without debouncing, two concurrent loadDemoChatsFromServer(true) calls race against
		// each other - the second call's communityDemoStore.clear() can wipe data that the
		// first call just added, causing demo chat titles to briefly disappear or stay stale.
		handleLanguageChangeForDemos = () => {
			// Clear any pending debounce timer (collapses multiple rapid events into one)
			if (languageChangeDemoDebounceTimer) {
				clearTimeout(languageChangeDemoDebounceTimer);
			}
			languageChangeDemoDebounceTimer = setTimeout(() => {
				languageChangeDemoDebounceTimer = null;
				console.debug('[Chats] Language changed (debounced) - reloading community demo chats');
				loadDemoChatsFromServer(true).catch(error => {
					console.error('[Chats] Error reloading demo chats after language change:', error);
				});
			}, 100); // 100ms debounce - long enough to collapse double-dispatch, short enough to feel instant
		};
		window.addEventListener('language-changed', handleLanguageChangeForDemos);

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
			// Note: syncing is derived from authStore - will be false when not authenticated
			syncComplete = false;
			
			// Clear the persistent store
			activeChatStore.clearActiveChat();
			
			// Reset display state to show all demo chats
			loadTier = 'all_local';
			olderChatsFromServer = [];
			hasMoreOnServer = false;
			serverPaginationOffset = 100;
			loadingMoreChats = false;
			totalServerChatCount = 0;
			
			// Force a reactive update to ensure UI reflects the cleared state
			// This is especially important if chats were already loaded before logout
			console.debug('[Chats] User chats cleared immediately, demo chats will be shown');

			// CRITICAL: After clearing user chats, select the welcome demo chat
			// This ensures the welcome chat is highlighted in the sidebar after logout
			// Use tick() to ensure reactive updates have processed (visiblePublicChats should be updated)
			// CRITICAL: URL hash chat has priority - skip welcome chat if active chat already set
			await tick();

			// Check if active chat is already set by deep link handler (more reliable than checking hash)
			const currentActiveChatAfterTick = $activeChatStore;

			// DISABLED: Chat selection after logout now handled by unified deep link system
			// This prevents conflicts and ensures consistent behavior across all entry points
			console.debug('[Chats] Skipping post-logout chat selection - handled by unified deep link system');
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
				// CRITICAL: URL hash chat has priority - skip welcome chat if active chat already set
				await tick();
				const currentActiveChatAfterAuthChange = $activeChatStore;

				// DISABLED: Chat selection after auth change now handled by unified deep link system
				// This prevents conflicts and ensures consistent behavior
				console.debug('[Chats] Skipping post-auth-change chat selection - handled by unified deep link system');
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
		chatSyncService.addEventListener('load_more_chats_ready', handleLoadMoreChatsReadyEvent as EventListener);

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

		// Listen for show inline unlock form for hiding a chat
		handleShowOverscrollUnlockForHide = (event: Event) => {
			const customEvent = event as CustomEvent<{ chatId: string }>;
			chatIdToHideAfterInlineUnlock = customEvent.detail.chatId;
			showInlineUnlock = true;
			// Scroll to top to show the inline unlock form
			if (activityHistoryElement) {
				activityHistoryElement.scrollTop = 0;
			}
			// Focus input after a brief delay
			setTimeout(() => {
				inlineUnlockInput?.focus();
			}, 100);
		};
		window.addEventListener('showOverscrollUnlockForHide', handleShowOverscrollUnlockForHide);

		// Listen for hidden chats auto-locked event
		handleHiddenChatsAutoLocked = () => {
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
			
			// Reset state after unhiding (no longer needed for overscroll, but kept for cleanup)
			
			// CRITICAL: Reset scroll position to top to allow user to scroll up to see hidden chats section
			// The hidden chats section is at the top of the scrollable area, so we need to ensure
			// the scroll position is reset after the chat list updates
			// Use setTimeout with multiple requestAnimationFrame calls to ensure DOM is fully updated
			// This is necessary because the chat list update might change the scroll container's content height
			setTimeout(() => {
				requestAnimationFrame(() => {
					requestAnimationFrame(() => {
						if (activityHistoryElement) {
							// Force scroll to top using multiple methods for maximum compatibility
							activityHistoryElement.scrollTop = 0;
							// Also try scrollTo for better compatibility
							activityHistoryElement.scrollTo({ top: 0, behavior: 'auto' });
							// Force a reflow to ensure scroll position is applied
							void activityHistoryElement.offsetHeight;
							
							// Double-check that scroll position is actually at 0
							// If not, try again after a brief delay
							if (activityHistoryElement.scrollTop !== 0) {
								setTimeout(() => {
									if (activityHistoryElement) {
										activityHistoryElement.scrollTop = 0;
									}
								}, 50);
							}
						}
					});
				});
			}, 150); // Delay to ensure chat list update and DOM reflow completes
		};
		window.addEventListener('chatUnhidden', handleChatUnhidden);
		
		// Initial load of incognito chats (only if mode is enabled)
		// Don't use subscription to avoid reactive loops - just check on mount
		await loadIncognitoChats();

		// Load demo chats from server in background (for all users)
		// Similar to how shared chats are loaded - stores in IndexedDB and displays in chat list
		loadDemoChatsFromServer().catch(error => {
			console.error('[Chats] Error loading demo chats from server:', error);
		});

		// Perform initial database load - loads and displays chats from IndexedDB immediately
		await initializeAndLoadDataFromDB();
		
		// CRITICAL FIX: Phased sync is now started in +page.svelte to ensure it works on mobile
		// where the sidebar (Chats component) is closed by default and this component never mounts.
		// This component only handles UI updates (loading indicators, list updates) from sync events.
		// Note: syncing is now derived from phasedSyncState.initialSyncCompleted - no manual check needed
		// If sync was already completed before this component mounted, ensure we have the latest data
		// This handles the case where the sidebar was closed during sync (common on mobile)
		// We intentionally stay on Tier 1 (20 chats) — user clicks "Show more" to see the rest
		if ($phasedSyncState.initialSyncCompleted) {
			await updateChatListFromDB();
			console.debug('[Chats] Sync was already complete on mount, loaded data but staying at loadTier:', loadTier);
		}
	});
	
	/**
	 * Load community demo chats from server with language-aware caching
	 * 
	 * ARCHITECTURE: Language-specific loading with IndexedDB caching
	 * 1. Loads demos in the user's current device language ONLY
	 * 2. Uses IndexedDB for offline support (cached demos available offline)
	 * 3. Reloads when language changes (via 'language-changed' event)
	 * 4. Hash-based change detection - only fetches updated demos
	 * 5. Clears cache on language change to fetch new language content
	 * 
	 * Rationale for single-language storage:
	 * - Most users rarely switch languages
	 * - Saves storage (5 demos × 20 languages = 100 demo chat records vs 5)
	 * - Simplifies cache management
	 * - Language change triggers automatic reload with new translations
	 * 
	 * Available for ALL users (authenticated and non-authenticated).
	 * 
	 * @param forceLanguageReload - If true, clears cache and reloads all demos (used on language change)
	 */
	async function loadDemoChatsFromServer(forceLanguageReload: boolean = false): Promise<void> {
		// Check if already loading (unless forcing reload for language change)
		if (!forceLanguageReload && communityDemoStore.isLoading()) {
			console.debug('[Chats] Community demos already loading, skipping');
			return;
		}

		// ABORT MECHANISM: Cancel any previous in-flight reload when a forced reload starts.
		// This prevents race conditions where an old reload's results overwrite new data.
		if (forceLanguageReload && demoReloadAbortController) {
			console.debug('[Chats] Aborting previous demo reload in favor of new language reload');
			demoReloadAbortController.abort();
		}
		const abortController = new AbortController();
		if (forceLanguageReload) {
			demoReloadAbortController = abortController;
		}

		try {
			// CRITICAL: Wait for translations to be fully loaded before fetching
			// This ensures svelteLocaleStore has the correct language for the API call
			await waitLocale();
			
			// Check if this reload was superseded by a newer one
			if (abortController.signal.aborted) {
				console.debug('[Chats] Demo reload aborted (superseded by newer reload)');
				return;
			}
			
			communityDemoStore.setLoading(true);
			
			// Get user's current language from svelte-i18n store
			const currentLang = get(svelteLocaleStore) || 'en';
			console.debug(`[Chats] Loading community demos for language: ${currentLang}`);
			
			// STEP 1: If language changed, clear cache and memory
			if (forceLanguageReload) {
				console.debug('[Chats] Language changed - clearing cache and reloading demos');
				try {
					const { demoChatsDB } = await import('../../services/demoChatsDB');
					await demoChatsDB.clearAllDemoChats();
					communityDemoStore.clear();
				} catch (error) {
					console.error('[Chats] Error clearing demo chats cache:', error);
				}
			}
			
			// STEP 2: Load from IndexedDB cache first (provides offline support)
			if (!forceLanguageReload && !communityDemoStore.isCacheLoaded()) {
				console.debug('[Chats] Loading community demos from IndexedDB cache...');
				await communityDemoStore.loadFromCache();
			}

			// Check abort again before making network requests
			if (abortController.signal.aborted) {
				console.debug('[Chats] Demo reload aborted before fetch (superseded by newer reload)');
				return;
			}

			// STEP 3: Get local content hashes for change detection
			const localHashes = await getLocalContentHashes();
			const hashesParam = Array.from(localHashes.entries())
				.map(([demoId, hash]) => `${demoId}:${hash}`)
				.join(',');
			
			if (forceLanguageReload) {
				console.debug(`[Chats] Reloading all demos in ${currentLang}`);
			} else {
				console.debug(`[Chats] Checking for demo chat updates with ${localHashes.size} local hashes...`);
			}
			
			// STEP 4: Fetch demo list with language and hashes for change detection
			const url = hashesParam 
				? getApiEndpoint(`/v1/demo/chats?lang=${currentLang}&hashes=${encodeURIComponent(hashesParam)}`)
				: getApiEndpoint(`/v1/demo/chats?lang=${currentLang}`);
			
			const response = await fetch(url, { signal: abortController.signal });
			if (!response.ok) {
				// If server is unavailable, use cached demos (offline mode)
				if (getAllCommunityDemoChats().length > 0) {
					console.debug(`[Chats] Server unavailable, using ${getAllCommunityDemoChats().length} cached community demos`);
					communityDemoStore.markAsLoaded();
					return;
				}
				console.warn('[Chats] Failed to fetch demo chats list:', response.status);
				communityDemoStore.markAsLoaded();
				return;
			}

			const data = await response.json();
			const demoChatsList = data.demo_chats || [];
			
			if (demoChatsList.length === 0) {
				console.debug('[Chats] No community demo chats available from server');
				communityDemoStore.markAsLoaded();
				return;
			}

			// Determine which demos need to be fetched
			// - If hashes were provided, only fetch demos with `updated: true`
			// - If no hashes (first load), fetch all demos
			const demosToFetch = localHashes.size > 0
				? demoChatsList.filter((d: { updated?: boolean }) => d.updated === true)
				: demoChatsList;
			
			console.debug(`[Chats] Found ${demoChatsList.length} community demos, ${demosToFetch.length} need updates`);

			// Track loaded demo IDs
			const newlyLoadedIds: string[] = [];

			// Load each demo chat that needs updating
			for (const demoChatMeta of demosToFetch) {
				// Check abort before each demo fetch to bail out quickly if superseded
				if (abortController.signal.aborted) {
					console.debug('[Chats] Demo reload aborted during fetch loop');
					return;
				}

				const demoId = demoChatMeta.demo_id;
				const contentHash = demoChatMeta.content_hash || '';
				if (!demoId) continue;

				try {
					// Fetch individual demo chat data
					const chatResponse = await fetch(getApiEndpoint(`/v1/demo/chat/${demoId}?lang=${currentLang}`), { signal: abortController.signal });
					if (!chatResponse.ok) {
						console.warn(`[Chats] Failed to fetch community demo chat ${demoId}:`, chatResponse.status);
						continue;
					}

					const chatData = await chatResponse.json();
					const chatDataObj = chatData.chat_data;
					const serverContentHash = chatData.content_hash || contentHash || ''; // Get content_hash from response
					
					// ARCHITECTURE: Community demo chats are server-side decrypted
					// The API returns cleartext messages with encryption_mode: "none"
					// No encryption_key is needed - just chat_id and messages
					if (!chatDataObj || !chatDataObj.chat_id) {
						console.warn(`[Chats] Invalid community demo chat data for ${demoId}`);
						continue;
					}

					const chatId = chatDataObj.chat_id;  // This is the demo_id (e.g., "demo-1")
					
					console.debug(`[Chats] Community demo ${demoId} loaded: chatId=${chatId}, hash=${serverContentHash.slice(0, 16)}...`);

					// Extract metadata from API response (already translated server-side)
					const title = chatData.title || 'Demo Chat';
					const summary = chatData.summary || '';
					const category = chatData.category || '';
					const icon = chatData.icon || '';
					const followUpSuggestions = chatData.follow_up_suggestions || [];
					const demoChatCategory = chatData.demo_chat_category || demoChatMeta.demo_chat_category || 'for_everyone';

					// ARCHITECTURE: Community demo messages are already decrypted server-side
					// The API returns cleartext content directly (not encrypted)
					// Store using CLEARTEXT field names (content, category, model_name) - NOT encrypted_* fields
					const rawMessages = chatDataObj.messages || [];
					const parsedMessages = rawMessages.map((msg: { role: string; content: string; category?: string; model_name?: string; created_at?: number }) => {
						// Convert cleartext API format to Message format
						// Server returns: { role, content (cleartext), category (cleartext), model_name (cleartext), created_at }
						return {
							message_id: `${demoId}-${rawMessages.indexOf(msg)}`,
							chat_id: chatId,
							role: msg.role || 'user',
							content: msg.content || '',  // Cleartext content
							category: msg.role === 'assistant' ? (msg.category || category) : undefined,  // Cleartext category
							model_name: msg.role === 'assistant' ? msg.model_name : undefined,  // Cleartext model name for assistant messages
							created_at: msg.created_at || Math.floor(Date.now() / 1000),
							status: 'synced' as const
						} as Message;
					});
					
					console.debug(`[Chats] Community demo ${demoId} has ${parsedMessages.length} messages`);

					// ARCHITECTURE: Use consistent timestamps for all demo chats (intro + community)
					// This ensures they stay grouped correctly and have a stable order.
					// Intro chats use '7 days ago' minus their order.
					// Community demos use '7 days ago' minus 10000 minus their index.
					const sevenDaysAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
					const demoIndex = parseInt(demoId.split('-')[1] || '0');
					const displayTimestamp = sevenDaysAgo - (demoIndex * 1000) - 10000;

					// Create Chat object with cleartext metadata
					// ARCHITECTURE: Demo chats use CLEARTEXT field names (category, icon, follow_up_request_suggestions)
					// NOT encrypted_* field names - the data is already decrypted server-side
					const chat: ChatType = {
						chat_id: chatId,
						title: title,  // Cleartext title
						encrypted_title: null,  // Not encrypted - title is in `title` field
						// CLEARTEXT fields - demo chats are already decrypted server-side
						chat_summary: summary || null,
						follow_up_request_suggestions: followUpSuggestions.length > 0 ? JSON.stringify(followUpSuggestions) : null,
						icon: icon || null,
						category: category || null,
						demo_chat_category: demoChatCategory || null,  // Target audience: for_everyone or for_developers
						messages_v: parsedMessages.length,
						title_v: 0,
						draft_v: 0,
						last_edited_overall_timestamp: displayTimestamp,
						unread_count: 0,
						created_at: displayTimestamp,
						updated_at: displayTimestamp,
						processing_metadata: false,
						waiting_for_metadata: false,
						group_key: 'examples'
					};

					// Parse embeds from API response (cleartext, server-side decrypted)
					// ARCHITECTURE: Demo embeds are stored in demo_chats_db for offline support
					const rawEmbeds = chatDataObj.embeds || [];
					const parsedEmbeds = rawEmbeds.map((emb: { embed_id?: string; type: string; content: string; created_at?: number }) => ({
						embed_id: emb.embed_id || `${demoId}-embed-${rawEmbeds.indexOf(emb)}`,
						chat_id: chatId,
						type: emb.type || 'unknown',
						content: emb.content || '',  // Cleartext content (JSON string)
						created_at: emb.created_at || Math.floor(Date.now() / 1000)
					}));

					// Store chat, messages, and embeds in memory AND IndexedDB (with content_hash for change detection)
					await addCommunityDemo(chatId, chat, parsedMessages, serverContentHash, parsedEmbeds);

					if (parsedEmbeds.length > 0) {
						console.debug(`[Chats] Stored ${parsedEmbeds.length} cleartext embeds for community demo ${demoId}`);
					}

					newlyLoadedIds.push(demoId);
					console.debug(`[Chats] Successfully loaded community demo ${demoId} (chat_id: ${chatId}) into memory and cache`);
				} catch (error) {
					// Re-throw abort errors to be caught by the outer catch
					if (error instanceof DOMException && error.name === 'AbortError') {
						throw error;
					}
					console.error(`[Chats] Error loading community demo ${demoId}:`, error);
				}
			}

			communityDemoStore.markAsLoaded();
			console.debug(`[Chats] Finished loading community demos: ${newlyLoadedIds.length} updated, ${getAllCommunityDemoChats().length} total`);
		} catch (error) {
			// Don't log abort errors (expected when a reload is superseded by a newer one)
			if (error instanceof DOMException && error.name === 'AbortError') {
				console.debug('[Chats] Demo reload aborted (superseded by newer reload)');
				return; // Don't markAsLoaded - the newer reload will handle it
			}
			console.error('[Chats] Error loading community demo chats from server:', error);
			communityDemoStore.markAsLoaded();
		}
	}
	
	/**
		* Initializes the local chatDB and loads the initial list of chats.
		* Called on component mount. Loads and displays chats immediately.
		* NON-BLOCKING: Does not wait for DB init if it's still in progress.
		* Handles database deletion gracefully (e.g., during logout).
		* CRITICAL: Only loads chats if user is authenticated.
		*/
	async function initializeAndLoadDataFromDB() {
		// CRITICAL: For non-authenticated users, NEVER use cached data from previous sessions
		// The chatListCache may contain stale chats from a previous authenticated session
		// if the component was destroyed (sidebar closed) when logout/session-expiry happened.
		// Always clear and skip the cache for unauthenticated users to prevent data leakage.
		if (!$authStore.isAuthenticated) {
			console.debug("[Chats] User not authenticated - clearing cache and loading shared chats only");
			chatListCache.clear(); // Defensive: ensure no stale data from previous session
			// Call updateChatListFromDB which handles shared chat loading for non-auth users
			await updateChatListFromDB();
			return;
		}

		// CRITICAL: Check global cache first to avoid unnecessary DB reads on remount
		// This cache persists across component instances (when sidebar closes/opens)
		// Only used for authenticated users - unauthenticated users are handled above
		const cached = chatListCache.getCache(false);
		if (cached) {
			console.debug("[Chats] Using cached chats on initialize, skipping DB read");
			allChatsFromDB = cached;
			return;
		}
		
		try {
			console.debug("[Chats] Ensuring local database is initialized...");
			// chatDB.init() is idempotent - safe to call multiple times
			// If already initialized, this returns immediately
			try {
				await chatDB.init();
			} catch (initError) {
				const error = initError as Error;
				// If database is being deleted (e.g., during logout), skip database access
				if (error?.message?.includes('being deleted') || error?.message?.includes('cannot be initialized')) {
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
		window.removeEventListener('language-changed', handleLanguageChangeForDemos);
		window.removeEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, handleLocalChatListChanged);
		window.removeEventListener('userLoggingOut', handleLogoutEvent);
		if (languageChangeDemoDebounceTimer) clearTimeout(languageChangeDemoDebounceTimer);
		if (demoReloadAbortController) demoReloadAbortController.abort();
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
		chatSyncService.removeEventListener('load_more_chats_ready', handleLoadMoreChatsReadyEvent as EventListener);

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
		
		// CRITICAL: Mark that user made an explicit choice when they click on a chat
		// This ensures sync phases will NEVER override the user's choice
		if (userInitiated) {
			phasedSyncState.markUserMadeExplicitChoice();
		}

		// Update last selected for potential range selection (even when not in select mode)
		lastSelectedChatId = chat.chat_id;

		// CRITICAL: Always save last_opened to IndexedDB when switching chats (before updating UI stores)
		// This ensures tab reload opens the correct chat even if the component unmounts during the update
		// IndexedDB update happens for all users (authenticated and non-authenticated) for tab reload persistence
		// Server sync (via WebSocket) only happens for authenticated users (handled by sendSetActiveChatImpl)
		// SECURITY: Don't store hidden chats as last_opened - they require password after page reload
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
			// NOTE: Community demo chats are now stored in-memory (communityDemoStore), not IndexedDB
			// They're included via visiblePublicChats derived, so we only need to load shared chats here
			
			try {
				// Check if database is being deleted (e.g., during logout)
				try {
					await chatDB.init();
				} catch (initError: any) {
					if (initError?.message?.includes('being deleted') || initError?.message?.includes('cannot be initialized') || initError?.message?.includes('Database initialization blocked')) {
						console.debug("[Chats] Database unavailable, skipping shared chat load");
						allChatsFromDB = [];
						return;
					}
					throw initError;
				}
				
				// Get shared chat IDs from IndexedDB (sharedChatKeyStorage)
				// Community demos are now in-memory, so we don't load them from here
				const { getStoredSharedChatIds } = await import('../../services/sharedChatKeyStorage');
				const sharedChatIds = await getStoredSharedChatIds();
				
				if (sharedChatIds.length > 0) {
					// Load shared chats from IndexedDB
					// CRITICAL: Mark these as shared by others since they came from share links
					const loadedChats: ChatType[] = [];
					
					for (const chatId of sharedChatIds) {
						try {
							const chat = await chatDB.getChat(chatId);
							if (chat) {
								// Mark as shared by others and assign to the shared_by_others group
								chat.is_shared_by_others = true;
								chat.group_key = 'shared_by_others';
								loadedChats.push(chat);
							}
						} catch (error) {
							console.warn(`[Chats] Error loading shared chat ${chatId}:`, error);
						}
					}
					
					allChatsFromDB = loadedChats;
					chatListCache.setCache(loadedChats);
					console.debug(`[Chats] Loaded ${loadedChats.length} shared chat(s) from IndexedDB (marked as shared_by_others)`);
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
     * Handle scroll event
     * Ensures scroll can reach 0 when hidden chats are unlocked
     */
    function handleScroll(event: Event) {
        if (!activityHistoryElement) return;
        
        // Update scroll position
        const newScrollTop = activityHistoryElement.scrollTop;
        
        // CRITICAL: Ensure scroll can reach 0 when hidden chats are unlocked
        // Sometimes scroll position can get stuck slightly above 0, preventing access to hidden chats section
        // If user is trying to scroll to top and we're very close (within 2px), force it to 0
        if (newScrollTop > 0 && newScrollTop <= 2 && hiddenChatState.isUnlocked) {
            // User is trying to scroll to top - ensure we can reach exactly 0
            requestAnimationFrame(() => {
                if (activityHistoryElement && activityHistoryElement.scrollTop <= 2) {
                    activityHistoryElement.scrollTop = 0;
                }
            });
        }
    }
    
    /**
     * Handle wheel event
     * Ensures scroll can reach 0 when hidden chats are unlocked
     */
    function handleWheel(event: WheelEvent) {
        if (!activityHistoryElement) return;
        
        const scrollTop = activityHistoryElement.scrollTop;
        
        // CRITICAL: Also allow scrolling to top when hidden chats are already unlocked
        // This ensures users can scroll up to see the hidden chats section after unhiding
        // If user is trying to scroll up and we're near the top, ensure we can reach scrollTop = 0
        if (scrollTop <= 10 && event.deltaY < 0 && hiddenChatState.isUnlocked) {
            // Allow normal scrolling to top - don't prevent default
            // Just ensure scroll position can reach 0
            if (scrollTop > 0) {
                // Smoothly scroll to top
                activityHistoryElement.scrollTo({ top: 0, behavior: 'smooth' });
            }
        }
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
        
        const touchY = event.touches[0].clientY;
        const deltaY = touchY - touchStartY;
        
        // CRITICAL: Also allow scrolling to top when hidden chats are already unlocked
        // This ensures users can scroll up to see the hidden chats section after unhiding
        // If user is trying to scroll up and we're near the top, ensure we can reach scrollTop = 0
        if (scrollTop <= 10 && deltaY > 0 && hiddenChatState.isUnlocked) {
            // Allow normal scrolling to top
            // Just ensure scroll position can reach 0
            if (scrollTop > 0) {
                // Smoothly scroll to top
                activityHistoryElement.scrollTo({ top: 0, behavior: 'smooth' });
            }
        }
    }
    

    /**
     * Handle inline unlock form submission
     */
    async function handleInlineUnlock(event: Event) {
        event.preventDefault();
        
        if (inlineUnlockLoading || inlineUnlockCode.length < 4 || inlineUnlockCode.length > 30) return;
        
        inlineUnlockLoading = true;
        inlineUnlockError = '';
        
        try {
            // If we're hiding a chat, encrypt it first, then unlock
            // This ensures unlock succeeds even if no existing chats are encrypted with this code
            let encryptedChatKeyForVerification: string | undefined = undefined;
            
            if (chatIdToHideAfterInlineUnlock) {
                // Import services
                const { hiddenChatService } = await import('../../services/hiddenChatService');
                const { chatDB } = await import('../../services/db');
                
                // Get the chat to hide
                const chatToHide = await chatDB.getChat(chatIdToHideAfterInlineUnlock);
                if (!chatToHide) {
                    inlineUnlockError = $text('chats.hidden_chats.unlock_error.text', {
                        default: 'Error: Chat not found'
                    });
                    inlineUnlockLoading = false;
                    return;
                }
                
                // Get the chat key (decrypt from encrypted_chat_key if needed)
                let chatKey = chatDB.getChatKey(chatIdToHideAfterInlineUnlock);
                if (!chatKey && chatToHide.encrypted_chat_key) {
                    const { decryptChatKeyWithMasterKey } = await import('../../services/cryptoService');
                    try {
                        chatKey = await decryptChatKeyWithMasterKey(chatToHide.encrypted_chat_key);
                    } catch (error) {
                        console.error('[Chats] Error decrypting chat key for hiding:', error);
                        inlineUnlockError = $text('chats.hidden_chats.unlock_error.text', {
                            default: 'Error decrypting chat key'
                        });
                        inlineUnlockLoading = false;
                        return;
                    }
                }
                
                if (!chatKey) {
                    inlineUnlockError = $text('chats.hidden_chats.unlock_error.text', {
                        default: 'Error: Chat key not found'
                    });
                    inlineUnlockLoading = false;
                    return;
                }
                
                // Encrypt chat key with the password (this doesn't unlock, just encrypts)
                const encryptedChatKey = await hiddenChatService.encryptChatKeyWithCode(chatKey, inlineUnlockCode);
                if (!encryptedChatKey) {
                    inlineUnlockError = $text('chats.hidden_chats.unlock_error.text', {
                        default: 'Error encrypting chat'
                    });
                    inlineUnlockLoading = false;
                    return;
                }
                
                // Store for verification during unlock
                encryptedChatKeyForVerification = encryptedChatKey;
                
                // Update chat in database
                const updatedChat = {
                    ...chatToHide,
                    encrypted_chat_key: encryptedChatKey,
                    is_hidden: true
                };
                await chatDB.updateChat(updatedChat);
                
                // Sync to server
                const { chatSyncService } = await import('../../services/chatSyncService');
                await chatSyncService.sendUpdateEncryptedChatKey(chatIdToHideAfterInlineUnlock, encryptedChatKey);
            }
            
            // Attempt to unlock hidden chats (after encrypting chat if needed)
            // If we encrypted a chat, pass the encrypted chat key so unlock can verify it even if getAllChats() hasn't picked it up yet
            const result = await hiddenChatStore.unlock(inlineUnlockCode, encryptedChatKeyForVerification);
            
            if (result.success) {
                // Success - close the inline form and refresh chat list
                // This handles both cases: chats decrypted (decryptedCount > 0) 
                // and no chats decrypted (decryptedCount === 0, but code is valid)
                // When decryptedCount === 0, the hidden chats section will show "No hidden chats"
                showInlineUnlock = false;
                inlineUnlockCode = '';
                inlineUnlockError = '';
                chatIdToHideAfterInlineUnlock = null;
                
                // Refresh chat list to show hidden chats (or "No hidden chats" if decryptedCount === 0)
                chatListCache.markDirty();
                await updateChatListFromDB(true);
            } else {
                // Incorrect password (some chats decrypted but not all, or other error)
                inlineUnlockError = $text('chats.hidden_chats.incorrect_password.text', {
                    default: 'Incorrect password. Please try again.'
                });
                inlineUnlockCode = ''; // Clear password on error
                inlineUnlockInput?.focus();
            }
        } catch (error) {
            console.error('[Chats] Error unlocking hidden chats:', error);
            inlineUnlockError = $text('chats.hidden_chats.unlock_error.text', {
                default: 'An error occurred. Please try again.'
            });
            inlineUnlockCode = '';
        } finally {
            inlineUnlockLoading = false;
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
        // Check if this is a public chat (intro, community demo, or legal)
        if (isPublicChat(chatId)) {
            // Find the chat in visiblePublicChats
            const chat = visiblePublicChats.find(c => c.chat_id === chatId);
            if (chat) {
                // getDemoMessages checks INTRO_CHATS, LEGAL_CHATS, and communityDemoStore
                const messages = getDemoMessages(chatId, INTRO_CHATS, LEGAL_CHATS);
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
        } finally {
            // Signal to Chat.svelte context menu that bulk download is complete
            window.dispatchEvent(new CustomEvent('chatBulkDownloadComplete'));
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
  - Iterates through grouped chats (3-tier loading: initial 20, all local, then server pagination).
  - Renders each chat item using the ChatComponent.
  - Provides a "Show more" button if more chats are available (local or server).
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
			<!-- Sync status indicator - shows during sync regardless of hidden chat state -->
		{#if syncing}
			<div class="show-hidden-chats-container">
				<div class="syncing-inline-indicator" aria-live="polite">
					<span class="clickable-icon icon_reload syncing-icon"></span>
					<span class="syncing-text">{$text('activity.syncing.text')}</span>
				</div>
			</div>
		{:else if !hiddenChatState.isUnlocked}
			<!-- Show hidden chats button/form (only when not syncing and hidden chats are locked) -->
			{#if !showInlineUnlock}
				<div class="show-hidden-chats-container">
					<button
						type="button"
						class="show-hidden-chats-button"
						class:fade-in={syncComplete || !syncing}
						onclick={() => {
							showInlineUnlock = true;
							// Focus input after a brief delay
							setTimeout(() => {
								inlineUnlockInput?.focus();
							}, 100);
						}}
					>
						<span class="clickable-icon icon_hidden"></span>
						<span>{$text('chats.hidden_chats.show_hidden_chats.text', { default: 'Show hidden chats' })}</span>
					</button>
				</div>
			{:else}
				<!-- Inline unlock form -->
				<div class="overscroll-unlock-container">
					<div class="overscroll-unlock-content">
						<p class="overscroll-unlock-label">
							<span class="clickable-icon icon_hidden"></span>
							<span>{$text('chats.hidden_chats.show_hidden_chats.text', { default: 'Show hidden chats' })}</span>
						</p>
						{#if $authStore.isAuthenticated}
							<!-- Authenticated users: show unlock form -->
							<p class="overscroll-unlock-info" style="font-size: 12px; color: var(--color-grey-60); margin-bottom: 8px;">
								{$text('chats.hidden_chats.password_info.text', { default: 'Each unique password can be used to hide/show different chats.' })}
							</p>
							<form onsubmit={handleInlineUnlock}>
								<div class="overscroll-unlock-input-wrapper">
									<input
										bind:this={inlineUnlockInput}
										type="password"
										autocomplete="off"
										class="overscroll-unlock-input"
										class:error={!!inlineUnlockError}
										bind:value={inlineUnlockCode}
										oninput={(e) => {
											const target = e.target as HTMLInputElement;
											let value = target.value;
											if (value.length > 30) {
												value = value.slice(0, 30); // Max 30 characters
											}
											inlineUnlockCode = value;
											inlineUnlockError = ''; // Clear error on input
										}}
										placeholder={$text('chats.hidden_chats.password_placeholder.text', { default: 'Enter password (4-30 characters)' })}
										maxlength="30"
										disabled={inlineUnlockLoading}
									/>
									{#if inlineUnlockError}
										<div class="overscroll-unlock-error">{inlineUnlockError}</div>
									{/if}
								</div>
								<button
									type="submit"
									class="overscroll-unlock-button"
									disabled={inlineUnlockLoading || inlineUnlockCode.length < 4 || inlineUnlockCode.length > 30}
								>
									{#if inlineUnlockLoading}
										<span class="loading-spinner"></span>
									{:else}
										{$text('chats.hidden_chats.unlock_button.text', { default: 'Unlock' })}
									{/if}
								</button>
							</form>
						{:else}
							<!-- Non-authenticated users: show placeholder message -->
							<p class="overscroll-unlock-info">
								<span>{$text('chats.hidden_chats.login_required.text')}</span>
							</p>
						{/if}
						<button
							type="button"
							class="clickable-icon icon_close_up overscroll-unlock-close"
							onclick={() => {
								showInlineUnlock = false;
								inlineUnlockCode = '';
								inlineUnlockError = '';
								chatIdToHideAfterInlineUnlock = null;
							}}
							aria-label={$text('activity.close.text', { default: 'Close' })}
						></button>
					</div>
				</div>
			{/if}
		{/if}
		
		{#if !allChats || allChats.length === 0}
			<div class="no-chats-indicator">{$text('activity.no_chats.text')}</div>
		{:else}
			<!-- Hidden chats section (shown when unlocked) - reusing overscroll-unlock-container styling -->
			{#if hiddenChatState.isUnlocked}
				<div class="overscroll-unlock-container">
					<div class="overscroll-unlock-content">
						<p class="overscroll-unlock-label">
							<span class="clickable-icon icon_hidden"></span>
							<span>{$text('chats.hidden_chats.title.text')}:</span>
						</p>
						{#if hiddenChats.length > 0}
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
						{:else}
							<!-- Show "No hidden chats" message when section is unlocked but empty -->
							<div class="no-hidden-chats-message">
								<p>{$text('chats.hidden_chats.no_hidden_chats.text', { default: 'No hidden chats' })}</p>
							</div>
						{/if}
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
			
			<!-- DEBUG: Rendering {allChats.length} chats (demo + real), loadTier: {loadTier}, grouped chats: {Object.keys(groupedChatsForDisplay).length} groups -->
			
			<!-- Snippet for rendering a chat group (avoids duplicating the complex chat item template) -->
			{#snippet chatGroupSnippet(groupKey: string, groupItems: ChatType[])}
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
			{/snippet}
			
			<div class="chat-groups">
				<!-- 1. User chat groups (time-based: today, yesterday, month groups, etc.) -->
				{#each orderedUserChatGroups as [groupKey, groupItems] (groupKey)}
					{@render chatGroupSnippet(groupKey, groupItems)}
				{/each}
				
				<!-- 2. "Show more" button — placed ABOVE static sections (intro, examples, legal)
				     so users don't have to scroll past non-user content to load more of their chats -->
				{#if showMoreButtonVisible}
					<div class="load-more-container">
						<button
							class="load-more-button"
							disabled={loadingMoreChats}
							onclick={handleShowMoreClick}
						>
							{#if loadingMoreChats}
								...
							{:else}
								{$text('chats.loadMore.button.text')}
							{/if}
						</button>
					</div>
				{/if}
				
				<!-- 3. Static chat groups (shared_by_others, intro, examples, legal) -->
				{#each orderedStaticChatGroups as [groupKey, groupItems] (groupKey)}
					{@render chatGroupSnippet(groupKey, groupItems)}
				{/each}
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
        padding: 0 15px; /* Match horizontal padding */
        font-weight: 500;
        margin-bottom: 6px; /* Reduced margin */
        text-transform: uppercase; /* Optional: Make titles stand out */
        letter-spacing: 0.5px; /* Optional */
		padding-top: 15px;
    }

    /* Show hidden chats button - styled like group-title */
    .show-hidden-chats-container {
        padding: 10px 15px; 
    }

    .show-hidden-chats-button {
        all: unset; /* Reset all default button styles */
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.85em; /* Match group-title font size */
        color: var(--color-grey-60); /* Match group-title color */
        font-weight: 500; /* Match group-title font weight */
        text-transform: uppercase; /* Match group-title text transform */
        letter-spacing: 0.5px; /* Match group-title letter spacing */
        cursor: pointer;
        transition: color 0.2s ease;
    }

    .show-hidden-chats-button:hover {
        color: var(--color-text-primary); /* Slightly darker on hover */
    }

    .show-hidden-chats-button:focus-visible {
        outline: 2px solid var(--color-primary-focus);
        outline-offset: 2px;
        border-radius: 4px;
    }

    .show-hidden-chats-button .clickable-icon {
        color: var(--color-grey-60); /* Icon color matches text */
        flex-shrink: 0;
    }

    /* Fade-in animation for show hidden chats button after sync completes */
    .show-hidden-chats-button.fade-in {
        animation: fadeInQuick 0.15s ease-out;
    }

    @keyframes fadeInQuick {
        0% { opacity: 0; }
        100% { opacity: 1; }
    }

    /* Inline syncing indicator - replaces "Show hidden chats" button during sync */
    .syncing-inline-indicator {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.85em; /* Match group-title font size */
        font-weight: 500; /* Match group-title font weight */
        text-transform: uppercase; /* Match group-title text transform */
        letter-spacing: 0.5px; /* Match group-title letter spacing */
        animation: fadeInQuick 0.15s ease-out;
    }

    /* Syncing icon with rotation animation */
    .syncing-inline-indicator .syncing-icon {
        flex-shrink: 0;
        animation: syncIconSpin 1.2s linear infinite;
        /* Apply shimmer gradient to icon */
        background: linear-gradient(
            90deg,
            var(--color-grey-60) 0%,
            var(--color-grey-60) 40%,
            var(--color-grey-40) 50%,
            var(--color-grey-60) 60%,
            var(--color-grey-60) 100%
        );
        background-size: 200% 100%;
        -webkit-mask-image: url("@openmates/ui/static/icons/reload.svg");
        mask-image: url("@openmates/ui/static/icons/reload.svg");
    }

    @keyframes syncIconSpin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    /* Syncing text with shimmer gradient animation (same as ActiveChat "Processing...") */
    .syncing-inline-indicator .syncing-text {
        background: linear-gradient(
            90deg,
            var(--color-grey-60) 0%,
            var(--color-grey-60) 40%,
            var(--color-grey-40) 50%,
            var(--color-grey-60) 60%,
            var(--color-grey-60) 100%
        );
        background-size: 200% 100%;
        background-clip: text;
        -webkit-background-clip: text;
        color: transparent;
        animation: syncingShimmer 1.5s infinite linear;
    }

    @keyframes syncingShimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }

    .no-chats-indicator {
        text-align: center;
        padding: 12px 20px;
        color: var(--color-grey-60);
        font-style: italic;
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
    
    .no-hidden-chats-message {
        padding: 24px 16px;
        text-align: center;
        color: var(--color-grey-60);
    }
    
    .no-hidden-chats-message p {
        margin: 0;
        font-size: 14px;
    }

    .overscroll-unlock-label,
    .overscroll-unlock-info {
        margin: 0;
        color: var(--color-grey-70);
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .overscroll-unlock-label .clickable-icon {
        flex-shrink: 0;
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

    .overscroll-unlock-input-wrapper {
        display: flex;
        flex-direction: column;
        padding-bottom: 10px;
    }

    .overscroll-unlock-input {
        all: unset;
        padding: 12px 16px;
        background: var(--color-grey-20);
        border-radius: 8px;
        font-size: 16px;
        color: var(--color-text-primary);
        border: 2px solid transparent;
        transition: border-color 0.2s;
        width: 100%;
        box-sizing: border-box;
    }

    .overscroll-unlock-input:focus {
        border-color: var(--color-primary);
        outline: none;
    }

    .overscroll-unlock-input.error {
        border-color: #E80000;
    }

    .overscroll-unlock-input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .overscroll-unlock-error {
        color: #E80000;
        font-size: 0.85em;
        margin-top: 4px;
    }

    .loading-spinner {
        width: 16px;
        height: 16px;
        border: 2px solid var(--color-grey-30);
        border-top-color: var(--color-button-text, var(--color-text-primary));
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
        transition: transform 0.2s ease, opacity 0.2s ease;
    }

    .overscroll-unlock-close:hover {
        transform: scale(1.1) rotate(90deg);
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
