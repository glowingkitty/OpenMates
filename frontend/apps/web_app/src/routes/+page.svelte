<script lang="ts">
    import {
        // components
        Chats,
        ActiveChat,
        Header,
        Settings,
        Footer,
        Login,
        Notification,
        // stores
        isInSignupProcess,
        showSignupFooter,
        authStore,
        initialize, // Import initialize directly
        panelState, // Import the new central panel state store
        settingsDeepLink,
        activeChatStore, // Import for deep linking
        phasedSyncState, // Import phased sync state store
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
    } from '@repo/ui';
    import { notificationStore, getKeyFromStorage, text, LANGUAGE_CODES } from '@repo/ui';
    import { checkAndClearMasterKeyOnLoad } from '@repo/ui';
    import { onMount, onDestroy, untrack } from 'svelte';
    import { locale, waitLocale, _, isLoading } from 'svelte-i18n';
    import { get } from 'svelte/store';
    import { browser } from '$app/environment';
    import { i18nLoaded } from '@repo/ui';

    // --- State ---
    let isInitialLoad = $state(true);
    let activeChat = $state<ActiveChat | null>(null); // Fixed: Use $state for Svelte 5
    let isProcessingInitialHash = $state(false); // Track if we're processing initial hash load
    let originalHashChatId: string | null = null; // Store original hash chat ID from URL (read before anything modifies it)
    
    // CRITICAL: Reactive effect to watch for signup state changes
    // This handles cases where user profile loads asynchronously after initialize() completes
    // or when user logs in and signup state needs to be detected
    // Must be at top level (not inside onMount) for Svelte 5
    // Use untrack to prevent infinite loops when setting loginInterfaceOpen
    $effect(() => {
        // Only check if user is authenticated and has a last_opened path
        if ($authStore.isAuthenticated && $userProfile.last_opened && isSignupPath($userProfile.last_opened)) {
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
                    console.debug(`[+page.svelte] [$effect] Set signup step to: ${step} from last_opened: ${$userProfile.last_opened}`);
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
    async function handleChatDeepLink(chatId: string) {
        console.debug(`[+page.svelte] Handling chat deep link for: ${chatId}`);
        
        // CRITICAL: During initial hash load, always process (store might be initialized from hash but chat not loaded)
        // After initial load, skip if chat is already active in store (prevents unnecessary processing)
        if (!isProcessingInitialHash && $activeChatStore === chatId) {
            console.debug(`[+page.svelte] Chat ${chatId} is already active (not initial load), skipping deep link processing`);
            return;
        }
        
        // Update the activeChatStore so the Chats component highlights it when opened
        activeChatStore.setActiveChat(chatId);
        
        // Check if this is a demo or legal chat (public chat)
        const { getPublicChatById, convertDemoChatToChat, translateDemoChat } = await import('@repo/ui');
        const publicChat = getPublicChatById(chatId);
        
        if (publicChat) {
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
                    console.debug(`[+page.svelte] Dispatched globalChatSelected for deep-linked public chat:`, chatId);
                    
                    // Keep the URL hash so users can share/bookmark the chat
                    // The activeChatStore.setActiveChat() call above already updated the hash
                    return;
                } else if (retries > 0) {
                    const delay = retries > 10 ? 50 : 100;
                    await new Promise(resolve => setTimeout(resolve, delay));
                    return loadPublicChat(retries - 1);
                } else {
                    console.error(`[+page.svelte] activeChat component not ready for deep-linked public chat`);
                }
            };
            
            await loadPublicChat();
            return;
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
                        console.debug(`[+page.svelte] Dispatched globalChatSelected for deep-linked chat:`, chat.chat_id);
                        
                        // Keep the URL hash so users can share/bookmark the chat
                        // The activeChatStore.setActiveChat() call above already updated the hash
                        return; // Success - exit
                    } else if (retries > 0) {
                        // If activeChat isn't ready yet, wait a bit and retry
                        const delay = retries > 10 ? 50 : 100;
                        await new Promise(resolve => setTimeout(resolve, delay));
                        return loadChatFromIndexedDB(retries - 1);
                    } else {
                        console.warn(`[+page.svelte] activeChat component not ready for deep link after retries`);
                    }
                } else {
                    // Chat not found in IndexedDB
                    if ($authStore.isAuthenticated) {
                        // For authenticated users, wait for sync to complete
                        console.debug(`[+page.svelte] Chat ${chatId} not found in IndexedDB, waiting for sync...`);
                    } else {
                        // For non-auth users, if chat is not in IndexedDB, it doesn't exist
                        console.warn(`[+page.svelte] Chat ${chatId} not found in IndexedDB (non-auth user)`);
                        activeChatStore.clearActiveChat();
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
            console.debug(`[+page.svelte] Non-auth user - loading shared chat immediately from IndexedDB: ${chatId}`);
            loadChatFromIndexedDB();
        } else {
            // For authenticated users, wait for sync to complete
            const handlePhasedSyncComplete = async () => {
                console.debug(`[+page.svelte] Phased sync complete, attempting to load deep-linked chat: ${chatId}`);
                await loadChatFromIndexedDB();
                // Remove the listener after handling
                chatSyncService.removeEventListener('phasedSyncComplete', handlePhasedSyncComplete as EventListener);
            };
            
            // Register listener for phased sync completion
            chatSyncService.addEventListener('phasedSyncComplete', handlePhasedSyncComplete as EventListener);
            
            // Also try immediately in case sync already completed
            // (e.g., page reload with URL already set)
            setTimeout(handlePhasedSyncComplete, 1000);
        }
    }
    
    /**
     * Handler for sync completion - loads chat based on priority:
     * 1. URL hash chat (if present)
     * 2. Last opened chat (if no hash)
     * 3. Default (demo-welcome for non-auth, new chat for auth)
     * 
     * This implements the "Auto-Open Logic" from sync.md Phase 1 requirements
     * 
     * IMPORTANT: This function is only called on login (when sync completes after authentication).
     * On tab reload, we load from IndexedDB directly (see instant load logic below).
     */
    async function handleSyncCompleteAndLoadChat() {
        console.debug('[+page.svelte] Sync event received, checking what chat to load...');
        
        // PRIORITY 1: URL hash chat has absolute priority
        // Use originalHashChatId if available (stored at start of onMount), otherwise check current hash
        // This prevents issues where welcome chat loading overwrote the hash
        let hashChatIdToLoad: string | null = null;
        if (typeof originalHashChatId !== 'undefined' && originalHashChatId !== null) {
            // Use original hash (read before anything could modify it)
            hashChatIdToLoad = originalHashChatId;
            console.debug('[+page.svelte] Using ORIGINAL hash chat ID from start of onMount:', hashChatIdToLoad);
        } else if (browser) {
            // Fallback: check current hash (might have been modified)
            hashChatIdToLoad = window.location.hash.startsWith('#chat-id=')
                ? window.location.hash.substring('#chat-id='.length)
                : window.location.hash.startsWith('#chat_id=')
                ? window.location.hash.substring('#chat_id='.length)
                : null;
            console.debug('[+page.svelte] Using CURRENT hash chat ID (fallback):', hashChatIdToLoad);
        }
        
        if (hashChatIdToLoad) {
            console.debug('[+page.svelte] URL hash contains chat ID, loading hash chat (priority 1):', hashChatIdToLoad);
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
     * OPTIMIZATION: Check if chat is already loaded to avoid duplicate loads
     * Only loads if chat exists in IndexedDB but isn't currently displayed
     */
    async function handleSyncCompleteAndLoadLastChat() {
        console.debug('[+page.svelte] Loading last opened chat (no hash in URL)...');
        
        // On login, use server state (from userProfile which was synced from server)
        // This ensures new devices get the correct last opened chat from server
        const lastOpenedChatId = $userProfile.last_opened;
        
        if (!lastOpenedChatId) {
            console.debug('[+page.svelte] No last opened chat in user profile (from server) - will load default chat');
            // Don't return - continue to load default chat below
        }
        
        // Try to load last opened chat if it exists
        if (lastOpenedChatId) {
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
                    console.debug('[+page.svelte] ✅ Loading last opened chat from sync (login):', lastOpenedChatId);
                    
                    // Update the active chat store so the sidebar highlights it when opened
                    activeChatStore.setActiveChat(lastOpenedChatId);
                    
                    // Load the chat in the UI
                    activeChat.loadChat(lastChat);
                    
                    console.debug('[+page.svelte] ✅ Successfully loaded last opened chat from sync (login)');
                    return; // Successfully loaded, don't load default
                } else if (!lastChat) {
                    console.debug('[+page.svelte] Last opened chat not yet in IndexedDB, will try again after next sync phase');
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
        // For non-authenticated users: demo-welcome
        // For authenticated users: new chat window
        if (!$activeChatStore && activeChat) {
            if (!$authStore.isAuthenticated) {
                // Non-auth: load demo-welcome
                console.debug('[+page.svelte] No last opened chat, loading demo-welcome (default for non-auth)');
                const { DEMO_CHATS, convertDemoChatToChat, translateDemoChat } = await import('@repo/ui');
                const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
                if (welcomeDemo) {
                    const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
                    const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
                    activeChatStore.setActiveChat('demo-welcome');
                    activeChat.loadChat(welcomeChat);
                }
            } else {
                // Auth: show new chat window (clear active chat)
                console.debug('[+page.svelte] No last opened chat, showing new chat window (default for auth)');
                activeChatStore.clearActiveChat();
            }
        }
    }
    
	// Login state management happens through components now
	// Login overlay feature was removed as incomplete implementation

	// --- Lifecycle ---
	// Define handlers outside onMount so they're accessible for cleanup
	let handleWebSocketAuthError: (() => Promise<void>) | null = null;
	let handlePaymentCompleted: ((payload: { order_id: string, credits_purchased: number, current_credits: number }) => void) | null = null;
	let handlePaymentFailed: ((payload: { order_id: string, message: string }) => void) | null = null;
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
			'main' // Main settings page
		];
		
		// Check if path starts with any public setting
		const normalizedPath = settingsPath.startsWith('/') ? settingsPath.substring(1) : settingsPath;
		const firstSegment = normalizedPath.split('/')[0];
		
		// Map aliases
		const mappedPath = firstSegment === 'appstore' ? 'app_store' : firstSegment;
		
		// If it's a public setting, no authentication required
		if (publicSettings.includes(mappedPath) || normalizedPath === '') {
			return false;
		}
		
		// All other settings require authentication (billing, account, security, etc.)
		return true;
	}
	
	/**
	 * Process settings deep link - extracted to reusable function
	 * Handles navigation to settings pages based on hash
	 * @param hash The hash string (e.g., '#settings/billing/invoices/.../refund')
	 */
	function processSettingsDeepLink(hash: string) {
		console.debug(`[+page.svelte] Processing settings deep link: ${hash}`);
		
		panelState.openSettings();
		const settingsPath = hash.substring('#settings'.length);
		
		// Check if this is a refund deep link (e.g., #settings/billing/invoices/{invoice_id}/refund)
		// For refund deep links, we navigate to billing/invoices but keep the hash for SettingsInvoices to process
		const refundMatch = settingsPath.match(/^\/billing\/invoices\/[^\/]+\/refund$/);
		
		if (refundMatch) {
			// This is a refund deep link - navigate to billing/invoices
			// SettingsInvoices will handle the refund processing
			console.debug(`[+page.svelte] Refund deep link detected: ${hash}`);
			settingsDeepLink.set('billing/invoices');
			// Don't clear the hash - SettingsInvoices needs it to process the refund
			// But we'll clear it after SettingsInvoices processes it
		} else if (settingsPath.startsWith('/')) {
			// Handle paths like #settings/appstore -> app_store
			let path = settingsPath.substring(1); // Remove leading slash
			// Map common aliases to actual settings paths
			if (path === 'appstore') {
				path = 'app_store';
			}
			settingsDeepLink.set(path);
			
			// Clear the hash after processing to keep URL clean
			// (similar to how signup and chat deep links are cleared)
			window.history.replaceState({}, '', window.location.pathname + window.location.search);
		} else if (settingsPath === '') {
			 settingsDeepLink.set('main'); // Default to main settings if just #settings
			 
			 // Clear the hash after processing
			 window.history.replaceState({}, '', window.location.pathname + window.location.search);
		} else {
			 // Handle invalid settings path?
			 console.warn(`[+page.svelte] Invalid settings deep link hash: ${hash}`);
			 settingsDeepLink.set('main'); // Default to main on invalid hash
			 
			 // Clear the hash after processing
			 window.history.replaceState({}, '', window.location.pathname + window.location.search);
		}
	}
	
	/**
	 * Handle pending deep link processing after successful login
	 * This handles cases where user opened a deep link while not authenticated
	 */
	function handlePendingDeepLink(event: CustomEvent<{ hash: string }>) {
		const hash = event.detail.hash;
		console.debug(`[+page.svelte] Processing pending deep link: ${hash}`);
		
		if (hash.startsWith('#settings')) {
			// Process settings deep link now that user is authenticated
			processSettingsDeepLink(hash);
		} else if (hash.startsWith('#chat_id=') || hash.startsWith('#chat-id=')) {
			// Process chat deep link
			const chatId = hash.startsWith('#chat_id=') 
				? hash.substring(9) // Remove '#chat_id=' prefix
				: hash.substring(9); // Remove '#chat-id=' prefix
			handleChatDeepLink(chatId);
		}
		// Note: signup deep links don't require authentication, so they're handled immediately
	}
	
	onMount(async () => {
		console.debug('[+page.svelte] onMount started');
		
		// CRITICAL: Read and store the ORIGINAL hash value BEFORE anything can modify it
		// This ensures we can check for hash chat even if welcome chat loading overwrites the hash
		const originalHash = browser ? window.location.hash : '';
		originalHashChatId = originalHash.startsWith('#chat-id=') || originalHash.startsWith('#chat_id=')
			? (originalHash.startsWith('#chat-id=') 
				? originalHash.substring('#chat-id='.length)
				: originalHash.substring('#chat_id='.length))
			: null;
		console.debug('[+page.svelte] [INIT] Original hash from URL:', originalHash, 'chatId:', originalHashChatId);
		
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
				window.history.replaceState({}, '', newUrl.toString());
			}
		}
		
		// SECURITY: Check if master key should be cleared (if stayLoggedIn was false)
		// This must happen BEFORE loading user data to ensure key is cleared if needed
		// This handles cases where user closed tab/browser with stayLoggedIn=false
		await checkAndClearMasterKeyOnLoad();
		
		// CRITICAL OFFLINE-FIRST: Load local user data FIRST to set optimistic auth state
		// This ensures user appears logged in immediately if they have local data, even if server is unreachable
		console.debug('[+page.svelte] Loading local user data optimistically (offline-first)...');
		await loadUserProfileFromDB();
		
		// Check if we have local authentication data (master key + user profile)
		const masterKey = await getKeyFromStorage();
		const localProfile = $userProfile;
		const hasLocalAuthData = masterKey && localProfile && localProfile.username;
		
		if (hasLocalAuthData) {
			// User has local data - optimistically set as authenticated
			console.debug('[+page.svelte] ✅ Local auth data found - setting optimistic auth state');
			authStore.update(state => ({
				...state,
				isAuthenticated: true,
				isInitialized: true // Mark as initialized so UI updates immediately
			}));
		} else {
			console.debug('[+page.svelte] No local auth data found - user will remain unauthenticated');
		}
		
		// Now check auth state after optimistic loading
		const isAuth = $authStore.isAuthenticated;
		
		// FALLBACK: Cleanup shared chats on page load (if unload events didn't fire)
		// This handles cases where browser crashed, force quit, or events didn't fire
		// Only run for non-authenticated users (authenticated users' chats should persist)
		if (!isAuth) {
			try {
				// Check if this is a new session (sessionStorage doesn't have shared_chats)
				// sessionStorage is cleared when tab/window closes, so empty = new session
				const hasSharedChatsInSession = sessionStorage.getItem('shared_chats') !== null;
				
				if (!hasSharedChatsInSession) {
					// This is a new session - cleanup any leftover shared chats from previous session
					console.debug('[+page.svelte] New session detected - cleaning up any leftover shared chats from IndexedDB');
					
					try {
						// Initialize DB if needed (non-blocking, may fail if DB is unavailable)
						await chatDB.init();
						
						// Get all chats from IndexedDB
						const allChats = await chatDB.getAllChats();
						
						// Import isPublicChat helper
						const { isPublicChat } = await import('@repo/ui');
						
						// Delete all chats that aren't demo/legal chats (these are leftover shared chats)
						let deletedCount = 0;
						for (const chat of allChats) {
							if (!isPublicChat(chat.chat_id)) {
								try {
									await chatDB.deleteChat(chat.chat_id);
									deletedCount++;
									console.debug('[+page.svelte] Deleted leftover shared chat:', chat.chat_id);
								} catch (error) {
									console.warn('[+page.svelte] Error deleting leftover shared chat:', chat.chat_id, error);
								}
							}
						}
						
						if (deletedCount > 0) {
							console.info(`[+page.svelte] Cleaned up ${deletedCount} leftover shared chat(s) from previous session`);
						}
					} catch (dbError: any) {
						// If DB is being deleted (e.g., during logout) or unavailable, skip cleanup
						if (dbError?.message?.includes('being deleted') || dbError?.message?.includes('cannot be initialized')) {
							console.debug('[+page.svelte] Database unavailable during shared chat cleanup - skipping (likely during logout)');
						} else {
							console.warn('[+page.svelte] Error accessing database during shared chat cleanup:', dbError);
						}
					}
				} else {
					// Session has shared chats - they're still valid, don't delete
					console.debug('[+page.svelte] Existing session with shared chats - skipping cleanup');
				}
			} catch (error) {
				console.warn('[+page.svelte] Error during shared chat cleanup on load:', error);
				// Don't fail the whole app if cleanup fails
			}
		}
		
		// CRITICAL: Check for signup hash in URL BEFORE initialize() to ensure hash-based signup state takes precedence
		// This ensures signup flow opens immediately on page reload if URL has #signup/ hash
		// The hash takes precedence over last_opened from IndexedDB and checkAuth() logic
		let hasSignupHash = false;
		if (window.location.hash.startsWith('#signup/')) {
			hasSignupHash = true;
			// Handle signup deep linking - open login interface and set signup step
			console.debug(`[+page.svelte] Found signup deep link in URL (before initialize): ${window.location.hash}`);
			
			// Extract step from hash (e.g., #signup/credits -> credits)
			const signupHash = window.location.hash.substring(1); // Remove leading #
			const step = getStepFromPath(signupHash);
			
			console.debug(`[+page.svelte] Setting signup step to: ${step} from hash: ${window.location.hash}`);
			
			// Set signup step and open login interface BEFORE initialize() runs
			// This ensures checkAuth() won't override these values
			currentSignupStep.set(step);
			isInSignupProcess.set(true);
			loginInterfaceOpen.set(true);
		}
		
		// CRITICAL FOR NON-AUTH: Mark sync completed IMMEDIATELY to prevent "Loading chats..." flash
		// Must happen before initialize() because it checks $phasedSyncState.initialSyncCompleted
		if (!isAuth) {
			phasedSyncState.markSyncCompleted();
			console.debug('[+page.svelte] [NON-AUTH] Pre-marked sync as completed to prevent loading flash');
		}

		// CRITICAL: Start IndexedDB initialization IMMEDIATELY in parallel (non-blocking)
		// This ensures DB is ready when sync data arrives, but doesn't block anything
		// Note: Demo chats are now loaded from static bundle, not IndexedDB
		let dbInitPromise: Promise<void> | null = null;
		if (isAuth) {
			console.debug('[+page.svelte] Starting IndexedDB initialization (non-blocking)...');
			dbInitPromise = chatDB.init().then(() => {
				console.debug('[+page.svelte] ✅ IndexedDB initialized and ready');
			}).catch(error => {
				console.error('[+page.svelte] ❌ IndexedDB initialization failed:', error);
			});
		}
		
		// Listen for WebSocket auth errors and trigger logout
		// This handles cases where the session expires and WebSocket connection is rejected with 403
		handleWebSocketAuthError = async () => {
			console.info('[+page.svelte] WebSocket auth error detected - session expired or invalid token. Logging out user.');
			
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
		webSocketService.addEventListener('authError', handleWebSocketAuthError as EventListener);
		console.debug('[+page.svelte] Registered WebSocket auth error listener');
		
		// Listen for payment completion notifications via WebSocket
		// This handles cases where payment completes after user has moved on from signup flow
		handlePaymentCompleted = (payload: { order_id: string, credits_purchased: number, current_credits: number }) => {
			console.debug('[+page.svelte] Received payment_completed notification via WebSocket:', payload);
			
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
				import('@repo/ui').then(({ updateProfile }) => {
					updateProfile({ credits: payload.current_credits });
				}).catch(error => {
					console.warn('[+page.svelte] Failed to import updateProfile:', error);
				});
			}
		};
		
		// Listen for payment failure notifications via WebSocket
		// This handles cases where payment fails minutes after user has moved on from signup flow
		handlePaymentFailed = (payload: { order_id: string, message: string }) => {
			console.debug('[+page.svelte] Received payment_failed notification via WebSocket:', payload);
			// Show error notification popup (using Notification.svelte component)
			notificationStore.error(
				payload.message || 'Payment failed. Please try again or use a different payment method.',
				10000 // Show for 10 seconds since this is important
			);
		};
		
		// Register WebSocket listeners for payment notifications
		// NOTE: Only register payment handlers if NOT in signup mode, as Payment.svelte already handles them during signup
		// This prevents duplicate handler registrations during signup flow
		// Store the signup state at registration time for proper cleanup
		wasInSignupProcessAtMount = get(isInSignupProcess);
		
		if (!wasInSignupProcessAtMount) {
			webSocketService.on('payment_completed', handlePaymentCompleted);
			webSocketService.on('payment_failed', handlePaymentFailed);
			console.debug('[+page.svelte] Registered WebSocket payment notification listeners');
		} else {
			console.debug('[+page.svelte] Skipping payment handler registration during signup');
		}
		
		// CRITICAL: Setup cleanup for shared chats on session close (non-authenticated users only)
		// Shared chats are stored in IndexedDB but should be deleted when the session ends
		// This ensures shared chats don't persist long-term for non-authenticated users
		// IMPORTANT: Only delete on actual tab close, not during navigation
		const cleanupSharedChats = async () => {
			// Only cleanup if user is not authenticated
			if (!$authStore.isAuthenticated) {
				try {
					const sharedChatIds = JSON.parse(sessionStorage.getItem('shared_chats') || '[]');
					if (sharedChatIds.length > 0) {
						console.debug('[+page.svelte] Cleaning up shared chats on session close:', sharedChatIds);
						
						// Delete chats from IndexedDB
						for (const chatId of sharedChatIds) {
							try {
								await chatDB.deleteChat(chatId);
								console.debug('[+page.svelte] Deleted shared chat from IndexedDB:', chatId);
							} catch (error) {
								console.warn('[+page.svelte] Error deleting shared chat:', chatId, error);
							}
						}
						
						// Clear sessionStorage tracking
						sessionStorage.removeItem('shared_chats');
						console.debug('[+page.svelte] Cleaned up shared chats on session close');
					}
				} catch (error) {
					console.warn('[+page.svelte] Error cleaning up shared chats:', error);
				}
			}
		};
		
		// Use pagehide for better mobile browser support (fires on tab close, browser close, navigation)
		// This is more reliable than beforeunload for detecting actual tab close
		// The 'persisted' property tells us if the page is being cached (navigation) or unloaded (tab close)
		window.addEventListener('pagehide', (event) => {
			// Check if this is a navigation (persisted) or actual unload
			// If persisted is true, the page is being cached (e.g., back/forward navigation, SPA navigation)
			// If persisted is false, the page is being unloaded (tab close, browser close)
			if (!event.persisted) {
				// Page is being unloaded (not cached) - this is actual tab/browser close
				// Use non-blocking approach - initiate cleanup (may not complete if page closes immediately)
				cleanupSharedChats().catch((error) => {
					// Ignore errors - cleanup will happen on next page load if needed
					console.debug('[+page.svelte] Shared chat cleanup on unload incomplete (will be handled on next page load)');
				});
			} else {
				console.debug('[+page.svelte] Page is being cached (navigation), not closing. Skipping cleanup.');
			}
		});
		
		// Note: We primarily rely on pagehide.persisted for accurate detection
		// Most modern browsers support this, so beforeunload is rarely needed
		// If a browser doesn't support pagehide.persisted, cleanup will happen on next page load anyway
		
		console.debug('[+page.svelte] Registered shared chat cleanup handlers');

		// CRITICAL: Register sync event listeners FIRST, before initialization
		// chatSyncService can auto-start sync when WebSocket connects during initialize()
		// If we register listeners after, we'll miss the syncComplete event
		if (isAuth || !$phasedSyncState.initialSyncCompleted) {
			console.debug('[+page.svelte] Registering sync event listeners...');
			
			// Register listener for sync completion to auto-open chat based on priority
			// Priority: hash chat > last opened chat > default
			const handleSyncComplete = (async () => {
				console.debug('[+page.svelte] Sync complete event received, marking as completed');
				phasedSyncState.markSyncCompleted(); // Mark immediately on any sync complete event
				await handleSyncCompleteAndLoadChat();
			}) as EventListener;
			
			// Register listeners for phased sync completion events only
			// Use explicit phase events for UX timing; no legacy sync events
			chatSyncService.addEventListener('phasedSyncComplete', handleSyncComplete);
			chatSyncService.addEventListener('phase_3_last_100_chats_ready', handleSyncComplete);

			// Also react to Phase 1 and Phase 2 events to load last chat ASAP (don't wait for full sync)
			// Phase 1: last opened chat should be ready
			chatSyncService.addEventListener('phase_1_last_chat_ready', handleSyncComplete);
			// Phase 2: in case Phase 1 was skipped or last chat appears in recent set
			chatSyncService.addEventListener('phase_2_last_20_chats_ready', handleSyncComplete);
			
			console.debug('[+page.svelte] Sync event listeners registered');
		}
		
		// Initialize authentication state (panelState will react to this)
		await initialize(); // Call the imported initialize function
		console.debug('[+page.svelte] initialize() finished');
		
		// CRITICAL: Re-check signup hash AFTER initialize() completes
		// This ensures hash-based signup state persists even if checkAuth() reset it
		// The hash takes absolute precedence over last_opened
		if (hasSignupHash && window.location.hash.startsWith('#signup/')) {
			console.debug(`[+page.svelte] Re-applying signup hash state after initialize(): ${window.location.hash}`);
			const signupHash = window.location.hash.substring(1); // Remove leading #
			const step = getStepFromPath(signupHash);
			currentSignupStep.set(step);
			isInSignupProcess.set(true);
			loginInterfaceOpen.set(true);
			console.debug(`[+page.svelte] Re-applied signup state: step=${step}, isInSignupProcess=true, loginInterfaceOpen=true`);
		}
		
		// CRITICAL: Use ORIGINAL hash value (read at start of onMount) to detect hash chat
		// This prevents welcome chat loading from overwriting the hash before we check it
		// Priority: hash chat > last opened chat > default (demo-welcome for non-auth, new chat for auth)
		let hasChatHash = false;
		let hashChatId: string | null = originalHashChatId; // Use original hash, not current hash
		
		if (hashChatId) {
			console.debug(`[+page.svelte] [DETECTED] Found chat deep link in ORIGINAL URL hash: ${hashChatId} - will load after chats are ready`);
			
			hasChatHash = true;
			
			// Check if it's a public chat (demo/legal) - these can be loaded immediately
			const { getPublicChatById } = await import('@repo/ui');
			const publicChat = getPublicChatById(hashChatId);
			
			if (publicChat) {
				// Public chat - can load immediately (no sync needed)
				console.debug(`[+page.svelte] [DETECTED] Hash chat is public chat, loading immediately: ${hashChatId}`);
				isProcessingInitialHash = true;
				await handleChatDeepLink(hashChatId);
				isProcessingInitialHash = false;
			} else if (!isAuth) {
				// For non-authenticated users, shared chats are already in IndexedDB, so load immediately
				console.debug(`[+page.svelte] [DETECTED] Hash chat is shared chat (non-auth), loading immediately: ${hashChatId}`);
				isProcessingInitialHash = true;
				await handleChatDeepLink(hashChatId);
				isProcessingInitialHash = false;
			} else {
				// User chat for authenticated users - will be loaded after sync completes
				console.debug(`[+page.svelte] [DETECTED] Hash chat is user chat, will load after sync: ${hashChatId}`);
			}
		}
		
		// CRITICAL: Check if user is in signup flow AFTER initialize() completes
		// This ensures login interface opens on page reload or login for users who haven't completed signup
		// checkAuth() should have already set this, but we verify and ensure login interface is open
		// This handles both page reload and login scenarios
		// Note: The $effect at top level will also handle this reactively, but we check immediately here too
		if ($authStore.isAuthenticated && $userProfile.last_opened && isSignupPath($userProfile.last_opened)) {
			console.debug('[+page.svelte] User is in signup flow after initialize() - ensuring login interface is open', {
				last_opened: $userProfile.last_opened,
				isInSignupProcess: $isInSignupProcess,
				loginInterfaceOpen: $loginInterfaceOpen
			});
			
			// Ensure signup state is set
			if (!$isInSignupProcess) {
				const step = getStepFromPath($userProfile.last_opened);
				currentSignupStep.set(step);
				isInSignupProcess.set(true);
				console.debug(`[+page.svelte] Set signup step to: ${step} from last_opened: ${$userProfile.last_opened}`);
			}
			
			// Ensure login interface is open to show signup flow
			if (!$loginInterfaceOpen) {
				loginInterfaceOpen.set(true);
				console.debug('[+page.svelte] Opened login interface to show signup flow');
			}
		}
		
		// Fetch most used apps on app load (non-blocking, cached for 1 hour)
		// This ensures data is available when App Store opens
		mostUsedAppsStore.fetchMostUsedApps(0).catch(error => {
			console.error('[+page.svelte] Error fetching most used apps:', error);
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
		// Use originalHashChatId to check (read before anything could modify hash)
		const shouldLoadWelcomeChat = !isAuth && !hasChatHash && !originalHashChatId;
		
		if (shouldLoadWelcomeChat) {
			console.debug('[+page.svelte] [NON-AUTH] Starting welcome chat loading logic...');
			// Retry mechanism to wait for activeChat component to bind
			const loadWelcomeChat = async (retries = 20): Promise<void> => {
				// CRITICAL: Check original hash (not current hash which might have been modified)
				// If original hash exists, don't load welcome chat
				if (originalHashChatId) {
					console.debug('[+page.svelte] [NON-AUTH] Original hash detected, aborting welcome chat loading');
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
				if (sidebarOpen && storeChatId === 'demo-welcome' && activeChat) {
					console.debug('[+page.svelte] [NON-AUTH] Welcome chat already selected by Chats.svelte (sidebar open), skipping duplicate load');
					return;
				}
				
				if (activeChat) {
					console.debug('[+page.svelte] [NON-AUTH] Loading welcome demo chat (instant)');
					const { DEMO_CHATS, convertDemoChatToChat, translateDemoChat } = await import('@repo/ui');
					const welcomeDemo = DEMO_CHATS.find(chat => chat.chat_id === 'demo-welcome');
					if (welcomeDemo) {
						// Translate the demo chat to the user's locale
						const translatedWelcomeDemo = translateDemoChat(welcomeDemo);
						const welcomeChat = convertDemoChatToChat(translatedWelcomeDemo);
						activeChatStore.setActiveChat('demo-welcome');
						activeChat.loadChat(welcomeChat);
						console.debug('[+page.svelte] [NON-AUTH] ✅ Welcome chat loaded successfully');
					} else {
						console.error('[+page.svelte] [NON-AUTH] ⚠️ Welcome demo chat not found in DEMO_CHATS');
					}
				} else if (retries > 0) {
					// Wait a bit longer on first few retries, then shorter waits
					const delay = retries > 10 ? 50 : 100;
					console.debug(`[+page.svelte] [NON-AUTH] activeChat not ready, retrying in ${delay}ms (${retries} retries left)`);
					await new Promise(resolve => setTimeout(resolve, delay));
					return loadWelcomeChat(retries - 1);
				} else {
					console.warn('[+page.svelte] [NON-AUTH] ⚠️ Failed to load welcome chat - activeChat not available after retries');
				}
			};
			
			// Start loading immediately, will retry if needed (non-blocking)
			// This ensures welcome chat loads on small screens where Chats.svelte doesn't mount
			// On large screens, this will load it if Chats.svelte hasn't already done so
			loadWelcomeChat().catch(error => {
				console.error('[+page.svelte] [NON-AUTH] Error loading welcome chat:', error);
			});
		} else if (!isAuth && (hasChatHash || originalHashChatId)) {
			console.debug('[+page.svelte] [NON-AUTH] Skipping welcome chat load - URL hash chat has priority');
		}
		
		// INSTANT LOAD: Check if last opened chat is already in IndexedDB (non-blocking)
		// This provides instant load on page reload without waiting for sync
		// CRITICAL: On tab reload, load from IndexedDB (not server state) to prevent sudden chat switches
		// On login, server state will be used (via handleSyncCompleteAndLoadChat)
		// CRITICAL: URL hash chat has priority - skip last opened chat if hash is present
		// Use originalHashChatId (read before anything could modify it)
		if ($authStore.isAuthenticated && dbInitPromise && !hasChatHash && !originalHashChatId) {
			// Only load last opened chat if we don't have a chat hash
			dbInitPromise.then(async () => {
				// Double-check original hash still applies (shouldn't change, but be safe)
				if (originalHashChatId) {
					console.debug('[+page.svelte] [TAB RELOAD] Original hash detected during instant load, aborting last opened chat load');
					return;
				}
					// Load last_opened from IndexedDB (local state) instead of server state
					// This prevents the sudden switch when server sync completes after tab reload
					const { userDB } = await import('@repo/ui');
					const localProfile = await userDB.getUserProfile();
					const lastOpenedChatId = localProfile?.last_opened;
					
					if (!lastOpenedChatId) {
						console.debug('[+page.svelte] [TAB RELOAD] No last opened chat in IndexedDB, will wait for sync or use server state on login');
						return;
					}
					
					// Handle "new chat window" case
					if (lastOpenedChatId === '/chat/new' || lastOpenedChatId === 'new') {
						console.debug('[+page.svelte] [TAB RELOAD] Last opened was new chat window, clearing active chat');
						// Clear active chat to show new chat window
						// The ActiveChat component will show the new chat interface when no chat is selected
						activeChatStore.clearActiveChat();
						phasedSyncState.markSyncCompleted();
						return;
					}
					
					// Handle real chat ID
					if (activeChat) {
						console.debug('[+page.svelte] [TAB RELOAD] Checking if last opened chat is already in IndexedDB:', lastOpenedChatId);
						const lastChat = await chatDB.getChat(lastOpenedChatId);
						if (lastChat) {
							// SECURITY: Don't load hidden chats on page reload - they require passcode to unlock
							// Check if chat is a hidden candidate (can't decrypt with master key)
							if ((lastChat as any).is_hidden_candidate || (lastChat as any).is_hidden) {
								console.debug('[+page.svelte] [TAB RELOAD] Last opened chat is hidden, skipping load (requires passcode)');
								// Clear last_opened to prevent trying to load it again
								await userDB.updateUserData({ last_opened: '/chat/new' });
								activeChatStore.clearActiveChat();
								phasedSyncState.markSyncCompleted();
								return;
							}
							
							console.debug('[+page.svelte] ✅ INSTANT LOAD: Last opened chat found in IndexedDB (tab reload), loading immediately');
							activeChatStore.setActiveChat(lastOpenedChatId);
							activeChat.loadChat(lastChat);
							// Mark sync as completed since we already have data
							phasedSyncState.markSyncCompleted();
							console.debug('[+page.svelte] ✅ Chat loaded instantly from IndexedDB cache (tab reload)');
						} else {
							console.debug('[+page.svelte] Last opened chat not in IndexedDB yet, will wait for sync');
						}
					}
				});
		}

        // Check if we need to start phased sync manually
        // (it might have already started automatically during initialize())
        if (!$phasedSyncState.initialSyncCompleted && $authStore.isAuthenticated) {
            if ($websocketStatus.status === 'connected') {
                console.debug('[+page.svelte] WebSocket already connected, checking if sync needs to be started...');
                // Sync might have already started automatically, so we don't force start it again
            } else {
                console.debug('[+page.svelte] Waiting for WebSocket connection before starting phased sync...');
                // Listen for WebSocket connection to start syncing
                const unsubscribeWS = websocketStatus.subscribe((wsState: { status: string }) => {
                    if (wsState.status === 'connected' && $authStore.isAuthenticated && !$phasedSyncState.initialSyncCompleted) {
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
            // CRITICAL: URL hash chat has priority over last opened chat
            if (activeChat) {
                // Check if original URL hash contains a chat ID (has priority)
                // Use originalHashChatId (read before anything could modify it)
                if (originalHashChatId) {
                    console.debug('[+page.svelte] [TAB RELOAD] Original URL hash contains chat ID, loading hash chat (hash has priority):', originalHashChatId);
                    // Load the hash chat instead of last opened chat
                    isProcessingInitialHash = true;
                    await handleChatDeepLink(originalHashChatId);
                    isProcessingInitialHash = false;
                } else {
                    try {
                        // Load from IndexedDB (local state) instead of server state
                        const { userDB } = await import('@repo/ui');
                        const localProfile = await userDB.getUserProfile();
                        const lastOpenedChatId = localProfile?.last_opened;
                        
                        if (!lastOpenedChatId) {
                            return;
                        }
                        
                        // Handle "new chat window" case
                        if (lastOpenedChatId === '/chat/new' || lastOpenedChatId === 'new') {
                            console.debug('[+page.svelte] [TAB RELOAD] Last opened was new chat window, clearing active chat');
                            // Clear active chat to show new chat window
                            // The ActiveChat component will show the new chat interface when no chat is selected
                            activeChatStore.clearActiveChat();
                            return;
                        }
                        
                        // Handle real chat ID
                        const lastChat = await chatDB.getChat(lastOpenedChatId);
                        if (lastChat) {
                            console.debug('[+page.svelte] [TAB RELOAD] Sync already complete, loading last opened chat from IndexedDB:', lastOpenedChatId);
                            activeChatStore.setActiveChat(lastOpenedChatId);
                            activeChat.loadChat(lastChat);
                        }
                    } catch (error) {
                        console.error('[+page.svelte] Error loading last opened chat from IndexedDB:', error);
                    }
                }
            }
        }

        // Clear signup hash after processing (if it was present) to keep URL clean
        // (similar to how chat deep links are cleared after loading)
        if (hasSignupHash) {
            window.history.replaceState({}, '', window.location.pathname + window.location.search);
        }
        
        // Handle other deep links (settings, chat, etc.)
        if (window.location.hash.startsWith('#settings')) {
            const settingsPath = window.location.hash.substring('#settings'.length);
            
            // CRITICAL: Check if this settings deep link requires authentication
            // Some settings (app_store, interface) are public and don't require authentication
            // Others (billing, account, security) require authentication
            const needsAuth = requiresAuthentication(settingsPath);
            
            if (needsAuth && !$authStore.isAuthenticated) {
                // This settings deep link requires authentication and user is not authenticated
                console.debug(`[+page.svelte] User not authenticated - storing settings deep link for after login: ${window.location.hash}`);
                // Store the deep link in sessionStorage to process after login
                sessionStorage.setItem('pendingDeepLink', window.location.hash);
                // Open login interface to prompt user to log in
                loginInterfaceOpen.set(true);
                // Clear the hash immediately to keep URL clean (we'll restore it after login)
                window.history.replaceState({}, '', window.location.pathname + window.location.search);
            } else {
                // Either doesn't require auth, or user is authenticated - process the deep link immediately
                processSettingsDeepLink(window.location.hash);
            }
        } else if (window.location.hash.startsWith('#chat_id=') || window.location.hash.startsWith('#chat-id=')) {
            // Handle chat deep linking from URL (fallback - should have been processed earlier)
            // Support both #chat_id= and #chat-id= formats
            const chatId = window.location.hash.startsWith('#chat_id=') 
                ? window.location.hash.substring(9) // Remove '#chat_id=' prefix
                : window.location.hash.substring(9); // Remove '#chat-id=' prefix
            console.debug(`[+page.svelte] Found chat deep link in URL (fallback processing): ${chatId}`);
            
            // Only process if not already processed earlier
            if (!isProcessingInitialHash) {
                // Mark as processing initial hash load
                isProcessingInitialHash = true;
                
                // Handle the deep link (supports both user chats and demo/legal chats)
                await handleChatDeepLink(chatId);
                
                // Reset flag after processing
                isProcessingInitialHash = false;
            } else {
                console.debug(`[+page.svelte] Chat hash already processed earlier, skipping duplicate processing`);
            }
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
        window.addEventListener('processPendingDeepLink', handlePendingDeepLink as EventListener);
        
        console.debug('[+page.svelte] onMount finished');
    });
    
    // Cleanup function for onDestroy
    onDestroy(() => {
        if (handleWebSocketAuthError) {
            webSocketService.removeEventListener('authError', handleWebSocketAuthError as EventListener);
        }
        // Only unregister payment handlers if they were registered
        if (!wasInSignupProcessAtMount && handlePaymentCompleted && handlePaymentFailed) {
            webSocketService.off('payment_completed', handlePaymentCompleted);
            webSocketService.off('payment_failed', handlePaymentFailed);
        }
        // Remove pending deep link event listener
        window.removeEventListener('processPendingDeepLink', handlePendingDeepLink as EventListener);
        // Note: hashchange, visibilitychange, pagehide, and beforeunload handlers are cleaned up automatically on page unload
    });

    /**
     * Handle hash changes after page load
     * Allows navigation by pasting URLs with chat_id, signup hash, or settings hash
     * 
     * CRITICAL: Ignores programmatic hash updates to prevent infinite loops
     */
    async function handleHashChange() {
        // Import the check function
        const { isProgrammaticHashUpdate } = await import('@repo/ui');
        
        // Ignore hash changes that we triggered programmatically (prevents infinite loops)
        if (isProgrammaticHashUpdate()) {
            console.debug('[+page.svelte] Ignoring programmatic hash update');
            return;
        }
        
        console.debug('[+page.svelte] Hash changed:', window.location.hash);
        
        if (window.location.hash.startsWith('#signup/')) {
            // Handle signup deep linking - open login interface and set signup step
            console.debug(`[+page.svelte] Hash changed to signup deep link: ${window.location.hash}`);
            
            // Extract step from hash (e.g., #signup/credits -> credits)
            const signupHash = window.location.hash.substring(1); // Remove leading #
            const step = getStepFromPath(signupHash);
            
            console.debug(`[+page.svelte] Setting signup step to: ${step} from hash: ${window.location.hash}`);
            
            // Set signup step and open login interface
            currentSignupStep.set(step);
            isInSignupProcess.set(true);
            loginInterfaceOpen.set(true);
            
            // Clear the hash after processing to keep URL clean
            window.history.replaceState({}, '', window.location.pathname + window.location.search);
        } else if (window.location.hash.startsWith('#settings')) {
            // Handle settings deep linking - open settings menu and navigate to specific page
            console.debug(`[+page.svelte] Hash changed to settings deep link: ${window.location.hash}`);
            
            const settingsPath = window.location.hash.substring('#settings'.length);
            
            // CRITICAL: Check if this settings deep link requires authentication
            // Some settings (app_store, interface) are public and don't require authentication
            // Others (billing, account, security) require authentication
            const needsAuth = requiresAuthentication(settingsPath);
            
            if (needsAuth && !$authStore.isAuthenticated) {
                // This settings deep link requires authentication and user is not authenticated
                console.debug(`[+page.svelte] User not authenticated - storing settings deep link for after login: ${window.location.hash}`);
                // Store the deep link in sessionStorage to process after login
                sessionStorage.setItem('pendingDeepLink', window.location.hash);
                // Open login interface to prompt user to log in
                loginInterfaceOpen.set(true);
                // Clear the hash immediately to keep URL clean (we'll restore it after login)
                window.history.replaceState({}, '', window.location.pathname + window.location.search);
            } else {
                // Either doesn't require auth, or user is authenticated - process the deep link immediately
                processSettingsDeepLink(window.location.hash);
            }
        } else if (window.location.hash.startsWith('#chat_id=') || window.location.hash.startsWith('#chat-id=')) {
            // Support both #chat_id= and #chat-id= formats
            // CRITICAL: This handles navigation from share page to main page with hash
            const chatId = window.location.hash.startsWith('#chat_id=')
                ? window.location.hash.substring('#chat_id='.length)
                : window.location.hash.substring('#chat-id='.length);
            
            console.debug(`[+page.svelte] Hash changed to chat deep link: ${chatId}`);
            
            // Update originalHashChatId to reflect the new hash (important for sync completion handler)
            originalHashChatId = chatId;
            
            // Mark as processing initial hash load (for hashchange handler)
            isProcessingInitialHash = true;
            
            await handleChatDeepLink(chatId);
            
            // Reset flag after processing
            isProcessingInitialHash = false;
        }
    }

    // Add handler for chatSelected event
    // FIXED: Improved retry mechanism with multiple attempts to ensure chat loads for SEO
    async function handleChatSelected(event: CustomEvent) {
        const selectedChat: Chat = event.detail.chat;
        console.debug("[+page.svelte] Received chatSelected event:", selectedChat.chat_id); // Use chat_id
        
        // Retry mechanism with multiple attempts to ensure chat loads (critical for SEO)
        const loadChatWithRetry = async (retries = 20): Promise<void> => {
            if (activeChat) {
                console.debug("[+page.svelte] activeChat ready, loading chat:", selectedChat.chat_id);
                activeChat.loadChat(selectedChat);
                console.debug("[+page.svelte] ✅ Successfully called loadChat for:", selectedChat.chat_id);
                return;
            } else if (retries > 0) {
                // Wait a bit longer on first few retries, then shorter waits
                const delay = retries > 10 ? 50 : 100;
                console.debug(`[+page.svelte] activeChat not ready yet, retrying in ${delay}ms (${retries} retries left)...`);
                await new Promise(resolve => setTimeout(resolve, delay));
                return loadChatWithRetry(retries - 1);
            } else {
                console.error("[+page.svelte] ⚠️ activeChat ref still not available after all retries - chat may not load for SEO");
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
            console.debug("[+page.svelte] chatDeselected event received - resetting ActiveChat to new chat state");
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

<div class="sidebar" class:closed={!$panelState.isActivityHistoryOpen}>
    {#if $panelState.isActivityHistoryOpen}
        <!-- Sidebar content - transition handled by parent sidebar transform -->
        <div class="sidebar-content">
            <Chats 
                on:chatSelected={handleChatSelected} 
                on:chatDeselected={handleChatDeselected}
            />
        </div>
    {/if}
</div>

<div class="main-content"
    class:menu-closed={!$panelState.isActivityHistoryOpen}
    class:initial-load={isInitialLoad}
    class:scrollable={showFooter}>
    <!-- Notification overlay - slides in from top -->
    <div class="notification-container">
        {#each $notificationStore.notifications as notification}
            <Notification {notification} />
        {/each}
    </div>
    
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="chat-container"
        class:menu-open={$panelState.isSettingsOpen}
        class:authenticated={$authStore.isAuthenticated}
        class:signup-process={$isInSignupProcess}>
        <div class="chat-wrapper">
            <!-- ActiveChat component - loads welcome chat via JS for PWA -->
            <ActiveChat
                bind:this={activeChat}
            />
        </div>
        <div class="settings-wrapper">
            <Settings 
                isLoggedIn={$authStore.isAuthenticated}
                on:chatSelected={handleChatSelected}
            />
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
        transition: transform 0.3s ease, opacity 0.3s ease, visibility 0.3s ease;
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
        transition: left 0.3s ease, transform 0.3s ease;
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
        .chat-container{
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
        transition: left 0.3s ease, transform 0.3s ease;
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
