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
        // types
        type Chat,
        // services
        chatDB,
        chatSyncService,
    } from '@repo/ui';
    import { notificationStore, getKeyFromStorage } from '@repo/ui';
    import { onMount } from 'svelte';
    import { locale, waitLocale, _, isLoading } from 'svelte-i18n';
    import { browser } from '$app/environment';
    import { i18nLoaded } from '@repo/ui';

    // --- State ---
    let isInitialLoad = $state(true);
    let activeChat = $state<ActiveChat | null>(null); // Fixed: Use $state for Svelte 5

    // SEO data from translations - only access after i18n is loaded
    let seoTitle = $derived($i18nLoaded ? $_('welcome_chat.title') : '');
    let seoDescription = $derived($i18nLoaded ? $_('welcome_chat.description') : '');

    // --- Reactive Computations ---

    // Footer should only show in settings panel (not on main chat interface)
    let showFooter = $derived($panelState.isSettingsOpen);

    /**
     * Handle chat deep linking from URL
     * Waits for phased sync to complete before attempting to load the chat
     * This ensures the chat is available in IndexedDB
     * After loading, immediately clears the URL to prevent sharing chat history
     */
    async function handleChatDeepLink(chatId: string) {
        console.debug(`[+page.svelte] Handling chat deep link for: ${chatId}`);
        
        // Update the activeChatStore so the Chats component highlights it when opened
        activeChatStore.setActiveChat(chatId);
        
        // Listen for phased sync completion to ensure chat is available
        const handlePhasedSyncComplete = async () => {
            console.debug(`[+page.svelte] Phased sync complete, attempting to load deep-linked chat: ${chatId}`);
            
            // Try to load the chat from IndexedDB
            try {
                await chatDB.init(); // Ensure DB is initialized
                const chat = await chatDB.getChat(chatId);
                
                if (chat) {
                    console.debug(`[+page.svelte] Found deep-linked chat in IndexedDB:`, chat.chat_id);
                    
                    // Load the chat if activeChat component is ready
                    if (activeChat) {
                        activeChat.loadChat(chat);
                        
                        // Clear the URL immediately after loading the chat
                        // This prevents sharing chat history while still supporting deep linking
                        console.debug(`[+page.svelte] Clearing chat_id from URL after loading deep-linked chat`);
                        window.history.replaceState({}, '', window.location.pathname + window.location.search);
                    } else {
                        // If activeChat isn't ready yet, wait a bit and retry
                        setTimeout(() => {
                            if (activeChat) {
                                activeChat.loadChat(chat);
                                
                                // Clear the URL after loading
                                console.debug(`[+page.svelte] Clearing chat_id from URL after loading deep-linked chat (delayed)`);
                                window.history.replaceState({}, '', window.location.pathname + window.location.search);
                            } else {
                                console.warn(`[+page.svelte] activeChat component not ready for deep link`);
                            }
                        }, 500);
                    }
                } else {
                    console.warn(`[+page.svelte] Chat ${chatId} not found in IndexedDB after sync`);
                    // Chat doesn't exist for this user - clear the URL and store
                    activeChatStore.clearActiveChat();
                    window.history.replaceState({}, '', window.location.pathname + window.location.search);
                }
            } catch (error) {
                console.error(`[+page.svelte] Error loading deep-linked chat:`, error);
                // Clear URL on error
                window.history.replaceState({}, '', window.location.pathname + window.location.search);
            }
            
            // Remove the listener after handling
            chatSyncService.removeEventListener('phasedSyncComplete', handlePhasedSyncComplete as EventListener);
        };
        
        // Register listener for phased sync completion
        chatSyncService.addEventListener('phasedSyncComplete', handlePhasedSyncComplete as EventListener);
        
        // Also try immediately in case sync already completed
        // (e.g., page reload with URL already set)
        setTimeout(handlePhasedSyncComplete, 1000);
    }
    
    /**
     * Handler for sync completion - automatically loads the last opened chat
     * This implements the "Auto-Open Logic" from sync.md Phase 1 requirements
     * 
     * OPTIMIZATION: Check if chat is already loaded to avoid duplicate loads
     * Only loads if chat exists in IndexedDB but isn't currently displayed
     */
    async function handleSyncCompleteAndLoadLastChat() {
        console.debug('[+page.svelte] Sync event received, checking for last opened chat...');
        
        // Get the last opened chat ID from user profile
        const lastOpenedChatId = $userProfile.last_opened;
        
        if (!lastOpenedChatId) {
            console.debug('[+page.svelte] No last opened chat in user profile');
            return;
        }
        
        // Skip if this chat is already loaded (active chat store matches)
        if ($activeChatStore === lastOpenedChatId) {
            console.debug('[+page.svelte] Last opened chat already loaded, skipping');
            return;
        }
        
        try {
            // Ensure chatDB is initialized
            await chatDB.init();
            
            // Try to load the last opened chat from IndexedDB
            // This will succeed as soon as the chat data is saved during any sync phase
            const lastChat = await chatDB.getChat(lastOpenedChatId);
            
            if (lastChat && activeChat) {
                console.debug('[+page.svelte] ✅ Loading last opened chat from sync:', lastOpenedChatId);
                
                // Update the active chat store so the sidebar highlights it when opened
                activeChatStore.setActiveChat(lastOpenedChatId);
                
                // Load the chat in the UI
                activeChat.loadChat(lastChat);
                
                console.debug('[+page.svelte] ✅ Successfully loaded last opened chat from sync');
            } else if (!lastChat) {
                console.debug('[+page.svelte] Last opened chat not yet in IndexedDB, will try again after next sync phase');
            } else if (!activeChat) {
                console.debug('[+page.svelte] ActiveChat component not ready yet, retrying...');
                // Retry after a short delay if activeChat isn't ready
                setTimeout(handleSyncCompleteAndLoadLastChat, 100);
            }
        } catch (error) {
            console.error('[+page.svelte] Error loading last opened chat:', error);
        }
    }
    
	// Login state management happens through components now
	// Login overlay feature was removed as incomplete implementation

	// --- Lifecycle ---
	onMount(async () => {
		console.debug('[+page.svelte] onMount started');
		
		// Handle ?lang= query parameter for language selection
		if (browser) {
			const urlParams = new URLSearchParams(window.location.search);
			const langParam = urlParams.get('lang');
			const supportedLocales = ['en', 'de', 'es', 'fr', 'zh', 'ja'];
			
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
		
		// CRITICAL: Register sync event listeners FIRST, before initialization
		// chatSyncService can auto-start sync when WebSocket connects during initialize()
		// If we register listeners after, we'll miss the syncComplete event
		if (isAuth || !$phasedSyncState.initialSyncCompleted) {
			console.debug('[+page.svelte] Registering sync event listeners...');
			
			// Register listener for sync completion to auto-open last chat (per sync.md Phase 1 requirements)
			const handleSyncComplete = (async () => {
				console.debug('[+page.svelte] Sync complete event received, marking as completed');
				phasedSyncState.markSyncCompleted(); // Mark immediately on any sync complete event
				await handleSyncCompleteAndLoadLastChat();
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
		
		// Load welcome chat for non-authenticated users (instant load)
		// Use the actual DEMO_CHATS data to ensure all fields (including follow_up_suggestions) are present
		// CRITICAL: Wait for activeChat component to be ready before loading chat
		// FIXED: Improved retry mechanism - loads welcome chat regardless of Chats.svelte mount state
		// This ensures welcome chat loads on both large screens (when Chats mounts) and small screens (when Chats doesn't mount)
		// On mobile, Chats.svelte doesn't mount when sidebar is closed, so this is the primary loading path
		if (!isAuth) {
			console.debug('[+page.svelte] [NON-AUTH] Starting welcome chat loading logic...');
			// Retry mechanism to wait for activeChat component to bind
			const loadWelcomeChat = async (retries = 20): Promise<void> => {
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
		}
		
		// INSTANT LOAD: Check if last opened chat is already in IndexedDB (non-blocking)
		// This provides instant load on page reload without waiting for sync
		if ($authStore.isAuthenticated && dbInitPromise) {
			dbInitPromise.then(async () => {
				const lastOpenedChatId = $userProfile.last_opened;
				if (lastOpenedChatId && activeChat) {
					console.debug('[+page.svelte] Checking if last opened chat is already in IndexedDB:', lastOpenedChatId);
					const lastChat = await chatDB.getChat(lastOpenedChatId);
					if (lastChat) {
						console.debug('[+page.svelte] ✅ INSTANT LOAD: Last opened chat found in IndexedDB, loading immediately');
						activeChatStore.setActiveChat(lastOpenedChatId);
						activeChat.loadChat(lastChat);
						// Mark sync as completed since we already have data
						phasedSyncState.markSyncCompleted();
						console.debug('[+page.svelte] ✅ Chat loaded instantly from cache');
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
            // check if we should load the last opened chat
            if ($userProfile.last_opened && activeChat) {
                const lastChat = await chatDB.getChat($userProfile.last_opened);
                if (lastChat) {
                    console.debug('[+page.svelte] Sync already complete, loading last opened chat:', $userProfile.last_opened);
                    activeChatStore.setActiveChat($userProfile.last_opened);
                    activeChat.loadChat(lastChat);
                }
            }
        }

        // Handle deep links (e.g., #settings, #chat/123)
        if (window.location.hash.startsWith('#settings')) {
            panelState.openSettings();
            const settingsPath = window.location.hash.substring('#settings'.length);
            if (settingsPath.startsWith('/')) {
                settingsDeepLink.set(settingsPath.substring(1)); // Remove leading slash
            } else if (settingsPath === '') {
                 settingsDeepLink.set('main'); // Default to main settings if just #settings
            } else {
                 // Handle invalid settings path?
                 console.warn(`[+page.svelte] Invalid settings deep link hash: ${window.location.hash}`);
                 settingsDeepLink.set('main'); // Default to main on invalid hash
            }
        } else if (window.location.hash.startsWith('#chat_id=')) {
            // Handle chat deep linking from URL
            const chatId = window.location.hash.substring(9); // Remove '#chat_id=' prefix
            console.debug(`[+page.svelte] Found chat deep link in URL: ${chatId}`);
            
            // Wait for sync to complete before attempting to load the chat
            // This ensures the chat is available in IndexedDB
            handleChatDeepLink(chatId);
        }

        // Remove initial load state after a small delay
        setTimeout(() => {
            console.debug('[+page.svelte] setTimeout for isInitialLoad finished');
            isInitialLoad = false;
        }, 100);

        // Listen for hash changes (e.g., user pastes a new URL with different chat_id)
        window.addEventListener('hashchange', handleHashChange);
        
        console.debug('[+page.svelte] onMount finished');
    });

    /**
     * Handle hash changes after page load
     * Allows navigation by pasting URLs with chat_id hash
     */
    function handleHashChange() {
        console.debug('[+page.svelte] Hash changed:', window.location.hash);
        
        if (window.location.hash.startsWith('#chat_id=')) {
            const chatId = window.location.hash.substring(9);
            handleChatDeepLink(chatId);
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
</script>

<!-- SEO meta tags - client-side with translations -->
<svelte:head>
    <title>{seoTitle}</title>
    <meta name="description" content={seoDescription} />
    <meta name="keywords" content="AI, assistant, privacy, encryption, PWA, offline" />
    
    <!-- hreflang tags for multi-language SEO -->
    <link rel="alternate" hreflang="en" href="https://openmates.org/?lang=en" />
    <link rel="alternate" hreflang="de" href="https://openmates.org/?lang=de" />
    <link rel="alternate" hreflang="es" href="https://openmates.org/?lang=es" />
    <link rel="alternate" hreflang="fr" href="https://openmates.org/?lang=fr" />
    <link rel="alternate" hreflang="zh" href="https://openmates.org/?lang=zh" />
    <link rel="alternate" hreflang="ja" href="https://openmates.org/?lang=ja" />
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
            <Chats on:chatSelected={handleChatSelected} />
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

<!-- Footer outside main content -->
{#if showFooter}
<div class="footer-wrapper">
    <Footer metaKey="webapp" context="webapp" />
</div>
{/if}

<!-- Login/Signup overlay removed - incomplete feature
     TODO: Implement proper login overlay if needed -->

<style>
    :root {
        --sidebar-width: 325px;
        --sidebar-margin: 10px;
    }
    
    /* SEO-only content (inside noscript tag, visible only to crawlers and no-JS users) */
    .seo-chat-content {
        max-width: 800px;
        margin: 2rem auto;
        padding: 2rem;
        line-height: 1.6;
        font-family: system-ui, -apple-system, sans-serif;
    }
    
    .seo-chat-content h1 {
        font-size: 2rem;
        margin-bottom: 0.5rem;
        color: #000;
    }
    
    .seo-chat-content .description {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    
    .seo-chat-content .messages {
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    
    .seo-chat-content .message {
        padding: 1rem;
        border-radius: 8px;
        background: #f5f5f5;
    }
    
    .seo-chat-content .message.assistant {
        background: #e3f2fd;
        align-self: flex-start;
        max-width: 80%;
    }
    
    .seo-chat-content .message.user {
        background: #d1f4d1;
        align-self: flex-end;
        max-width: 80%;
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
        height: calc(100vh - 90px);
        /* Modern browsers will use this */
        height: calc(100dvh - 90px);
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
    @media (max-width: 730px) {
        .chat-container{
            padding-right: 10px;
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

    /* Update footer wrapper styles */
    .footer-wrapper {
        position: relative; /* Change from absolute to relative */
        width: 100%;
        z-index: 5; /* Ensure it's below main content */
        margin-top: -90px; /* Adjust based on your footer height */
        padding-top: calc(100vh + 90px);
        padding-top: calc(100dvh + 90px);
    }

    /* Login overlay styles */
    .login-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: var(--color-grey-0);
        z-index: 1000;
        overflow-y: auto;
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
