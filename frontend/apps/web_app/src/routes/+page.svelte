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
        // types
        type Chat,
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

    // --- Lifecycle ---
    onMount(async () => {
        console.debug('[+page.svelte] onMount started');
        
        // Initialize authentication state (panelState will react to this)
        await initialize(); // Call the imported initialize function
        console.debug('[+page.svelte] initialize() finished');

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
        } else if (window.location.hash.startsWith('#chat/')) {
            const chatId = window.location.hash.substring(6);
            // panelState.openActivityHistory(); // Ensure it's open
            // TODO: Dispatch event or call method to load chat
        }

        // Remove initial load state after a small delay
        setTimeout(() => {
            console.debug('[+page.svelte] setTimeout for isInitialLoad finished');
            isInitialLoad = false;
        }, 100);

        console.debug('[+page.svelte] onMount finished');
    });

    // Add handler for chatSelected event
    function handleChatSelected(event: CustomEvent) {
        const selectedChat: Chat = event.detail.chat;
        console.debug("[+page.svelte] Received chatSelected event:", selectedChat.chat_id); // Use chat_id
        if (activeChat) {
            activeChat.loadChat(selectedChat);
        }
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
        <div transition:fade={{ duration: 150 }}>
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

        /* Add scrolling for overflow content */
        overflow-y: auto;

        /* Add more pronounced inner shadow on right side for better visibility */
        box-shadow: inset -6px 0 12px -4px rgba(0, 0, 0, 0.25);

        /* Custom scrollbar styling */
        scrollbar-width: thin;
        scrollbar-color: var(--color-grey-40) transparent;

        transition: transform 0.3s ease, opacity 0.3s ease;
        opacity: 1;
        display: block;
    }

    .sidebar.closed {
        opacity: 0;
        display: none;
    }

    /* For Webkit browsers */
    .sidebar::-webkit-scrollbar {
        width: 8px;
    }

    .sidebar::-webkit-scrollbar-track {
        background: transparent;
    }

    .sidebar::-webkit-scrollbar-thumb {
        background-color: var(--color-grey-40);
        border-radius: 4px;
        border: 2px solid transparent;
    }

    .sidebar::-webkit-scrollbar-thumb:hover {
        background-color: var(--color-grey-50);
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
