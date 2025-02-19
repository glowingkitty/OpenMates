<script lang="ts">
    import {
        // components
        ActivityHistory,
        ActiveChat,
        Header,
        Settings,
        Footer,
        isAuthenticated,
        // constants
        MOBILE_BREAKPOINT,
        // stores
        isMenuOpen,
        settingsMenuVisible,
        isMobileView,
        // types
        type Chat,
    } from '@repo/ui';
    import { _ } from 'svelte-i18n'; // Import the translation function
    import { fade } from 'svelte/transition';
    // Subscribe to settings menu visibility state
    import { onMount } from 'svelte';

    // Compute gap class based on menu state and view
    $: menuClass = $settingsMenuVisible && !$isMobileView ? 'menu-open' : '';

    // Handle initial sidebar state based on auth
    $: if ($isAuthenticated) {
        // Only open menu on desktop when authenticated
        if (window.innerWidth >= MOBILE_BREAKPOINT) {
            isMenuOpen.set(true);
        }
    } else {
        isMenuOpen.set(false);
    }

    // Add state for initial load
    let isInitialLoad = true;

    // Add reference to ActiveChat instance
    let activeChat: ActiveChat | null = null;

    onMount(() => {
        if (window.innerWidth < MOBILE_BREAKPOINT) {
            isMenuOpen.set(false);
        }
        // Remove initial load state after a small delay to ensure proper rendering
        setTimeout(() => {
            isInitialLoad = false;
        }, 100);
    });

    function handleLoginSuccess() {
        // Only open menu on desktop
        if (window.innerWidth >= MOBILE_BREAKPOINT) {
            isMenuOpen.set(true);
        } else {
            // Ensure menu stays closed on mobile
            isMenuOpen.set(false);
        }
    }

    // Add reactive statement to handle auth state changes
    $: {
        if (!$isAuthenticated) {
            // Close sidebar when logged out
            isMenuOpen.set(false);
            // Close settings if open
            settingsMenuVisible.set(false);
        }
    }

    // Add handler for chatSelected event
    function handleChatSelected(event: CustomEvent) {
        const selectedChat: Chat = event.detail.chat;
        console.log("[+page.svelte] Received chatSelected event:", selectedChat.id);
        if (activeChat) {
            activeChat.loadChat(selectedChat);
        }
    }
</script>

<div class="sidebar" class:closed={!$isMenuOpen || !$isAuthenticated}>
    {#if $isAuthenticated}
        <ActivityHistory on:chatSelected={handleChatSelected} />
    {/if}
</div>

<div class="main-content" 
    class:menu-closed={!$isMenuOpen || !$isAuthenticated}
    class:initial-load={isInitialLoad}
    class:login-mode={!$isAuthenticated}>
    <Header context="webapp" isLoggedIn={$isAuthenticated} />
    <div class="chat-container" class:menu-open={menuClass}>
        <div class="chat-wrapper">
            <ActiveChat 
                bind:this={activeChat}
                on:loginSuccess={handleLoginSuccess}
            />
        </div>
        <div class="settings-wrapper">
            <Settings isLoggedIn={$isAuthenticated} />
        </div>
    </div>
</div>

<!-- Footer outside main content -->
{#if !$isAuthenticated}
<div class="footer-wrapper" transition:fade>
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
        /* Change from fixed to absolute positioning when in login mode */
        position: fixed;
        left: calc(var(--sidebar-width) + var(--sidebar-margin));
        top: 0;
        right: 0;
        bottom: 0;
        background-color: var(--color-grey-0);
        z-index: 10;
        transition: left 0.3s ease, transform 0.3s ease;
    }

    /* Add new login mode styles */
    .main-content.login-mode {
        position: absolute;
        bottom: auto; /* Remove bottom constraint */
        min-height: 100vh; /* Ensure it takes at least full viewport height */
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

    /* Add specific height for login mode */
    .main-content.login-mode .chat-container {
        height: max(var(--chat-container-min-height), calc(100vh - 90px));
        height: max(var(--chat-container-min-height), calc(100dvh - 90px));
        min-height: max(var(--chat-container-min-height), calc(100vh - 90px));
        min-height: max(var(--chat-container-min-height), calc(100dvh - 90px));
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
        }

        /* When menu is open, slide main content right */
        .main-content:not(.menu-closed) {
            transform: translateX(100%);
        }

        /* When menu is closed, keep main content over sidebar */
        .main-content.menu-closed {
            left: 0;
            transform: translateX(0);
        }

        .main-content.login-mode {
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
        padding-top: calc(100vh + 90px); /* Push footer below viewport initially */
    }
</style>
