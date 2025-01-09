<script>
    // Import the required components
    import ActivityHistory from '@website-components/ActivityHistory.svelte';
    import ActiveChat from '@website-components/ActiveChat.svelte';
    import Header from '@website-components/Header.svelte';
    import Settings from '@website-components/Settings.svelte';

    // Subscribe to settings menu visibility state
    import { settingsMenuVisible, isMobileView } from '@website-components/Settings.svelte';

    // Compute gap class based on menu state and view
    $: menuClass = $settingsMenuVisible && !$isMobileView ? 'menu-open' : '';
</script>

<div class="sidebar">
    <ActivityHistory />
</div>

<div class="main-content">
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
    }

    .main-content {
        /* Position relative to accommodate fixed sidebar */
        position: fixed;
        left: calc(var(--sidebar-width) + var(--sidebar-margin));
        top: var(--sidebar-margin);
        right: var(--sidebar-margin);
        bottom: var(--sidebar-margin);

        /* Add scrolling for overflow content */
        overflow-y: auto;
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
