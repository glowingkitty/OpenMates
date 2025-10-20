<script lang="ts">
    import {
        // components
        Chats,
        ActiveChat,
        Header,
        Settings,
        Footer,
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
        // types
        type Chat,
        // services
        chatDB,
        chatSyncService,
    } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { onMount } from 'svelte';
    // Removed browser import as it's handled in uiStateStore now

    // --- State ---
    let isInitialLoad = $state(true);
    let activeChat: ActiveChat | null = null; // Reference to ActiveChat instance

    // --- Reactive Computations ---

    // Determine if the footer should be shown (depends on auth and signup state)
    let showFooter = $derived(!$authStore.isAuthenticated || ($isInSignupProcess && $showSignupFooter));

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
     */
    async function handleSyncCompleteAndLoadLastChat() {
        console.debug('[+page.svelte] Sync completed, checking for last opened chat...');
        
        // Get the last opened chat ID from user profile
        const lastOpenedChatId = $userProfile.last_opened;
        
        if (!lastOpenedChatId) {
            console.debug('[+page.svelte] No last opened chat in user profile');
            return;
        }
        
        try {
            // Ensure chatDB is initialized
            await chatDB.init();
            
            // Try to load the last opened chat from IndexedDB
            const lastChat = await chatDB.getChat(lastOpenedChatId);
            
            if (lastChat && activeChat) {
                console.debug('[+page.svelte] Loading last opened chat after sync:', lastOpenedChatId);
                
                // Update the active chat store so the sidebar highlights it when opened
                activeChatStore.setActiveChat(lastOpenedChatId);
                
                // Load the chat in the UI
                activeChat.loadChat(lastChat);
                
                console.debug('[+page.svelte] Successfully loaded last opened chat');
            } else if (!lastChat) {
                console.warn('[+page.svelte] Last opened chat not found in IndexedDB:', lastOpenedChatId);
            } else if (!activeChat) {
                console.warn('[+page.svelte] ActiveChat component not ready yet, retrying...');
                // Retry after a short delay if activeChat isn't ready
                setTimeout(handleSyncCompleteAndLoadLastChat, 200);
            }
        } catch (error) {
            console.error('[+page.svelte] Error loading last opened chat:', error);
        }
    }
    
    // --- Lifecycle ---
    onMount(async () => {
        console.debug('[+page.svelte] onMount started');
        
        // Initialize authentication state (panelState will react to this)
        await initialize(); // Call the imported initialize function
        console.debug('[+page.svelte] initialize() finished');

        // CRITICAL FIX: Start phased sync here instead of in Chats.svelte
        // This ensures sync works on mobile where the sidebar (Chats component) is closed by default
        // Only start if sync hasn't been completed yet and user is authenticated
        if (!$phasedSyncState.initialSyncCompleted && $authStore.isAuthenticated) {
            // Register listener for sync completion to auto-open last chat (per sync.md Phase 1 requirements)
            const handleSyncComplete = (async () => {
                await handleSyncCompleteAndLoadLastChat();
            }) as EventListener;
            
            // Register listener to mark sync as completed in the state store
            // This is critical for mobile where Chats.svelte might not be mounted when sync completes
            const handlePhasedSyncComplete = (() => {
                console.debug('[+page.svelte] Phased sync complete, marking as completed in state store');
                phasedSyncState.markSyncCompleted();
            }) as EventListener;
            
            chatSyncService.addEventListener('syncComplete', handleSyncComplete);
            chatSyncService.addEventListener('phasedSyncComplete', handleSyncComplete);
            chatSyncService.addEventListener('phasedSyncComplete', handlePhasedSyncComplete);
            
            if ($websocketStatus.status === 'connected') {
                console.debug('[+page.svelte] Starting initial phased sync process...');
                phasedSyncState.updateSyncTimestamp();
                await chatSyncService.startPhasedSync();
            } else {
                console.debug('[+page.svelte] Waiting for WebSocket connection before starting phased sync...');
                // Listen for WebSocket connection to start syncing
                const unsubscribeWS = websocketStatus.subscribe((wsState: { status: string }) => {
                    if (wsState.status === 'connected' && $authStore.isAuthenticated && !$phasedSyncState.initialSyncCompleted) {
                        console.debug('[+page.svelte] WebSocket connected, starting initial phased sync...');
                        phasedSyncState.updateSyncTimestamp();
                        chatSyncService.startPhasedSync();
                        unsubscribeWS(); // Unsubscribe after starting sync once
                    }
                });
            }
        } else if (!$authStore.isAuthenticated) {
            console.debug('[+page.svelte] Skipping phased sync - user not authenticated');
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
    function handleChatSelected(event: CustomEvent) {
        const selectedChat: Chat = event.detail.chat;
        console.debug("[+page.svelte] Received chatSelected event:", selectedChat.chat_id); // Use chat_id
        
        if (!activeChat) {
            console.warn("[+page.svelte] activeChat ref not ready yet, retrying in 100ms...");
            // Retry after a short delay to ensure activeChat bind:this is ready
            setTimeout(() => {
                if (activeChat) {
                    console.debug("[+page.svelte] Retry successful, loading chat:", selectedChat.chat_id);
                    activeChat.loadChat(selectedChat);
                } else {
                    console.error("[+page.svelte] activeChat ref still not available after retry");
                }
            }, 100);
            return;
        }
        
        activeChat.loadChat(selectedChat);
        console.debug("[+page.svelte] Successfully called loadChat for:", selectedChat.chat_id);
        
        // Optionally close Activity History on mobile after selection
        // if ($panelState.isMobileView) { // Assuming isMobileView is exposed or checked
        //    panelState.toggleActivityHistory(); // Or a specific close action
        // }
    }
</script>

<!-- Removed svelte:window binding for innerWidth -->

<div class="sidebar" class:closed={!$panelState.isActivityHistoryOpen}>
    {#if $panelState.isActivityHistoryOpen}
        <!-- Use a transition for smoother appearance/disappearance -->
        <div class="sidebar-content" transition:fade={{ duration: 150 }}>
            <Chats on:chatSelected={handleChatSelected} />
        </div>
    {/if}
</div>

<div class="main-content"
    class:menu-closed={!$panelState.isActivityHistoryOpen}
    class:initial-load={isInitialLoad}
    class:scrollable={showFooter}>
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="chat-container"
        class:menu-open={$panelState.isSettingsOpen}
        class:authenticated={$authStore.isAuthenticated}
        class:signup-process={$isInSignupProcess}>
        <div class="chat-wrapper">
            <ActiveChat
                bind:this={activeChat}
            />
        </div>
        <div class="settings-wrapper">
            <Settings isLoggedIn={$authStore.isAuthenticated} />
        </div>
    </div>
</div>

<!-- Footer outside main content -->
{#if showFooter}
<div class="footer-wrapper">
    <Footer metaKey="webapp" context="webapp" />
</div>
{/if}

<style>
    :root {
        --sidebar-width: 325px;
        --sidebar-margin: 10px;
        --chat-container-min-height: 650px;
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

        transition: transform 0.3s ease, opacity 0.3s ease;
        opacity: 1;
        display: block;
    }

    .sidebar.closed {
        opacity: 0;
        display: none;
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
        transition: left 0.3s ease, transform 0.3s ease;
    }

    /* Add new scrollable mode styles */
    .main-content.scrollable {
        position: absolute;
        bottom: auto; /* Remove bottom constraint */
        min-height: max(var(--chat-container-min-height-mobile), 100vh); /* Ensure it takes at least full viewport height */
        min-height: max(var(--chat-container-min-height-mobile), 100dvh);; /* Ensure it takes at least full viewport height */
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
        /* min-height is removed once we are logged in and signup is completed via the .authenticated:not(.signup-process) selector */
        /* Only apply min-height when not authenticated */
        min-height: var(--chat-container-min-height-mobile);
        gap: 0px;
        padding: 10px;
        padding-right: 20px;
        /* Only apply gap transition on larger screens */
        @media (min-width: 1100px) {
            transition: gap 0.3s ease;
        }
    }

    /* Remove min-height when authenticated AND signup process is completed */
    .chat-container.authenticated:not(.signup-process) {
        min-height: unset;
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
            /* Ensure sidebar stays in place */
            transform: none;
        }

        .main-content {
            /* Position main content over the sidebar by default */
            left: 0;
            right: 0;
            z-index: 20; /* Higher than sidebar to cover it */
            transform: translateX(0);
            min-height: unset;
        }

        /* figure our css issues related to height */

        /* When menu is open, slide main content right */
        .main-content:not(.menu-closed) {
            transform: translateX(100%);
        }

        /* When menu is closed, keep main content over sidebar */
        .main-content.menu-closed {
            left: 0;
            transform: translateX(0);
        }

        .main-content.scrollable {
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
        padding-top: max(calc(var(--chat-container-min-height-mobile) + 170px), calc(100vh + 90px));
        padding-top: max(calc(var(--chat-container-min-height-mobile) + 170px), calc(100dvh + 90px));
    }
</style>
