<script>
    import { isMenuOpen } from '@website-lib/stores/menuState';
    import ActivityHistory from '@website-components/activity_history/ActivityHistory.svelte';
    import ActiveChat from '@website-components/ActiveChat.svelte';
    import Header from '@website-components/Header.svelte';
    import Settings from '@website-components/Settings.svelte';
    import { _ } from 'svelte-i18n'; // Import the translation function
    import { isAuthenticated } from '@website-lib/stores/authState';
    import { fade } from 'svelte/transition';

    // Subscribe to settings menu visibility state
    import { settingsMenuVisible, isMobileView } from '@website-components/Settings.svelte';
    import { onMount } from 'svelte';
    import Footer from '@website-components/Footer.svelte';

    // Compute gap class based on menu state and view
    $: menuClass = $settingsMenuVisible && !$isMobileView ? 'menu-open' : '';
    $: sidebarClass = $isMenuOpen ? 'open' : 'closed';

    // Add mobile breakpoint
    const MOBILE_BREAKPOINT = 730;
    
    // Handle initial sidebar state based on auth
    $: if ($isAuthenticated) {
        // Only open sidebar on desktop view when authenticated
        if (window.innerWidth >= MOBILE_BREAKPOINT) {
            isMenuOpen.set(true);
        } else {
            isMenuOpen.set(false);
        }
    } else {
        isMenuOpen.set(false);
    }

    // Add flag to control initial load animation
    let isInitialLoad = true;
    
    onMount(() => {
        if (window.innerWidth < MOBILE_BREAKPOINT) {
            isMenuOpen.set(false);
        }
        // Set initial load to false after a brief delay to prevent animation
        setTimeout(() => {
            isInitialLoad = false;
        }, 100);
    });

    function handleLoginSuccess() {
        // Only open sidebar on desktop view
        if (window.innerWidth >= MOBILE_BREAKPOINT) {
            isMenuOpen.set(true);
        } else {
            // Ensure sidebar is closed on mobile after login
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

    // Add transition state for footer
    $: footerClass = $isAuthenticated ? 'footer-hidden' : 'footer-visible';
</script>

<div class="page-container">
    <div class="sidebar" class:closed={!$isMenuOpen || !$isAuthenticated}>
        {#if $isAuthenticated}
            <ActivityHistory />
        {/if}
    </div>

    <div class="main-content" 
        class:menu-closed={!$isMenuOpen || !$isAuthenticated}
        class:no-transition={isInitialLoad}>
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

    <!-- Footer outside main content -->
    {#if !$isAuthenticated}
        <div class="footer-wrapper" transition:fade>
            <Footer />
        </div>
    {/if}
</div>

<style>
    :root {
        --sidebar-width: 325px;
        --sidebar-margin: 10px;
    }

    .page-container {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
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

        transition: opacity 0.3s ease;
        opacity: 1;
    }

    .sidebar.closed {
        opacity: 0;
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
        height: 100vh;
        margin-left: calc(var(--sidebar-width) + var(--sidebar-margin));
        background-color: var(--color-grey-0);
        z-index: 10;
        transition: margin-left 0.3s ease;
        overflow-y: auto;
    }

    .main-content.menu-closed {
        margin-left: var(--sidebar-margin);
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
        height: calc(100% - 90px);
        display: flex;
        flex-direction: row;
        gap: 0px;
        padding: 10px;
        padding-right: 20px;
        overflow-y: auto;
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
        transition: margin-left 0.3s ease;
    }

    /* Add new style to disable transitions during initial load */
    .no-transition {
        transition: none !important;
    }

    /* Add footer transition styles */
    .footer-wrapper {
        transition: height 0.3s ease, opacity 0.3s ease;
        height: auto;
        opacity: 1;
        overflow: hidden;
    }

    .footer-wrapper.hidden {
        height: 0;
        opacity: 0;
    }
</style>
