<script>
    import { isMenuOpen } from '../../../website/src/lib/stores/menuState';
    import ActivityHistory from '@website-components/activity_history/ActivityHistory.svelte';
    import ActiveChat from '@website-components/ActiveChat.svelte';
    import Header from '@website-components/Header.svelte';
    import Settings from '@website-components/Settings.svelte';
    import { _ } from 'svelte-i18n'; // Import the translation function

    // Subscribe to settings menu visibility state
    import { settingsMenuVisible, isMobileView } from '@website-components/Settings.svelte';

    // Compute gap class based on menu state and view
    $: menuClass = $settingsMenuVisible && !$isMobileView ? 'menu-open' : '';
    $: sidebarClass = $isMenuOpen ? 'open' : 'closed';
</script>

<div class="sidebar" class:closed={!$isMenuOpen}>
    <ActivityHistory />
</div>

<div class="main-content" class:menu-closed={!$isMenuOpen}>
    <Header context="webapp" />
    <div class="chat-container" class:menu-open={menuClass}>
        <ActiveChat />
        <div class="settings-wrapper">
            <Settings />
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
        transition: left 0.3s ease;
    }

    .main-content.menu-closed {
        left: 0;
        
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
        height: calc(100% - 80px);
        gap: 0px;
        padding: 10px;
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
</style>
