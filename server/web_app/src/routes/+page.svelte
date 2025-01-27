<script>
    import { isMenuOpen } from '../../../website/src/lib/stores/menuState';
    import ActivityHistory from '@website-components/activity_history/ActivityHistory.svelte';
    import ActiveChat from '@website-components/ActiveChat.svelte';
    import Header from '@website-components/Header.svelte';
    import Settings from '@website-components/Settings.svelte';
    import { _ } from 'svelte-i18n'; // Import the translation function
    import { isAuthenticated } from '../../../website/src/lib/stores/authState';

    // Subscribe to settings menu visibility state
    import { settingsMenuVisible, isMobileView } from '@website-components/Settings.svelte';
    import { onMount } from 'svelte';

    // Compute gap class based on menu state and view
    $: menuClass = $settingsMenuVisible && !$isMobileView ? 'menu-open' : '';
    $: sidebarClass = $isMenuOpen ? 'open' : 'closed';

    // Add mobile breakpoint
    const MOBILE_BREAKPOINT = 730;
    
    // Handle initial sidebar state based on auth
    $: if ($isAuthenticated) {
        isMenuOpen.set(true);
    } else {
        isMenuOpen.set(false);
    }

    onMount(() => {
        if (window.innerWidth < MOBILE_BREAKPOINT) {
            isMenuOpen.set(false);
        }
    });

    function handleLoginSuccess() {
        if (window.innerWidth >= MOBILE_BREAKPOINT) {
            isMenuOpen.set(true);
        }
    }
</script>

<div class="sidebar" class:closed={!$isMenuOpen || !$isAuthenticated}>
    {#if $isAuthenticated}
        <ActivityHistory />
    {/if}
</div>

<div class="main-content" class:menu-closed={!$isMenuOpen || !$isAuthenticated}>
    <Header context="webapp" isLoggedIn={$isAuthenticated} />
    <div class="chat-container" class:menu-open={menuClass}>
        <div class="chat-wrapper">
            <ActiveChat 
                on:loginSuccess={handleLoginSuccess}
            />
        </div>
        <div class="settings-wrapper">
            <Settings isLoggedIn={$isAuthenticated} />
        </div>
    </div>
</div>

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

        /* Add scrolling for overflow content */
        overflow-y: auto;

        /* Add more pronounced inner shadow on right side for better visibility */
        box-shadow: inset -6px 0 12px -4px rgba(0, 0, 0, 0.25);

        /* Custom scrollbar styling */
        scrollbar-width: thin;
        scrollbar-color: var(--color-grey-40) transparent;

        transition: transform 0.3s ease;
    }

    .sidebar.closed {
        transform: translateX(-100%);
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
        position: fixed;
        left: calc(var(--sidebar-width) + var(--sidebar-margin));
        top: 0;
        right: 0;
        bottom: 0;
        background-color: var(--color-grey-0);
        z-index: 10;
        transition: left 0.3s ease, transform 0.3s ease;
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
        height: calc(100% - 90px);
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
        .sidebar {
            width: 100%;
            /* Ensure sidebar stays in place */
            transform: none;
        }

        .sidebar.closed {
            /* Don't translate sidebar off screen on mobile */
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
</style>
