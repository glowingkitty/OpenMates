<script lang="ts">
	import {
		// components
		Chats,
		ActiveChat,
		Header,
		Settings,
		Notification,
		ChatMessageNotification,
		// stores
		isInSignupProcess,
		authStore,
		initialize, // Import initialize directly
		panelState, // Import the new central panel state store
		settingsDeepLink,
		activeChatStore, // Import for deep linking
		activeEmbedStore, // Import for embed deep linking
		phasedSyncState, // Import phased sync state store
		messageHighlightStore, // Import message highlight store for deep linking
		websocketStatus, // Import WebSocket status store
		userProfile, // Import user profile to access last_opened
		loadUserProfileFromDB, // Import loadUserProfileFromDB function
		loginInterfaceOpen, // Import loginInterfaceOpen to control login interface visibility
		currentSignupStep, // Import currentSignupStep to set signup step from hash
		getStepFromPath, // Import getStepFromPath to parse step from hash
		isSignupPath, // Import isSignupPath helper
		// types
		type Chat,
		// services
		chatDB,
		chatSyncService,
		webSocketService, // Import WebSocket service to listen for auth errors
		mostUsedAppsStore, // Import most used apps store to fetch on app load
		// deep link handler
		processDeepLink,
		processSettingsDeepLink as processSettingsDeepLinkUnified,
		type DeepLinkHandlers
	} from '@repo/ui';
	import {
		notificationStore,
		getKeyFromStorage,
		text,
		LANGUAGE_CODES,
		forcedLogoutInProgress,
		isPublicChat,
		loadSessionStorageDraft,
		getAllDraftChatIdsWithDrafts,
		NEW_CHAT_SENTINEL
	} from '@repo/ui';
	import { checkAndClearMasterKeyOnLoad } from '@repo/ui';
	import { onMount, onDestroy, untrack } from 'svelte';
	import { locale, waitLocale } from 'svelte-i18n';
	import { get } from 'svelte/store';
	import { browser } from '$app/environment';
	import { replaceState } from '$app/navigation';

	// --- State ---
	let isInitialLoad = $state(true);
	let activeChat = $state<ActiveChat | null>(null); // Fixed: Use $state for Svelte 5
	let isProcessingInitialHash = $state(false); // Track if we're processing initial hash load
	let originalHashChatId: string | null = null; // Store original hash chat ID from URL (read before anything modifies it)
	let deepLinkProcessed = $state(false); // Track if any deep link was processed during onMount to avoid loading welcome chat
	let pendingDeepLinkHandler: ((event: Event) => void) | null = null; // Store event handler for cleanup

	// CRITICAL: Reactive effect to watch for signup state changes
	// This handles cases where user profile loads asynchronously after initialize() completes
	// or when user logs in and signup state needs to be detected
	// Must be at top level (not inside onMount) for Svelte 5
	// Use untrack to prevent infinite loops when setting loginInterfaceOpen
	$effect(() => {
		// Only check if user is authenticated and has a last_opened path
		// CRITICAL: Also check that forcedLogoutInProgress is NOT set
		// If forced logout is in progress (master key missing after page reload with stayLoggedIn=false),
		// we should NOT resume signup because the user's session is being cleared
		if (
			$authStore.isAuthenticated &&
			$userProfile.last_opened &&
			isSignupPath($userProfile.last_opened) &&
			!$forcedLogoutInProgress
		) {
			// Use untrack to read current state without creating a dependency
			// This prevents infinite loops when we set loginInterfaceOpen or isInSignupProcess
			untrack(() => {
				const currentLoginOpen = $loginInterfaceOpen;
				const currentInSignup = $isInSignupProcess;

				// Ensure signup state is set
				if (!currentInSignup) {
					const step = getStepFromPath($userProfile.last_opened);
					currentSignupStep.set(step);
					isInSignupProcess.set(true);
					console.debug(
						`[+page.svelte] [$effect] Set signup step to: ${step} from last_opened: ${$userProfile.last_opened}`
					);
				}

				// Ensure login interface is open to show signup flow
				// Only set if not already open to prevent infinite loops
				if (!currentLoginOpen) {
					loginInterfaceOpen.set(true);
					console.debug('[+page.svelte] [$effect] Opened login interface to show signup flow');
				}
			});
		}
	});

	// SEO data from translations - use $text() for offline-first PWA compatibility
	// Uses metadata.webapp keys from translations (en.json, de.json, etc.)
	// $text() is reactive and will update when language changes
	// If translations aren't loaded, $text() returns the key itself as fallback
	let seoTitle = $derived($text('metadata.webapp.title.text'));
	let seoDescription = $derived($text('metadata.webapp.description.text'));
	let seoKeywords = $derived($text('metadata.default.keywords.text'));

	// --- Reactive Computations ---

	// Footer should only show in settings panel (not on main chat interface)
	let showFooter = $derived($panelState.isSettingsOpen);

	/**
	 * Handle chat deep linking from URL
	 * Supports both user chats (from IndexedDB) and demo/legal chats (from static data)
	 * After loading, immediately clears the URL to prevent sharing chat history
	 */
	async function handleChatDeepLink(chatId: string, messageId?: string | null) {
		console.debug(
			`[+page.svelte] Handling chat deep link for: ${chatId}${messageId ? `, message: ${messageId}` : ''}`
		);

		// If messageId is provided, set it in the highlight store
		if (messageId) {
			messageHighlightStore.set(messageId);
		}

		// CRITICAL: During initial hash load, always process (store might be initialized from hash but chat not loaded)
		// After initial load, skip if chat is already active in store (prevents unnecessary processing)
		if (!isProcessingInitialHash && $activeChatStore === chatId) {
			console.debug(
				`[+page.svelte] Chat ${chatId} is already active (not initial load), skipping deep link processing`
			);
			return;
		}

		// Update the activeChatStore so the Chats component highlights it when opened
		activeChatStore.setActiveChat(chatId);

		// Check if this is a demo or legal chat (public chat)
		const { getPublicChatById, convertDemoChatToChat, translateDemoChat } =
			await import('@repo/ui');
		const publicChat = getPublicChatById(chatId);

		if (publicChat) {
			// CRITICAL: For non-authenticated users during initial page load, check if they have
			// existing sessionStorage drafts BEFORE loading the default public chat.
			// Without this, a page reload with #chat-id=demo-for-everyone would discard the user's draft
			// because loadDemoWelcomeChat (which handles draft restoration) is only called from onNoHash.
			if (!$authStore.isAuthenticated && isProcessingInitialHash) {
				const draftChatIds = getAllDraftChatIdsWithDrafts();
				if (draftChatIds.length > 0) {
					console.debug(
						`[+page.svelte] Non-auth user has sessionStorage drafts during initial hash load - redirecting to loadDemoWelcomeChat instead of loading public chat ${chatId}`
					);
					await loadDemoWelcomeChat();
					return;
				}
			}

			// This is a demo or legal chat - load it directly (no need to wait for sync)
			console.debug(`[+page.svelte] Found deep-linked public chat:`, chatId);

			const loadPublicChat = async (retries = 20): Promise<void> => {
				if (activeChat) {
					// Translate and convert to Chat format
					const translatedChat = translateDemoChat(publicChat);
					const chat = convertDemoChatToChat(translatedChat);

					activeChat.loadChat(chat);

					// Dispatch globalChatSelected event so Chats.svelte highlights the chat
					const globalChatSelectedEvent = new CustomEvent('globalChatSelected', {
						detail: { chat },
						bubbles: true,
						composed: true
					});
					window.dispatchEvent(globalChatSelectedEvent);
					console.debug(
						`[+page.svelte] Dispatched globalChatSelected for deep-linked public chat:`,
						chatId
					);

					// Keep the URL hash so users can share/bookmark the chat
					// The activeChatStore.setActiveChat() call above already updated the hash
					return;
				} else if (retries > 0) {
					const delay = retries > 10 ? 50 : 100;
					await new Promise((resolve) => setTimeout(resolve, delay));
					return loadPublicChat(retries - 1);
				} else {
					console.error(
						`[+page.svelte] activeChat component not ready for deep-linked public chat`
					);
				}
			};

			await loadPublicChat();
			return;
		}

		// CRITICAL: For non-authenticated users, check if this is a sessionStorage-only draft chat
		// These are new chats that exist only in sessionStorage (not IndexedDB) - created when user types in a new chat
		// Without this check, navigating to a draft chat would fail and fall back to the default chat
		if (!$authStore.isAuthenticated) {
			const sessionDraft = loadSessionStorageDraft(chatId);
			if (sessionDraft) {
				console.debug(`[+page.svelte] Found sessionStorage draft for non-auth user:`, chatId);

				// Create a virtual chat object for this sessionStorage-only draft
				const now = Math.floor(Date.now() / 1000);
				const virtualChat: Chat = {
					chat_id: chatId,
					encrypted_title: null,
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

				const loadSessionStorageChat = async (retries = 20): Promise<void> => {
					if (activeChat) {
						activeChat.loadChat(virtualChat);

						// Dispatch globalChatSelected event so Chats.svelte highlights the chat
						const globalChatSelectedEvent = new CustomEvent('globalChatSelected', {
							detail: { chat: virtualChat },
							bubbles: true,
							composed: true
						});
						window.dispatchEvent(globalChatSelectedEvent);
						console.debug(
							`[+page.svelte] Dispatched globalChatSelected for sessionStorage draft chat:`,
							chatId
						);
						return;
					} else if (retries > 0) {
						const delay = retries > 10 ? 50 : 100;
						await new Promise((resolve) => setTimeout(resolve, delay));
						return loadSessionStorageChat(retries - 1);
					} else {
						console.error(`[+page.svelte] activeChat component not ready for sessionStorage draft`);
					}
				};

				await loadSessionStorageChat();
				return;
			}
		}

		// This is a user chat - load from IndexedDB
		// CRITICAL: For non-authenticated users, shared chats are already in IndexedDB, so load immediately
		// For authenticated users, wait for sync to complete (chat might not be in IndexedDB yet)
		const loadChatFromIndexedDB = async (retries = 20): Promise<void> => {
			try {
				await chatDB.init(); // Ensure DB is initialized
				const chat = await chatDB.getChat(chatId);

				if (chat) {
					console.debug(`[+page.svelte] Found deep-linked chat in IndexedDB:`, chat.chat_id);

					// Load the chat if activeChat component is ready
					if (activeChat) {
						activeChat.loadChat(chat);

						// Dispatch globalChatSelected event so Chats.svelte highlights the chat
						const globalChatSelectedEvent = new CustomEvent('globalChatSelected', {
							detail: { chat },
							bubbles: true,
							composed: true
						});
						window.dispatchEvent(globalChatSelectedEvent);
						console.debug(
							`[+page.svelte] Dispatched globalChatSelected for deep-linked chat:`,
							chat.chat_id
						);

						// Keep the URL hash so users can share/bookmark the chat
						// The activeChatStore.setActiveChat() call above already updated the hash
						return; // Success - exit
					} else if (retries > 0) {
						// If activeChat isn't ready yet, wait a bit and retry
						const delay = retries > 10 ? 50 : 100;
						await new Promise((resolve) => setTimeout(resolve, delay));
						return loadChatFromIndexedDB(retries - 1);
					} else {
						console.warn(
							`[+page.svelte] activeChat component not ready for deep link after retries`
						);
					}
				} else {
					// Chat not found in IndexedDB
					if ($authStore.isAuthenticated) {
						// For authenticated users, wait for sync to complete
						console.debug(
							`[+page.svelte] Chat ${chatId} not found in IndexedDB, waiting for sync...`
						);
					} else {
						// For non-auth users, retry a few times before giving up
						// CRITICAL: Shared chats are stored in IndexedDB by the share page, but there
						// may be a race condition where the transaction hasn't fully committed yet.
						// Retry with exponential backoff to handle this timing issue.
						if (retries > 0) {
							const delay = retries > 15 ? 50 : retries > 10 ? 100 : 200;
							console.debug(
								`[+page.svelte] Chat ${chatId} not found in IndexedDB (non-auth), retrying in ${delay}ms (${retries} retries left)`
							);
							await new Promise((resolve) => setTimeout(resolve, delay));
							return loadChatFromIndexedDB(retries - 1);
						} else {
							// After all retries, give up - chat truly doesn't exist
							console.warn(
								`[+page.svelte] Chat ${chatId} not found in IndexedDB after retries (non-auth user)`
							);
							activeChatStore.clearActiveChat();
						}
					}
				}
			} catch (error) {
				console.error(`[+page.svelte] Error loading deep-linked chat:`, error);
				// Clear URL on error - chat doesn't exist or can't be loaded
				activeChatStore.clearActiveChat();
			}
		};

		// For non-authenticated users, try loading immediately (shared chats are already in IndexedDB)
		if (!$authStore.isAuthenticated) {
			console.debug(
				`[+page.svelte] Non-auth user - loading shared chat immediately from IndexedDB: ${chatId}`
			);
			await loadChatFromIndexedDB();
		} else {
			// For authenticated users, wait for sync to complete
			const handlePhasedSyncComplete = async () => {
				console.debug(
					`[+page.svelte] Phased sync complete, attempting to load deep-linked chat: ${chatId}`
				);
				await loadChatFromIndexedDB();
				// Remove the listener after handling
				chatSyncService.removeEventListener('phasedSyncComplete', handlePhasedSyncComplete);
			};

			// Register listener for phased sync completion
			chatSyncService.addEventListener('phasedSyncComplete', handlePhasedSyncComplete);

			// Also try immediately in case sync already completed
			// (e.g., page reload with URL already set)
			setTimeout(handlePhasedSyncComplete, 1000);
		}
	}

	/**
	 * Handle embed deep linking from URL
	 * Opens the embed in fullscreen mode when #embed-id={embedId} is in the URL
	 */
	async function handleEmbedDeepLink(embedId: string) {
		console.debug(`[+page.svelte] Handling embed deep link for: ${embedId}`);

		// Mark that a deep link was processed
		deepLinkProcessed = true;

		// Update the activeEmbedStore so the URL hash is set
		// NOTE: This is a programmatic change; hashchange handler must ignore embed hash updates.
		activeEmbedStore.setActiveEmbed(embedId);

		// Wait a bit for ActiveChat component to be ready and register event listeners
		// This ensures the embedfullscreen event listener is registered
		await new Promise((resolve) => setTimeout(resolve, 300));

		// Dispatch embedfullscreen event to open the embed in fullscreen
		// This reuses the same system that opens embeds when clicking on embed previews
		const embedFullscreenEvent = new CustomEvent('embedfullscreen', {
			detail: {
				embedId: embedId,
				// Let handleEmbedFullscreen load and decode the embed content
				embedData: null,
				decodedContent: null,
				// Use a placeholder type; ActiveChat will infer the real embed type from the stored embed.
				embedType: 'app-skill-use',
				attrs: null
			},
			bubbles: true
		});

		console.debug(
			'[+page.svelte] Dispatching embedfullscreen event for deep-linked embed:',
			embedId
		);
		document.dispatchEvent(embedFullscreenEvent);
	}

	/**
	 * Handler for sync completion - loads chat based on priority:
	 * 1. URL hash chat (if present)
	 * 2. Last opened chat (if no hash)
	 * 3. Default (demo-for-everyone for non-auth, new chat for auth)
	 *
	 * This implements the "Auto-Open Logic" from sync.md Phase 1 requirements
	 *
	 * IMPORTANT: This function is only called on login (when sync completes after authentication).
	 * On tab reload, we load from IndexedDB directly (see instant load logic below).
	 */
	async function handleSyncCompleteAndLoadChat() {
		console.debug('[+page.svelte] Sync event received, checking what chat to load...');

		// CRITICAL: Check if we can auto-navigate
		// If user has made an explicit choice (clicked on a chat or new chat), don't override
		// If initial chat was already loaded, don't override
		if (!phasedSyncState.canAutoNavigate()) {
			console.debug(
				'[+page.svelte] Skipping sync auto-load: user made explicit choice or initial chat already loaded'
			);
			return;
		}

		// PRIORITY 1: URL hash chat has absolute priority
		// Use originalHashChatId if available (stored at start of onMount), otherwise check current hash
		// This prevents issues where welcome chat loading overwrote the hash
		let hashChatIdToLoad: string | null = null;
		if (typeof originalHashChatId !== 'undefined' && originalHashChatId !== null) {
			// Use original hash (read before anything could modify it)
			hashChatIdToLoad = originalHashChatId;
			console.debug(
				'[+page.svelte] Using ORIGINAL hash chat ID from start of onMount:',
				hashChatIdToLoad
			);
		} else if (browser) {
			// Fallback: check current hash (might have been modified)
			hashChatIdToLoad = window.location.hash.startsWith('#chat-id=')
				? window.location.hash.substring('#chat-id='.length)
				: window.location.hash.startsWith('#chat-id=')
					? window.location.hash.substring('#chat-id='.length)
					: null;
			console.debug('[+page.svelte] Using CURRENT hash chat ID (fallback):', hashChatIdToLoad);
		}

		if (hashChatIdToLoad) {
			console.debug(
				'[+page.svelte] URL hash contains chat ID, loading hash chat (priority 1):',
				hashChatIdToLoad
			);
			await handleChatDeepLink(hashChatIdToLoad);
			return; // Don't load last opened chat or default
		}

		// PRIORITY 2: Last opened chat (only if no hash)
		await handleSyncCompleteAndLoadLastChat();
	}

	/**
	 * Handler for sync completion - automatically loads the last opened chat
	 * This implements the "Auto-Open Logic" from sync.md Phase 1 requirements
	 *
	 * IMPORTANT: This function is only called on login (when sync completes after authentication).
	 * On tab reload, we load from IndexedDB directly (see instant load logic below).
	 *
	 * PRIORITY SYSTEM:
	 * 1. Skip if last_opened is a signup step (priority 1 already handled)
	 * 2. Skip if hash is a chat (priority 2 - hash chat takes precedence)
	 * 3. Load last_opened chat if hash is settings (priority 3) or no hash
	 *
	 * OPTIMIZATION: Check if chat is already loaded to avoid duplicate loads
	 * Only loads if chat exists in IndexedDB but isn't currently displayed
	 */
	async function handleSyncCompleteAndLoadLastChat() {
		console.debug('[+page.svelte] Loading last opened chat (checking priority system)...');

		// PRIORITY 1: Skip if last_opened is a signup step (already handled with priority 1)
		const lastOpenedChatId = $userProfile.last_opened;
		if (lastOpenedChatId && isSignupPath(lastOpenedChatId)) {
			console.debug(
				'[+page.svelte] [PRIORITY 1] Skipping last_opened chat - it is a signup step (already handled)'
			);
			return;
		}

		// PRIORITY 2: Skip if hash is a chat (hash chat takes precedence)
		if (originalHashChatId) {
			console.debug(
				'[+page.svelte] [PRIORITY 2] Skipping last_opened chat - hash chat has priority:',
				originalHashChatId
			);
			return;
		}

		// PRIORITY 3: Check if hash is settings - if so, we load last_opened chat after settings
		const currentHash = browser ? window.location.hash : '';
		const { parseDeepLink } = await import('@repo/ui');
		const parsed = currentHash ? parseDeepLink(currentHash) : null;
		const isSettingsHash = parsed?.type === 'settings';

		// Only load last_opened chat if:
		// - No hash in URL, OR
		// - Hash is settings (priority 3: settings first, then last_opened chat)
		if (currentHash && !isSettingsHash) {
			console.debug(
				'[+page.svelte] [PRIORITY 2] Skipping last_opened chat - hash is not settings:',
				currentHash
			);
			return;
		}

		if (!lastOpenedChatId) {
			console.debug(
				'[+page.svelte] No last opened chat in user profile (from server) - will load default chat'
			);
			// Don't return - continue to load default chat below
		}

		// Try to load last opened chat if it exists
		if (lastOpenedChatId) {
			// Handle "new chat window" case - this is not a real chat ID
			if (lastOpenedChatId === '/chat/new' || lastOpenedChatId === 'new') {
				console.debug('[+page.svelte] Last opened is new chat window, clearing active chat');
				// Clear active chat to show new chat window
				// The ActiveChat component will show the new chat interface when no chat is selected
				activeChatStore.clearActiveChat();
				return; // Don't load default chat
			}

			// Skip if this chat is already loaded (active chat store matches)
			if ($activeChatStore === lastOpenedChatId) {
				console.debug('[+page.svelte] Last opened chat already loaded, skipping');
				return; // Already loaded, don't load default
			}

			try {
				// Ensure chatDB is initialized
				await chatDB.init();

				// Try to load the last opened chat from IndexedDB
				// This will succeed as soon as the chat data is saved during any sync phase
				const lastChat = await chatDB.getChat(lastOpenedChatId);

				if (lastChat && activeChat) {
					if (isSettingsHash) {
						console.debug(
							'[+page.svelte] [PRIORITY 3] ✅ Loading last_opened chat after settings hash:',
							lastOpenedChatId
						);
					} else {
						console.debug(
							'[+page.svelte] ✅ Loading last opened chat from sync (login):',
							lastOpenedChatId
						);
					}

					// Update the active chat store so the sidebar highlights it when opened
					activeChatStore.setActiveChat(lastOpenedChatId);

					// Load the chat in the UI
					activeChat.loadChat(lastChat);

					console.debug('[+page.svelte] ✅ Successfully loaded last opened chat from sync (login)');
					return; // Successfully loaded, don't load default
				} else if (!lastChat) {
					console.debug(
						'[+page.svelte] Last opened chat not yet in IndexedDB, will try again after next sync phase'
					);
					// Don't return - will load default below
				} else if (!activeChat) {
					console.debug('[+page.svelte] ActiveChat component not ready yet, retrying...');
					// Retry after a short delay if activeChat isn't ready
					setTimeout(handleSyncCompleteAndLoadLastChat, 100);
					return; // Will retry, don't load default yet
				}
			} catch (error) {
				console.error('[+page.svelte] Error loading last opened chat:', error);
				// Continue to load default chat on error
			}
		}

		// PRIORITY 3: Default chat (only if no last opened chat was loaded)
		// For non-authenticated users: demo-for-everyone
		// For authenticated users: new chat window
		if (!$activeChatStore && activeChat) {
			if (!$authStore.isAuthenticated) {
				// Non-auth: load demo-for-everyone
				console.debug(
					'[+page.svelte] No last opened chat, loading demo-for-everyone (default for non-auth)'
				);
				const { DEMO_CHATS, convertDemoChatToChat, translateDemoChat } = await import('@repo/ui');
				const welcomeDemo = DEMO_CHATS.find((chat) => chat.chat_id === 'demo-for-everyone');
				if (welcomeDemo) {
					const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
					const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
					activeChatStore.setActiveChat('demo-for-everyone');
					activeChat.loadChat(welcomeChat);
				}
			} else {
				// Auth: show new chat window (clear active chat)
				console.debug(
					'[+page.svelte] No last opened chat, showing new chat window (default for auth)'
				);
				activeChatStore.clearActiveChat();
			}
		}
	}

	// Login state management happens through components now
	// Login overlay feature was removed as incomplete implementation

	// --- Lifecycle ---
	// Define handlers outside onMount so they're accessible for cleanup
	let handleWebSocketAuthError: (() => Promise<void>) | null = null;
	let handleAdminStatusUpdate: ((payload: { is_admin: boolean }) => void) | null = null;
	let handlePaymentCompleted:
		| ((payload: { order_id: string; credits_purchased: number; current_credits: number }) => void)
		| null = null;
	let handlePaymentFailed: ((payload: { order_id: string; message: string }) => void) | null = null;
	let wasInSignupProcessAtMount = false;

	/**
	 * Check if a settings deep link requires authentication
	 * Some settings (like app_store, interface) are public and don't require authentication
	 * Others (like billing, account, security) require authentication
	 * @param settingsPath The settings path (e.g., '/billing/invoices/.../refund' or '/app_store')
	 * @returns true if authentication is required, false otherwise
	 */
	function requiresAuthentication(settingsPath: string): boolean {
		// Public settings that don't require authentication
		const publicSettings = [
			'app_store',
			'appstore', // Alias
			'interface',
			'main', // Main settings page
			'newsletter', // Newsletter settings (for email link actions)
			'email', // Email blocking settings (for email link actions)
			'support', // Support settings (for sponsoring the project)
			'report_issue' // Report issue settings (for reporting bugs/issues)
		];

		// Check if path starts with any public setting
		const normalizedPath = settingsPath.startsWith('/') ? settingsPath.substring(1) : settingsPath;

		// Specific check for account deletion deep links from email
		// These allow uncompleted accounts to be deleted without login
		if (normalizedPath.startsWith('account/delete/')) {
			return false;
		}

		const firstSegment = normalizedPath.split('/')[0];

		// Normalize hyphens to underscores for consistency (e.g., report-issue -> report_issue)
		// This matches the normalization done in processSettingsDeepLink
		const normalizedSegment = firstSegment.replace(/-/g, '_');

		// Map aliases
		const mappedPath = normalizedSegment === 'appstore' ? 'app_store' : normalizedSegment;

		// If it's a public setting, no authentication required
		if (publicSettings.includes(mappedPath) || normalizedPath === '') {
			return false;
		}

		// All other settings require authentication (billing, account, security, etc.)
		return true;
	}

	/**
	 * Process settings deep link - uses unified deep link handler
	 * Handles navigation to settings pages based on hash
	 * @param hash The hash string (e.g., '#settings/billing/invoices/.../refund')
	 */
	function processSettingsDeepLink(hash: string) {
		processSettingsDeepLinkUnified(hash, {
			openSettings: () => panelState.openSettings(),
			setSettingsDeepLink: (path: string) => settingsDeepLink.set(path)
		});
	}

	/**
	 * Handle pending deep link processing after successful login
	 * This handles cases where user opened a deep link while not authenticated
	 */
	async function handlePendingDeepLink(event: CustomEvent<{ hash: string }>) {
		const hash = event.detail.hash;
		console.debug(`[+page.svelte] Processing pending deep link: ${hash}`);

		const handlers: DeepLinkHandlers = {
			onChat: handleChatDeepLink,
			onSettings: (path: string, fullHash: string) => processSettingsDeepLink(fullHash),
			onSignup: (step: string) => {
				currentSignupStep.set(step);
				isInSignupProcess.set(true);
				loginInterfaceOpen.set(true);
			},
			onEmbed: handleEmbedDeepLink,
			requiresAuthentication,
			isAuthenticated: () => $authStore.isAuthenticated,
			openSettings: () => panelState.openSettings(),
			openLogin: () => loginInterfaceOpen.set(true),
			setSettingsDeepLink: (path: string) => settingsDeepLink.set(path)
		};

		await processDeepLink(hash, handlers);
	}

	onMount(async () => {
		console.debug('[+page.svelte] onMount started');

		// CRITICAL: Read and store the ORIGINAL hash value BEFORE anything can modify it
		// This ensures we can check for hash chat even if welcome chat loading overwrites the hash
		const originalHash = browser ? window.location.hash : '';
		console.debug('[+page.svelte] [INIT] Original hash from URL:', originalHash);

		// SECURITY: Check if master key should be cleared (if stayLoggedIn was false)
		// This must happen BEFORE loading user data to ensure key is cleared if needed
		// This handles cases where user closed tab/browser with stayLoggedIn=false
		await checkAndClearMasterKeyOnLoad();

		// PRIORITY 1: Check last_opened for signup step BEFORE processing hash
		// Load user profile first to check last_opened
		await loadUserProfileFromDB();
		const initialProfile = $userProfile;
		const hasSignupInLastOpened =
			initialProfile?.last_opened && isSignupPath(initialProfile.last_opened);

		// CRITICAL: Set optimistic auth state BEFORE processing deep links
		// This ensures settings deep links that require auth (like account/delete) work correctly in new tabs
		// Without this, $authStore.isAuthenticated would be false during deep link processing,
		// causing authenticated settings pages to be blocked and redirect to login
		const masterKey = await getKeyFromStorage();
		const localProfile = $userProfile;
		const hasLocalAuthData = masterKey && localProfile && localProfile.username;

		if (hasLocalAuthData) {
			// User has local data - optimistically set as authenticated
			console.debug(
				'[+page.svelte] ✅ Local auth data found - setting optimistic auth state BEFORE deep link processing'
			);

			// CRITICAL FIX: Reset forcedLogoutInProgress if it was set but auth data is now valid
			// This handles race conditions where the flag was set during a previous load cycle
			// but the user has since logged in (e.g., in another tab)
			if (get(forcedLogoutInProgress)) {
				console.debug(
					'[+page.svelte] Resetting forcedLogoutInProgress to false - valid auth data found'
				);
				forcedLogoutInProgress.set(false);
			}

			authStore.update((state) => ({
				...state,
				isAuthenticated: true,
				isInitialized: true // Mark as initialized so UI updates immediately
			}));
		} else {
			console.debug('[+page.svelte] No local auth data found - user will remain unauthenticated');

			// CRITICAL FIX: Detect "stayLoggedIn=false reload" scenario
			// If user profile exists with username but master key is missing, this means:
			// 1. User was logged in with stayLoggedIn=false (master key in memory only)
			// 2. Page was reloaded, clearing the memory-stored master key
			// 3. IndexedDB user profile still exists from the session
			// In this case, we must:
			// - Set forcedLogoutInProgress to prevent any encrypted chat loading attempts
			// - Clear the URL hash if it points to an encrypted chat
			// - Ensure demo-for-everyone loads instead of the previous chat
			if (localProfile && localProfile.username) {
				console.warn(
					'[+page.svelte] ⚠️ User profile exists but master key is missing (stayLoggedIn=false reload)'
				);
				console.debug(
					'[+page.svelte] Setting forcedLogoutInProgress=true IMMEDIATELY to prevent encrypted chat loading'
				);
				forcedLogoutInProgress.set(true);

				// Check if URL hash points to an encrypted chat (not demo-/legal-)
				// If so, clear the hash and navigate to demo-for-everyone to prevent loading broken chat
				if (originalHash) {
					let hashChatId: string | null = null;
					if (originalHash.startsWith('#chat-id=')) {
						hashChatId = originalHash.substring('#chat-id='.length);
					}

					if (hashChatId && !isPublicChat(hashChatId)) {
						console.debug(
							`[+page.svelte] URL hash points to encrypted chat ${hashChatId} - clearing hash and loading demo-for-everyone`
						);
						// Clear the hash to prevent deep link handler from trying to load it
						window.location.hash = '';
						// Clear the stored original hash so deep link handler doesn't use it
						// Note: We can't reassign originalHash (const), but we'll handle this in deep link processing
						// by setting activeChatStore to demo-for-everyone explicitly
						activeChatStore.setActiveChat('demo-for-everyone');
					}
				}
			}
		}

		// Now check auth state after optimistic loading (used throughout onMount)
		const isAuth = $authStore.isAuthenticated;

		// Check if forced logout is in progress (set earlier when master key is missing)
		const isForcedLogoutAtStartup = get(forcedLogoutInProgress);

		// CRITICAL: Only resume signup if NOT in forced logout state
		// If master key is missing (stayLoggedIn=false reload), we should NOT resume signup
		// because the user's session is being cleared and they need to start fresh
		if (hasSignupInLastOpened && !isForcedLogoutAtStartup) {
			// PRIORITY 1: last_opened signup step takes absolute priority - skip hash processing
			const step = getStepFromPath(initialProfile.last_opened);
			currentSignupStep.set(step);
			isInSignupProcess.set(true);
			loginInterfaceOpen.set(true);
			console.debug(
				`[+page.svelte] [PRIORITY 1] Found signup step in last_opened: ${step} - skipping hash processing`
			);
			originalHashChatId = null; // No hash processing when signup is in last_opened
		} else if (isForcedLogoutAtStartup && hasSignupInLastOpened) {
			// User had signup in progress but was force-logged out (master key missing)
			// Clear the signup state and show login/demo instead
			console.debug(
				`[+page.svelte] [FORCED LOGOUT] Found signup step in last_opened but master key is missing - skipping signup resume`
			);
			// Don't set signup state - let the normal logout flow handle showing login/demo
		} else {
			// UNIFIED APPROACH: Always process through deep link handler (including empty hash)
			// This ensures all chat loading goes through one consistent system
			console.debug(
				'[+page.svelte] Processing all hashes (including empty) through unified deep link handler:',
				originalHash || '(no hash)'
			);

			// Set global flag to prevent auto-loading during deep link processing
			const { deepLinkProcessing } = await import('@repo/ui');
			deepLinkProcessing.set(true);

			// CRITICAL: Check if forced logout is in progress (stayLoggedIn=false reload scenario)
			// If so, skip processing encrypted chat hashes - they can't be decrypted
			const isForcedLogout = get(forcedLogoutInProgress);

			// Extract originalHashChatId for chat hashes (needed for other logic)
			if (
				originalHash &&
				(originalHash.startsWith('#chat-id=') || originalHash.startsWith('#chat-id='))
			) {
				originalHashChatId = originalHash.startsWith('#chat-id=')
					? originalHash.substring('#chat-id='.length)
					: originalHash.substring('#chat-id='.length);

				// CRITICAL: Don't set active chat to encrypted chat ID during forced logout
				// The encrypted chat can't be decrypted without master key
				if (isForcedLogout && !isPublicChat(originalHashChatId)) {
					console.debug(
						`[+page.svelte] Forced logout in progress - skipping encrypted chat hash ${originalHashChatId}, using demo-for-everyone`
					);
					originalHashChatId = 'demo-for-everyone';
					activeChatStore.setActiveChat('demo-for-everyone');
				} else {
					// Set active chat store immediately to prevent race conditions
					activeChatStore.setActiveChat(originalHashChatId);
				}
			} else {
				originalHashChatId = null;
			}

			// Process through unified deep link handler
			// NOTE: Auth state is now set above, so isAuthenticated() will return correct value
			// During forced logout, the handler will load demo-for-everyone for empty/null hash
			const handlers = createDeepLinkHandlers();
			const hashToProcess =
				isForcedLogout && originalHashChatId === 'demo-for-everyone' ? '' : originalHash || '';
			await processDeepLink(hashToProcess, handlers);
			deepLinkProcessed = true; // Mark that processing was completed

			// Clear the deep link processing flag
			deepLinkProcessing.set(false);
		}

		// Handle ?lang= query parameter for language selection
		if (browser) {
			const urlParams = new URLSearchParams(window.location.search);
			const langParam = urlParams.get('lang');
			// Use supported locales from single source of truth
			const supportedLocales = LANGUAGE_CODES;

			if (langParam && supportedLocales.includes(langParam)) {
				console.debug(`[+page.svelte] Setting locale from URL parameter: ${langParam}`);

				// Set the locale
				locale.set(langParam);
				await waitLocale();

				// Save to localStorage and cookies
				localStorage.setItem('preferredLanguage', langParam);
				document.cookie = `preferredLanguage=${langParam}; path=/; max-age=31536000; SameSite=Lax`;

				// Update HTML lang attribute
				document.documentElement.setAttribute('lang', langParam);

				// Remove the lang parameter from URL (cleaner URL after setting preference)
				const newUrl = new URL(window.location.href);
				newUrl.searchParams.delete('lang');
				replaceState(newUrl.toString(), {});
			}
		}

		// NOTE: Shared chat cleanup for unauthenticated users
		// Shared chats are now intentionally persisted in IndexedDB (with keys in sharedChatKeyStorage)
		// so that users can explore multiple shared chats across tab reloads and closures before signup.
		// Cleanup only happens when users explicitly delete a shared chat via the chat context menu.
		// The old session-based cleanup (using sessionStorage) has been removed to support this behavior.
		//
		// If we ever need to clean up orphaned chats (chats without keys), we could add logic here
		// that compares IndexedDB chats against sharedChatKeyStorage to find mismatches.
		console.debug(
			'[+page.svelte] Shared chat cleanup skipped - shared chats persist until explicitly deleted'
		);

		// CRITICAL: Check for signup hash in URL BEFORE initialize() to ensure hash-based signup state takes precedence
		// This ensures signup flow opens immediately on page reload if URL has #signup/ hash
		// The hash takes precedence over last_opened from IndexedDB and checkAuth() logic
		let hasSignupHash = false;
		if (window.location.hash.startsWith('#signup/')) {
			hasSignupHash = true;
			// Handle signup deep linking - open login interface and set signup step
			console.debug(
				`[+page.svelte] Found signup deep link in URL (before initialize): ${window.location.hash}`
			);

			// Extract step from hash (e.g., #signup/credits -> credits)
			const signupHash = window.location.hash.substring(1); // Remove leading #
			const step = getStepFromPath(signupHash);

			console.debug(
				`[+page.svelte] Setting signup step to: ${step} from hash: ${window.location.hash}`
			);

			// Set signup step and open login interface BEFORE initialize() runs
			// This ensures checkAuth() won't override these values
			currentSignupStep.set(step);
			isInSignupProcess.set(true);
			loginInterfaceOpen.set(true);
		}

		// CRITICAL: Mark sync completed IMMEDIATELY to prevent "Loading chats..." flash
		// Must happen before initialize() because it checks $phasedSyncState.initialSyncCompleted
		//
		// This applies to:
		// 1. Non-authenticated users - they have no chats to sync, show default suggestions
		// 2. Authenticated users WITH local data - they have cached data in IndexedDB,
		//    NewChatSuggestions can load from local DB while background sync runs
		//
		// The phasedSyncState store resets to initialSyncCompleted=false on page reload,
		// so without this early mark, users see "Loading chats..." when clicking "new chat"
		// before WebSocket sync events fire. This is a race condition that causes poor UX.
		//
		// Note: Sync events will still fire and update data in the background.
		// The event listeners are registered regardless of initialSyncCompleted status
		// because the condition checks `isAuth || !initialSyncCompleted`.
		if (!isAuth) {
			phasedSyncState.markSyncCompleted();
			console.debug(
				'[+page.svelte] [NON-AUTH] Pre-marked sync as completed to prevent loading flash'
			);
		} else if (hasLocalAuthData) {
			// CRITICAL: For authenticated users with local data (master key + profile),
			// mark sync completed immediately. The NewChatSuggestions component loads from
			// IndexedDB and has fallbacks to default suggestions. Showing "Loading chats..."
			// while waiting for WebSocket sync is poor UX when user has cached data.
			phasedSyncState.markSyncCompleted();
			console.debug(
				'[+page.svelte] [AUTH WITH LOCAL DATA] Pre-marked sync as completed to prevent loading flash'
			);
		}

		// CRITICAL: Start IndexedDB initialization IMMEDIATELY in parallel (non-blocking)
		// This ensures DB is ready when sync data arrives, but doesn't block anything
		// Note: Demo chats are now loaded from static bundle, not IndexedDB
		let dbInitPromise: Promise<void> | null = null;
		if (isAuth) {
			console.debug('[+page.svelte] Starting IndexedDB initialization (non-blocking)...');
			dbInitPromise = chatDB
				.init()
				.then(() => {
					console.debug('[+page.svelte] ✅ IndexedDB initialized and ready');
				})
				.catch((error) => {
					console.error('[+page.svelte] ❌ IndexedDB initialization failed:', error);
				});
		}

		// Listen for WebSocket auth errors and trigger logout
		// This handles cases where the session expires and WebSocket connection is rejected with 403
		handleWebSocketAuthError = async () => {
			console.info(
				'[+page.svelte] WebSocket auth error detected - session expired or invalid token. Logging out user.'
			);

			// Import checkAuth dynamically to avoid circular dependencies
			// checkAuth is exported from @repo/ui via authStore (which re-exports from authSessionActions)
			const { checkAuth } = await import('@repo/ui');

			// Check if user was previously authenticated (has master key)
			const hadMasterKey = !!(await getKeyFromStorage());

			if (hadMasterKey) {
				// User was authenticated - trigger logout flow
				// Use checkAuth with force=true to trigger the same logout logic as when server says user is not authenticated
				await checkAuth(undefined, true);
			} else {
				// User wasn't authenticated - just clear auth state
				console.debug('[+page.svelte] User was not authenticated, just clearing auth state');
			}
		};

		// Register listener for WebSocket auth errors
		webSocketService.addEventListener('authError', handleWebSocketAuthError);
		console.debug('[+page.svelte] Registered WebSocket auth error listener');

		// Listen for payment completion notifications via WebSocket
		// This handles cases where payment completes after user has moved on from signup flow
		handlePaymentCompleted = (payload: {
			order_id: string;
			credits_purchased: number;
			current_credits: number;
		}) => {
			console.debug(
				'[+page.svelte] Received payment_completed notification via WebSocket:',
				payload
			);

			// CRITICAL: Suppress notifications during signup - Payment.svelte already handles them
			// Only show notification if user is not in signup process
			if (!get(isInSignupProcess)) {
				// Show success notification popup (using Notification.svelte component)
				notificationStore.success(
					`Payment completed! ${payload.credits_purchased.toLocaleString()} credits have been added to your account.`,
					5000
				);
			} else {
				console.debug('[+page.svelte] Suppressing payment_completed notification during signup');
			}

			// Always update credits in user profile if available (even during signup)
			if (payload.current_credits !== undefined) {
				// Import updateProfile dynamically (non-blocking)
				import('@repo/ui')
					.then(({ updateProfile }) => {
						updateProfile({ credits: payload.current_credits });
					})
					.catch((error) => {
						console.warn('[+page.svelte] Failed to import updateProfile:', error);
					});
			}
		};

		// Listen for payment failure notifications via WebSocket
		// This handles cases where payment fails minutes after user has moved on from signup flow
		handlePaymentFailed = (payload: { order_id: string; message: string }) => {
			console.debug('[+page.svelte] Received payment_failed notification via WebSocket:', payload);
			// Show error notification popup (using Notification.svelte component)
			notificationStore.error(
				payload.message || 'Payment failed. Please try again or use a different payment method.',
				10000 // Show for 10 seconds since this is important
			);
		};

		// Listen for admin status updates via WebSocket
		// This handles cases where admin privileges are granted/revoked while user is logged in
		handleAdminStatusUpdate = async (payload: { is_admin: boolean }) => {
			console.debug(
				'[+page.svelte] Received user_admin_status_updated notification via WebSocket:',
				payload
			);

			// Update user profile with new admin status
			if (typeof payload.is_admin === 'boolean') {
				// Import updateProfile dynamically (non-blocking)
				import('@repo/ui')
					.then(({ updateProfile }) => {
						updateProfile({ is_admin: payload.is_admin });
						console.debug(`[+page.svelte] Updated user profile: is_admin = ${payload.is_admin}`);
					})
					.catch((error) => {
						console.warn('[+page.svelte] Failed to import updateProfile:', error);
					});
			}
		};

		// Register WebSocket listeners for payment notifications
		// NOTE: Only register payment handlers if NOT in signup mode, as Payment.svelte already handles them during signup
		// This prevents duplicate handler registrations during signup flow
		// Store the signup state at registration time for proper cleanup
		wasInSignupProcessAtMount = get(isInSignupProcess);

		// Register admin status update listener (always register, not dependent on signup state)
		webSocketService.on('user_admin_status_updated', handleAdminStatusUpdate);
		console.debug('[+page.svelte] Registered WebSocket admin status update listener');

		if (!wasInSignupProcessAtMount) {
			// CRITICAL FIX: Clean up any existing handlers before registering new ones
			// This prevents duplicate handler registrations if the effect runs multiple times
			if (handlePaymentCompleted) {
				webSocketService.off('payment_completed', handlePaymentCompleted);
			}
			if (handlePaymentFailed) {
				webSocketService.off('payment_failed', handlePaymentFailed);
			}

			// Register new handlers
			webSocketService.on('payment_completed', handlePaymentCompleted);
			webSocketService.on('payment_failed', handlePaymentFailed);
			console.debug('[+page.svelte] Registered WebSocket payment notification listeners');
		} else {
			console.debug('[+page.svelte] Skipping payment handler registration during signup');
		}

		// NOTE: Shared chat automatic cleanup has been removed.
		// Shared chats now persist in IndexedDB across browser sessions (with keys in sharedChatKeyStorage)
		// so that unauthenticated users can explore multiple shared chats before deciding to sign up.
		// Users can delete shared chats explicitly via the chat context menu.
		// See: sharedChatKeyStorage.ts for how shared chat keys are persisted.

		// CRITICAL: Register sync event listeners FIRST, before initialization
		// chatSyncService can auto-start sync when WebSocket connects during initialize()
		// If we register listeners after, we'll miss the syncComplete event
		if (isAuth || !$phasedSyncState.initialSyncCompleted) {
			console.debug('[+page.svelte] Registering sync event listeners...');

			// OPTIMIZATION: Only Phase 1 triggers chat loading (last opened chat)
			// Phase 2 and 3 only update the chat list in the sidebar (handled by Chats.svelte)
			// This prevents duplicate load attempts and improves performance
			const handlePhase1ChatLoad = async () => {
				console.debug('[+page.svelte] Phase 1 complete, loading last opened chat');
				await handleSyncCompleteAndLoadChat();
			};

			// Mark sync completed when phasedSyncComplete fires (after all phases)
			const handleSyncCompleted = () => {
				console.debug('[+page.svelte] Full sync complete, marking as completed');
				phasedSyncState.markSyncCompleted();
			};

			// Only Phase 1 triggers chat loading - this is the "last opened chat" data
			chatSyncService.addEventListener('phase_1_last_chat_ready', handlePhase1ChatLoad);

			// phasedSyncComplete marks overall sync as done (for sync status UI)
			chatSyncService.addEventListener('phasedSyncComplete', handleSyncCompleted);

			console.debug(
				'[+page.svelte] Sync event listeners registered (Phase 1 for chat load, phasedSyncComplete for status)'
			);
		}

		// Initialize authentication state (panelState will react to this)
		await initialize(); // Call the imported initialize function
		console.debug('[+page.svelte] initialize() finished');

		// CRITICAL: Re-check signup hash AFTER initialize() completes
		// This ensures hash-based signup state persists even if checkAuth() reset it
		// The hash takes absolute precedence over last_opened
		if (hasSignupHash && window.location.hash.startsWith('#signup/')) {
			console.debug(
				`[+page.svelte] Re-applying signup hash state after initialize(): ${window.location.hash}`
			);
			const signupHash = window.location.hash.substring(1); // Remove leading #
			const step = getStepFromPath(signupHash);
			currentSignupStep.set(step);
			isInSignupProcess.set(true);
			loginInterfaceOpen.set(true);
			console.debug(
				`[+page.svelte] Re-applied signup state: step=${step}, isInSignupProcess=true, loginInterfaceOpen=true`
			);
		}

		// CRITICAL: Chat deep links are already processed at the very start of onMount
		// This section only handles user chats that need to wait for sync
		// Public chats and shared chats are already loaded immediately above
		if (originalHashChatId && !isProcessingInitialHash) {
			// Check if it's a user chat that needs sync
			const { getPublicChatById } = await import('@repo/ui');
			const publicChat = getPublicChatById(originalHashChatId);

			if (!publicChat && isAuth) {
				// User chat for authenticated users - will be loaded after sync completes
				console.debug(
					`[+page.svelte] [DETECTED] Hash chat is user chat, will load after sync: ${originalHashChatId}`
				);
			}
		}

		// CRITICAL: Check if user is in signup flow AFTER initialize() completes
		// This ensures login interface opens on page reload or login for users who haven't completed signup
		// checkAuth() should have already set this, but we verify and ensure login interface is open
		// This handles both page reload and login scenarios
		// Note: The $effect at top level will also handle this reactively, but we check immediately here too
		// CRITICAL: Also check that forced logout is NOT in progress
		// If forced logout is happening (master key missing), don't resume signup
		if (
			$authStore.isAuthenticated &&
			$userProfile.last_opened &&
			isSignupPath($userProfile.last_opened) &&
			!get(forcedLogoutInProgress)
		) {
			console.debug(
				'[+page.svelte] User is in signup flow after initialize() - ensuring login interface is open',
				{
					last_opened: $userProfile.last_opened,
					isInSignupProcess: $isInSignupProcess,
					loginInterfaceOpen: $loginInterfaceOpen
				}
			);

			// Ensure signup state is set
			if (!$isInSignupProcess) {
				const step = getStepFromPath($userProfile.last_opened);
				currentSignupStep.set(step);
				isInSignupProcess.set(true);
				console.debug(
					`[+page.svelte] Set signup step to: ${step} from last_opened: ${$userProfile.last_opened}`
				);
			}

			// Ensure login interface is open to show signup flow
			if (!$loginInterfaceOpen) {
				loginInterfaceOpen.set(true);
				console.debug('[+page.svelte] Opened login interface to show signup flow');
			}
		}

		// Fetch most used apps on app load (non-blocking, cached for 1 hour)
		// This ensures data is available when App Store opens
		mostUsedAppsStore.fetchMostUsedApps(0).catch((error) => {
			console.error('[+page.svelte] Error fetching most used apps:', error);
		});

		// Initialize app health status to filter apps based on health (non-blocking)
		// This ensures only healthy apps are shown in the app store
		const { initializeAppHealth } = await import('@repo/ui');
		initializeAppHealth().catch((error) => {
			console.error('[+page.svelte] Error initializing app health:', error);
		});

		// Load welcome chat for non-authenticated users (instant load)
		// Use the actual DEMO_CHATS data to ensure all fields (including follow_up_suggestions) are present
		// CRITICAL: Wait for activeChat component to be ready before loading chat
		// FIXED: Improved retry mechanism - loads welcome chat regardless of Chats.svelte mount state
		// This ensures welcome chat loads on both large screens (when Chats mounts) and small screens (when Chats doesn't mount)
		// On mobile, Chats.svelte doesn't mount when sidebar is closed, so this is the primary loading path
		// CRITICAL: Only load welcome chat if:
		// 1. No hash in URL (hash chat will be loaded after sync)
		// 2. User is not authenticated (auth users get new chat window as default)
		// 3. No last opened chat will be loaded (for tab reloads)
		// 4. No deep link was processed (settings, embed, signup, etc.)
		// Use originalHashChatId and deepLinkProcessed flags (read before anything could modify hash)
		const shouldLoadWelcomeChat = false; // DISABLED: All chat loading now handled by deep link system

		if (shouldLoadWelcomeChat) {
			console.debug('[+page.svelte] [NON-AUTH] Starting welcome chat loading logic...');
			// Retry mechanism to wait for activeChat component to bind
			const loadWelcomeChat = async (retries = 20): Promise<void> => {
				// CRITICAL: Check original hash (not current hash which might have been modified)
				// If original hash exists or any deep link was processed, don't load welcome chat
				if (originalHashChatId || deepLinkProcessed) {
					console.debug(
						'[+page.svelte] [NON-AUTH] Hash/deep link detected, aborting welcome chat loading',
						{
							originalHashChatId,
							deepLinkProcessed
						}
					);
					return;
				}

				const sidebarOpen = $panelState.isActivityHistoryOpen;
				const storeChatId = $activeChatStore;

				console.debug('[+page.svelte] [NON-AUTH] loadWelcomeChat attempt:', {
					retriesLeft: retries,
					sidebarOpen,
					storeChatId,
					activeChatReady: !!activeChat
				});

				// Only skip loading if:
				// 1. Sidebar is open (Chats.svelte is mounted and might have already loaded it)
				// 2. Store indicates welcome chat is selected
				// 3. ActiveChat component is ready
				// Otherwise, always load to ensure it works on mobile where Chats.svelte doesn't mount
				if (sidebarOpen && storeChatId === 'demo-for-everyone' && activeChat) {
					console.debug(
						'[+page.svelte] [NON-AUTH] Welcome chat already selected by Chats.svelte (sidebar open), skipping duplicate load'
					);
					return;
				}

				if (activeChat) {
					console.debug('[+page.svelte] [NON-AUTH] Loading welcome demo chat (instant)');
					const { DEMO_CHATS, convertDemoChatToChat, translateDemoChat } = await import('@repo/ui');
					const welcomeDemo = DEMO_CHATS.find((chat) => chat.chat_id === 'demo-for-everyone');
					if (welcomeDemo) {
						// Translate the demo chat to the user's locale
						const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
						const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
						activeChatStore.setActiveChat('demo-for-everyone');
						activeChat.loadChat(welcomeChat);
						console.debug('[+page.svelte] [NON-AUTH] ✅ Welcome chat loaded successfully');
					} else {
						console.error('[+page.svelte] [NON-AUTH] ⚠️ Welcome demo chat not found in DEMO_CHATS');
					}
				} else if (retries > 0) {
					// Wait a bit longer on first few retries, then shorter waits
					const delay = retries > 10 ? 50 : 100;
					console.debug(
						`[+page.svelte] [NON-AUTH] activeChat not ready, retrying in ${delay}ms (${retries} retries left)`
					);
					await new Promise((resolve) => setTimeout(resolve, delay));
					return loadWelcomeChat(retries - 1);
				} else {
					console.warn(
						'[+page.svelte] [NON-AUTH] ⚠️ Failed to load welcome chat - activeChat not available after retries'
					);
				}
			};

			// Start loading immediately, will retry if needed (non-blocking)
			// This ensures welcome chat loads on small screens where Chats.svelte doesn't mount
			// On large screens, this will load it if Chats.svelte hasn't already done so
			loadWelcomeChat().catch((error) => {
				console.error('[+page.svelte] [NON-AUTH] Error loading welcome chat:', error);
			});
		} else if (!isAuth && (originalHashChatId || deepLinkProcessed)) {
			console.debug(
				'[+page.svelte] [NON-AUTH] Skipping welcome chat load - hash/deep link has priority',
				{
					originalHashChatId,
					deepLinkProcessed
				}
			);
		}

		// INSTANT LOAD: Check if last opened chat is already in IndexedDB (non-blocking)
		// This provides instant load on page reload without waiting for sync
		// CRITICAL: On tab reload, load from IndexedDB (not server state) to prevent sudden chat switches
		// On login, server state will be used (via handleSyncCompleteAndLoadChat)
		// CRITICAL: URL hash chat has priority - skip last opened chat if hash is present or deep link processed
		// Use originalHashChatId and deepLinkProcessed flags (read before anything could modify it)
		if ($authStore.isAuthenticated && dbInitPromise && !originalHashChatId && !deepLinkProcessed) {
			// Only load last opened chat if we don't have a chat hash
			dbInitPromise.then(async () => {
				// Double-check original hash still applies (shouldn't change, but be safe)
				if (originalHashChatId || deepLinkProcessed) {
					console.debug(
						'[+page.svelte] [TAB RELOAD] Hash/deep link detected during instant load, aborting last opened chat load',
						{
							originalHashChatId,
							deepLinkProcessed
						}
					);
					return;
				}
				// Load last_opened from IndexedDB (local state) instead of server state
				// This prevents the sudden switch when server sync completes after tab reload
				const { userDB } = await import('@repo/ui');
				const localProfile = await userDB.getUserProfile();
				const lastOpenedChatId = localProfile?.last_opened;

				if (!lastOpenedChatId) {
					console.debug(
						'[+page.svelte] [TAB RELOAD] No last opened chat in IndexedDB, will wait for sync or use server state on login'
					);
					return;
				}

				// Handle "new chat window" case
				if (lastOpenedChatId === '/chat/new' || lastOpenedChatId === 'new') {
					console.debug(
						'[+page.svelte] [TAB RELOAD] Last opened was new chat window, clearing active chat'
					);
					// Clear active chat to show new chat window
					// The ActiveChat component will show the new chat interface when no chat is selected
					activeChatStore.clearActiveChat();
					phasedSyncState.markSyncCompleted();
					return;
				}

				// Handle real chat ID
				if (activeChat) {
					console.debug(
						'[+page.svelte] [TAB RELOAD] Checking if last opened chat is already in IndexedDB:',
						lastOpenedChatId
					);
					const lastChat = await chatDB.getChat(lastOpenedChatId);
					if (lastChat) {
						// SECURITY: Don't load hidden chats on page reload - they require passcode to unlock
						// Check if chat is a hidden candidate (can't decrypt with master key)
						const chatWithHidden = lastChat as Chat & {
							is_hidden_candidate?: boolean;
							is_hidden?: boolean;
						};
						if (chatWithHidden.is_hidden_candidate || chatWithHidden.is_hidden) {
							console.debug(
								'[+page.svelte] [TAB RELOAD] Last opened chat is hidden, skipping load (requires passcode)'
							);
							// Clear last_opened to prevent trying to load it again
							await userDB.updateUserData({ last_opened: '/chat/new' });
							activeChatStore.clearActiveChat();
							phasedSyncState.markSyncCompleted();
							return;
						}

						console.debug(
							'[+page.svelte] ✅ INSTANT LOAD: Last opened chat found in IndexedDB (tab reload), loading immediately'
						);
						activeChatStore.setActiveChat(lastOpenedChatId);
						activeChat.loadChat(lastChat);
						// Mark sync as completed since we already have data
						phasedSyncState.markSyncCompleted();
						console.debug(
							'[+page.svelte] ✅ Chat loaded instantly from IndexedDB cache (tab reload)'
						);
					} else {
						console.debug(
							'[+page.svelte] Last opened chat not in IndexedDB yet, will wait for sync'
						);
					}
				}
			});
		}

		// Check if we need to start phased sync manually
		// (it might have already started automatically during initialize())
		if (!$phasedSyncState.initialSyncCompleted && $authStore.isAuthenticated) {
			if ($websocketStatus.status === 'connected') {
				console.debug(
					'[+page.svelte] WebSocket already connected, checking if sync needs to be started...'
				);
				// Sync might have already started automatically, so we don't force start it again
			} else {
				console.debug(
					'[+page.svelte] Waiting for WebSocket connection before starting phased sync...'
				);
				// Listen for WebSocket connection to start syncing
				const unsubscribeWS = websocketStatus.subscribe((wsState: { status: string }) => {
					if (
						wsState.status === 'connected' &&
						$authStore.isAuthenticated &&
						!$phasedSyncState.initialSyncCompleted
					) {
						console.debug('[+page.svelte] WebSocket connected, sync will start automatically');
						unsubscribeWS(); // Unsubscribe after detecting connection
					}
				});
			}
		} else if (!$authStore.isAuthenticated) {
			console.debug('[+page.svelte] Skipping phased sync - user not authenticated');
			// Note: Sync already marked as completed at the start of onMount() for non-auth users
			// Note: Welcome chat already loaded from SSR data (instant, no delay)
		} else {
			console.debug('[+page.svelte] Skipping phased sync - already completed in this session');

			// If sync already completed but we're just mounting (e.g., after page reload),
			// check if we should load the last opened chat from IndexedDB (not server state)
			// This prevents sudden chat switches when already logged in
			// PRIORITY: URL hash chat has priority over last opened chat
			// EXCEPTION: If hash is settings, we load settings first, then last_opened chat after
			if (activeChat) {
				// Check if original URL hash contains a chat ID (has priority)
				// Use originalHashChatId (read before anything could modify it)
				if (originalHashChatId) {
					console.debug(
						'[+page.svelte] [TAB RELOAD] Original URL hash contains chat ID, loading hash chat (hash has priority):',
						originalHashChatId
					);
					// Load the hash chat instead of last opened chat
					isProcessingInitialHash = true;
					await handleChatDeepLink(originalHashChatId);
					isProcessingInitialHash = false;
				} else {
					// Check if hash is settings - if so, we already processed it, now load last_opened chat
					const currentHash = browser ? window.location.hash : '';
					const { parseDeepLink } = await import('@repo/ui');
					const parsed = currentHash ? parseDeepLink(currentHash) : null;
					const isSettingsHash = parsed?.type === 'settings';

					// If hash is settings, we already processed it above, now load last_opened chat
					// If no hash or hash is not settings, check if we should load last_opened chat
					if (!currentHash || isSettingsHash) {
						try {
							// Load from IndexedDB (local state) instead of server state
							const { userDB } = await import('@repo/ui');
							const localProfile = await userDB.getUserProfile();
							const lastOpenedChatId = localProfile?.last_opened;

							// Skip if last_opened is a signup step (already handled with priority 1)
							if (lastOpenedChatId && isSignupPath(lastOpenedChatId)) {
								console.debug(
									'[+page.svelte] [TAB RELOAD] Skipping last_opened chat - it is a signup step (already handled)'
								);
								return;
							}

							if (!lastOpenedChatId) {
								return;
							}

							// Handle "new chat window" case
							if (lastOpenedChatId === '/chat/new' || lastOpenedChatId === 'new') {
								console.debug(
									'[+page.svelte] [TAB RELOAD] Last opened was new chat window, clearing active chat'
								);
								// Clear active chat to show new chat window
								// The ActiveChat component will show the new chat interface when no chat is selected
								activeChatStore.clearActiveChat();
								return;
							}

							// Handle real chat ID
							const lastChat = await chatDB.getChat(lastOpenedChatId);
							if (lastChat) {
								if (isSettingsHash) {
									console.debug(
										'[+page.svelte] [PRIORITY 3] Loading last_opened chat after settings hash:',
										lastOpenedChatId
									);
								} else {
									console.debug(
										'[+page.svelte] [TAB RELOAD] Sync already complete, loading last opened chat from IndexedDB:',
										lastOpenedChatId
									);
								}
								activeChatStore.setActiveChat(lastOpenedChatId);
								activeChat.loadChat(lastChat);
							}
						} catch (error) {
							console.error('[+page.svelte] Error loading last opened chat from IndexedDB:', error);
						}
					}
				}
			}
		}

		// Clear signup hash after processing (if it was present) to keep URL clean
		// (similar to how chat deep links are cleared after loading)
		if (hasSignupHash) {
			replaceState(window.location.pathname + window.location.search, {});
		}

		// Handle other deep links using unified handler (settings, embed, signup)
		// Note: Chat deep links are already processed at the very start of onMount
		// Only process non-chat deep links here
		if (window.location.hash && !originalHashChatId) {
			const handlers = createDeepLinkHandlers();
			await processDeepLink(window.location.hash, handlers);
		}

		// Remove initial load state after a small delay
		setTimeout(() => {
			console.debug('[+page.svelte] setTimeout for isInitialLoad finished');
			isInitialLoad = false;
		}, 100);

		// Listen for hash changes (e.g., user pastes a new URL with different chat_id)
		window.addEventListener('hashchange', handleHashChange);

		// Listen for pending deep link processing after successful login
		// This handles cases where user opened a deep link while not authenticated
		const pendingDeepLinkHandlerWrapper = (event: Event) => {
			if (
				event instanceof CustomEvent &&
				event.detail &&
				typeof event.detail === 'object' &&
				'hash' in event.detail
			) {
				handlePendingDeepLink(event as CustomEvent<{ hash: string }>);
			}
		};
		pendingDeepLinkHandler = pendingDeepLinkHandlerWrapper;
		window.addEventListener('processPendingDeepLink', pendingDeepLinkHandlerWrapper);

		console.debug('[+page.svelte] onMount finished');
	});

	// Cleanup function for onDestroy
	onDestroy(() => {
		if (handleWebSocketAuthError) {
			webSocketService.removeEventListener('authError', handleWebSocketAuthError);
		}
		// Unregister admin status update handler
		if (handleAdminStatusUpdate) {
			webSocketService.off('user_admin_status_updated', handleAdminStatusUpdate);
		}
		// Only unregister payment handlers if they were registered
		if (!wasInSignupProcessAtMount && handlePaymentCompleted && handlePaymentFailed) {
			webSocketService.off('payment_completed', handlePaymentCompleted);
			webSocketService.off('payment_failed', handlePaymentFailed);
		}
		// Remove pending deep link event listener
		if (pendingDeepLinkHandler) {
			window.removeEventListener('processPendingDeepLink', pendingDeepLinkHandler);
		}
		// Note: hashchange, visibilitychange, pagehide, and beforeunload handlers are cleaned up automatically on page unload
	});

	/**
	 * Load demo-for-everyone chat for non-authenticated users
	 * CRITICAL: Check for existing sessionStorage drafts first - if user has unsaved work,
	 * we should restore their most recent draft instead of overwriting with the demo chat.
	 */
	async function loadDemoWelcomeChat() {
		console.debug('[+page.svelte] loadDemoWelcomeChat called for non-authenticated user');

		// CRITICAL: Check if user has any sessionStorage drafts (new chat drafts)
		// If so, load the most recent one instead of demo-for-everyone
		const draftChatIds = getAllDraftChatIdsWithDrafts();
		if (draftChatIds.length > 0) {
			// User has unsaved drafts - load the most recent one
			// The draft IDs are ordered by when they were added, so the last one is most recent
			const mostRecentDraftId = draftChatIds[draftChatIds.length - 1];
			const draftContent = loadSessionStorageDraft(mostRecentDraftId);

			if (draftContent) {
				console.debug(
					`[+page.svelte] Found sessionStorage draft for non-auth user, restoring draft chat: ${mostRecentDraftId}`
				);

				// Create a virtual chat object for the draft
				const now = Math.floor(Date.now() / 1000);
				const virtualChat: Chat = {
					chat_id: mostRecentDraftId,
					encrypted_title: null,
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

				// Wait for activeChat component to be ready
				const waitForActiveChatForDraft = async (retries = 20): Promise<void> => {
					if (activeChat) {
						// Set the phased sync state to NEW_CHAT_SENTINEL to indicate we're in draft mode
						phasedSyncState.setCurrentActiveChatId(NEW_CHAT_SENTINEL);
						activeChatStore.setActiveChat(mostRecentDraftId);
						activeChat.loadChat(virtualChat);
						console.debug(
							`[+page.svelte] ✅ SessionStorage draft chat loaded successfully: ${mostRecentDraftId}`
						);
						return;
					} else if (retries > 0) {
						await new Promise((resolve) => setTimeout(resolve, 50));
						return waitForActiveChatForDraft(retries - 1);
					} else {
						console.error(
							'[+page.svelte] ⚠️ activeChat not ready after retries - draft may not load'
						);
					}
				};

				await waitForActiveChatForDraft();
				return; // Successfully loaded draft, don't load demo chat
			}
		}

		// No drafts found, load demo-for-everyone as usual
		console.debug('[+page.svelte] No sessionStorage drafts found, loading demo-for-everyone');

		// Wait for activeChat component to be ready
		const waitForActiveChat = async (retries = 20): Promise<void> => {
			if (activeChat) {
				const { DEMO_CHATS, convertDemoChatToChat, translateDemoChat } = await import('@repo/ui');
				const welcomeDemo = DEMO_CHATS.find((chat) => chat.chat_id === 'demo-for-everyone');
				if (welcomeDemo) {
					const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
					const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
					activeChatStore.setActiveChat('demo-for-everyone');
					activeChat.loadChat(welcomeChat);
					console.debug('[+page.svelte] ✅ demo-for-everyone chat loaded successfully');
				}
				return;
			} else if (retries > 0) {
				await new Promise((resolve) => setTimeout(resolve, 50));
				return waitForActiveChat(retries - 1);
			} else {
				console.error(
					'[+page.svelte] ⚠️ activeChat not ready after retries - demo-for-everyone may not load'
				);
			}
		};

		await waitForActiveChat();
	}

	/**
	 * Load last opened chat for authenticated users, or create new chat if none exists
	 */
	async function loadLastOpenedChatOrCreateNew() {
		console.debug(
			'[+page.svelte] Loading last_opened chat or creating new chat for authenticated user'
		);

		const profile = $userProfile;
		if (profile?.last_opened) {
			// Try to load last opened chat from local storage first
			try {
				const { chatDB } = await import('@repo/ui');
				const localChat = await chatDB.getChat(profile.last_opened);

				if (localChat && activeChat) {
					console.debug(
						'[+page.svelte] ✅ Loaded last_opened chat from local storage:',
						profile.last_opened
					);
					activeChatStore.setActiveChat(profile.last_opened);
					activeChat.loadChat(localChat);
					return;
				}
			} catch (error) {
				console.debug('[+page.svelte] Could not load last_opened chat from local storage:', error);
			}
		}

		// Fallback: Wait for sync to complete and load from server, or create new chat
		console.debug(
			'[+page.svelte] No local last_opened chat found, waiting for sync or creating new chat'
		);
		// Note: This will be handled by the sync completion handler
	}

	/**
	 * Create deep link handlers for unified processing
	 */
	function createDeepLinkHandlers(): DeepLinkHandlers {
		return {
			onChat: async (chatId: string, messageId?: string | null) => {
				// Update originalHashChatId to reflect the new hash (important for sync completion handler)
				originalHashChatId = chatId;

				// Mark as processing initial hash load (for hashchange handler)
				isProcessingInitialHash = true;
				deepLinkProcessed = true; // Mark that a deep link was processed

				await handleChatDeepLink(chatId, messageId);

				// Reset flag after processing
				isProcessingInitialHash = false;
			},
			onSettings: (path: string, fullHash: string) => {
				deepLinkProcessed = true; // Mark that a deep link was processed
				processSettingsDeepLink(fullHash);
			},
			onSignup: (step: string) => {
				deepLinkProcessed = true; // Mark that a deep link was processed
				currentSignupStep.set(step);
				isInSignupProcess.set(true);
				loginInterfaceOpen.set(true);
				// Clear the hash after processing to keep URL clean
				replaceState(window.location.pathname + window.location.search, {});
			},
			onEmbed: handleEmbedDeepLink,
			onNoHash: async () => {
				// Handle the case where no hash is present - load appropriate default chat
				const isAuth = $authStore.isAuthenticated;
				console.debug('[+page.svelte] onNoHash: Determining default chat to load', { isAuth });

				if (isAuth) {
					// For authenticated users: try to load last_opened chat, otherwise create new chat
					await loadLastOpenedChatOrCreateNew();
				} else {
					// For non-authenticated users: load demo-for-everyone chat
					await loadDemoWelcomeChat();
				}
			},
			requiresAuthentication,
			isAuthenticated: () => $authStore.isAuthenticated,
			openSettings: () => panelState.openSettings(),
			openLogin: () => loginInterfaceOpen.set(true),
			setSettingsDeepLink: (path: string) => settingsDeepLink.set(path)
		};
	}

	/**
	 * Handle hash changes after page load
	 * Uses unified deep link handler to avoid collisions
	 *
	 * CRITICAL: Ignores programmatic hash updates to prevent infinite loops
	 */
	async function handleHashChange() {
		// Import the check function
		const { isProgrammaticHashUpdate, isProgrammaticEmbedHashUpdate } = await import('@repo/ui');

		// Ignore hash changes that we triggered programmatically (prevents infinite loops)
		if (isProgrammaticHashUpdate() || isProgrammaticEmbedHashUpdate()) {
			console.debug('[+page.svelte] Ignoring programmatic hash update');
			return;
		}

		console.debug('[+page.svelte] Hash changed:', window.location.hash);

		const handlers = createDeepLinkHandlers();
		await processDeepLink(window.location.hash, handlers);
	}

	// Add handler for chatSelected event
	// FIXED: Improved retry mechanism with multiple attempts to ensure chat loads for SEO
	async function handleChatSelected(event: CustomEvent) {
		const selectedChat: Chat = event.detail.chat;
		console.debug('[+page.svelte] Received chatSelected event:', selectedChat.chat_id); // Use chat_id

		// Retry mechanism with multiple attempts to ensure chat loads (critical for SEO)
		const loadChatWithRetry = async (retries = 20): Promise<void> => {
			if (activeChat) {
				console.debug('[+page.svelte] activeChat ready, loading chat:', selectedChat.chat_id);
				activeChat.loadChat(selectedChat);
				console.debug('[+page.svelte] ✅ Successfully called loadChat for:', selectedChat.chat_id);
				return;
			} else if (retries > 0) {
				// Wait a bit longer on first few retries, then shorter waits
				const delay = retries > 10 ? 50 : 100;
				console.debug(
					`[+page.svelte] activeChat not ready yet, retrying in ${delay}ms (${retries} retries left)...`
				);
				await new Promise((resolve) => setTimeout(resolve, delay));
				return loadChatWithRetry(retries - 1);
			} else {
				console.error(
					'[+page.svelte] ⚠️ activeChat ref still not available after all retries - chat may not load for SEO'
				);
			}
		};

		await loadChatWithRetry();

		// Optionally close Activity History on mobile after selection
		// if ($panelState.isMobileView) { // Assuming isMobileView is exposed or checked
		//    panelState.toggleActivityHistory(); // Or a specific close action
		// }
	}

	// Reset the active chat UI when the sidebar reports that a chat was deselected (e.g., after deletion)
	async function handleChatDeselected() {
		if (activeChat?.resetToNewChat) {
			console.debug(
				'[+page.svelte] chatDeselected event received - resetting ActiveChat to new chat state'
			);
			await activeChat.resetToNewChat();
		}
	}
</script>

<!-- SEO meta tags - client-side with translations -->
<svelte:head>
	<title>{seoTitle}</title>
	<meta name="description" content={seoDescription} />
	<meta name="keywords" content={seoKeywords} />

	<!-- hreflang tags for multi-language SEO - generated from single source of truth -->
	{#each LANGUAGE_CODES as lang}
		<link rel="alternate" hreflang={lang} href="https://openmates.org/?lang={lang}" />
	{/each}
	<link rel="alternate" hreflang="x-default" href="https://openmates.org/" />

	<meta property="og:title" content={seoTitle} />
	<meta property="og:description" content={seoDescription} />
	<meta property="og:type" content="website" />
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content={seoTitle} />
	<meta name="twitter:description" content={seoDescription} />
	<link rel="canonical" href="https://openmates.org" />
</svelte:head>

<!-- Removed svelte:window binding for innerWidth -->

<!-- Notification overlay - positioned outside main-content to stay visible when chats menu is open on mobile -->
<div class="notification-container">
	{#each $notificationStore.notifications as notification (notification.id)}
		{#if notification.type === 'chat_message'}
			<ChatMessageNotification {notification} />
		{:else}
			<Notification {notification} />
		{/if}
	{/each}
</div>

<div class="sidebar" class:closed={!$panelState.isActivityHistoryOpen}>
	{#if $panelState.isActivityHistoryOpen}
		<!-- Sidebar content - transition handled by parent sidebar transform -->
		<div class="sidebar-content">
			<Chats on:chatSelected={handleChatSelected} on:chatDeselected={handleChatDeselected} />
		</div>
	{/if}
</div>

<div
	class="main-content"
	class:menu-closed={!$panelState.isActivityHistoryOpen}
	class:initial-load={isInitialLoad}
	class:scrollable={showFooter}
>
	<Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
	<div
		class="chat-container"
		class:menu-open={$panelState.isSettingsOpen}
		class:authenticated={$authStore.isAuthenticated}
		class:signup-process={$isInSignupProcess}
	>
		<div class="chat-wrapper">
			<!-- ActiveChat component - loads welcome chat via JS for PWA -->
			<ActiveChat bind:this={activeChat} />
		</div>
		<div class="settings-wrapper">
			<Settings isLoggedIn={$authStore.isAuthenticated} on:chatSelected={handleChatSelected} />
		</div>
	</div>
</div>

<!-- Login/Signup overlay removed - incomplete feature
     TODO: Implement proper login overlay if needed -->

<style>
	:root {
		--sidebar-width: 325px;
		--sidebar-margin: 10px;
	}
	.sidebar {
		/* Fixed positioning relative to viewport */
		position: fixed;
		left: 0;
		top: 0;
		bottom: 0;

		/* Specified width */
		width: var(--sidebar-width);

		/* Background color */
		background-color: var(--color-grey-20);

		/* Ensure sidebar stays above other content */
		z-index: 10;

		/* Remove scrolling - let internal components handle it */
		overflow: hidden;

		/* Add more pronounced inner shadow on right side for better visibility */
		box-shadow: inset -6px 0 12px -4px rgba(0, 0, 0, 0.25);

		/* Smooth transition for sidebar reveal/hide */
		transition:
			transform 0.3s ease,
			opacity 0.3s ease,
			visibility 0.3s ease;
		transform: translateX(0);
		opacity: 1;
		visibility: visible;
	}

	.sidebar.closed {
		/* Slide sidebar off-screen to the left instead of hiding instantly */
		transform: translateX(-100%);
		opacity: 0;
		visibility: hidden;
	}

	.sidebar-content {
		height: 100%;
		width: 100%;
		overflow: hidden;
	}

	.main-content {
		/* Change from fixed to absolute positioning when in scrollable mode */
		position: fixed;
		left: calc(var(--sidebar-width) + var(--sidebar-margin));
		top: 0;
		right: 0;
		bottom: 0;
		background-color: var(--color-grey-0);
		z-index: 10;
		/* Smooth transitions for width changes (large screens) and slide animations (small screens) */
		transition:
			left 0.3s ease,
			transform 0.3s ease;
	}

	/* Add new scrollable mode styles */
	.main-content.scrollable {
		position: absolute;
		bottom: auto; /* Remove bottom constraint */
		min-height: 100vh; /* Ensure it takes at least full viewport height */
		min-height: 100dvh; /* Ensure it takes at least full viewport height */
		overflow-x: hidden; /* Prevent horizontal scrolling when profile container is absolute */
	}

	.main-content.menu-closed {
		left: var(--sidebar-margin);
	}

	/* For Webkit browsers */
	.main-content::-webkit-scrollbar {
		width: 8px;
	}

	.main-content::-webkit-scrollbar-track {
		background: transparent;
	}

	.main-content::-webkit-scrollbar-thumb {
		background-color: var(--color-grey-40);
		border-radius: 4px;
		border: 2px solid transparent;
	}

	.main-content::-webkit-scrollbar-thumb:hover {
		background-color: var(--color-grey-50);
	}

	.chat-container {
		display: flex;
		flex-direction: row;
		/* Fallback for browsers that don't support dvh */
		height: calc(100vh - 82px);
		/* Modern browsers will use this */
		height: calc(100dvh - 82px);
		gap: 0px;
		padding: 10px;
		padding-right: 20px;
		/* Only apply gap transition on larger screens */
		@media (min-width: 1100px) {
			transition: gap 0.3s ease;
		}
	}

	/* Only apply gap on larger screens */
	@media (min-width: 1100px) {
		.chat-container.menu-open {
			gap: 20px;
		}
	}

	/* Ensure no gap on mobile */
	@media (max-width: 1099px) {
		.chat-container.menu-open {
			gap: 0px;
		}
	}

	.settings-wrapper {
		display: flex;
		align-items: flex-start;
		min-width: fit-content;
	}

	/* Add mobile styles */
	@media (max-width: 600px) {
		.chat-container {
			padding-right: 10px;
			height: calc(100vh - 75px);
			height: calc(100dvh - 75px);
		}
		.sidebar {
			width: 100%;
			/* On mobile, sidebar slides from the left */
			/* transform is handled by .sidebar.closed class */
		}

		.main-content {
			/* Position main content over the sidebar by default */
			left: 0;
			right: 0;
			z-index: 20; /* Higher than sidebar to cover it */
			transform: translateX(0);
			min-height: unset;
			/* Ensure smooth sliding transition on mobile */
			transition: transform 0.3s ease;
		}

		/* figure our css issues related to height */

		/* When menu is open (sidebar visible), slide main content right */
		.main-content:not(.menu-closed) {
			transform: translateX(100%);
		}

		/* When menu is closed, keep main content over sidebar */
		.main-content.menu-closed {
			left: 0;
			transform: translateX(0);
		}

		/* Scrollable mode: disable transform transitions to prevent conflicts */
		.main-content.scrollable {
			transition: none;
			transform: none;
			left: 0;
		}
	}

	.chat-wrapper,
	.settings-wrapper {
		transition: opacity 0.3s ease;
	}

	.chat-wrapper {
		flex: 1;
		display: flex;
		min-width: 0;
	}

	/* Smooth transition for main content */
	.main-content {
		transition:
			left 0.3s ease,
			transform 0.3s ease;
	}

	/* Disable transitions during initial load */
	.main-content.initial-load {
		transition: none;
	}

	/* Notification container - positioned at top of main-content */
	.notification-container {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		z-index: 10000; /* High z-index to appear above all content */
		pointer-events: none; /* Allow clicks to pass through container */
		display: flex;
		flex-direction: column;
		align-items: center;
		padding-top: 20px;
		gap: 10px; /* Space between multiple notifications */
	}

	/* Enable pointer events on notifications themselves */
	.notification-container :global(.notification) {
		pointer-events: auto;
	}
</style>
