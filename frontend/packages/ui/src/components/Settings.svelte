<script lang="ts">
    import { get } from 'svelte/store';
    import { fly, fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { text } from '@repo/ui';
    import { panelState } from '../stores/panelStateStore';
    import { isMobileView } from '../stores/uiStateStore';
    import { isSignupSettingsStep, isInSignupProcess, isLoggingOut, currentSignupStep } from '../stores/signupState';
    import { userProfile } from '../stores/userProfile';
    // Import the new components
    import SettingsHeader from './settings/SettingsHeader.svelte';
    import SettingsContent from './settings/SettingsContent.svelte';
    import SettingsFooter from './settings/SettingsFooter.svelte';

    // Props for user and team information
    export let isLoggedIn = false;

    // Reactive variables
    // Only show settings icon when:
    // 1. User is logged in but not in signup process, OR
    // 2. User is in signup process AND we're at step 7 or higher (isSignupSettingsStep)
    $: showSettingsIcon = (isLoggedIn && !$isInSignupProcess && !$isLoggingOut) ||
                          (isLoggedIn && $isInSignupProcess && $isSignupSettingsStep);

    $: isInSignupMode = $isInSignupProcess;

    // State to track active submenu view and transition direction
    let activeSettingsView = 'main';
    let direction = 'forward';

    // Function to handle navigation events from child components
    function handleNavigateSettings(event) {
        const { settingsPath, direction: newDirection } = event.detail;
        direction = newDirection;
        activeSettingsView = settingsPath;

        // Note: Scroll to top is handled in SettingsContent
        // Note: Profile container class is handled reactively in Settings.svelte based on panelState
    }

    // Handler for profile click to show menu
    function toggleMenu() {
        if ($panelState.isSettingsOpen) {
            panelState.closeSettings();
            // Reset internal view state when closing via toggle button
            // This should reset activeSettingsView to 'main'
            activeSettingsView = 'main';
            direction = 'backward'; // Assume backward transition when closing
        } else {
            panelState.openSettings();
            // Reset to main view when opening
            activeSettingsView = 'main';
            direction = 'forward'; // Assume forward transition when opening
        }
    }

    // Handler for quick setting toggled event from SettingsContent
    function handleQuickSettingToggled(event) {
        const { toggleName, isChecked } = event.detail;
        console.debug(`[Settings.svelte] Quick setting toggled: ${toggleName} is ${isChecked}`);
        // TODO: Handle state update or action dispatch based on toggleName and isChecked
    }

    // Click outside handler (moved from Settings.svelte)
    function handleClickOutside(event) {
        // Use isMobileView store directly
        if (get(isMobileView)) { // Use get() for one-time read if not subscribed via $
            const settingsMenu = document.querySelector('.settings-menu');
            const profileContainer = document.querySelector('.profile-container');

            // Check if the click is within the settings menu or any of its child components
            // This prevents the menu from closing when clicking on nested setting items
            if (settingsMenu &&
                profileContainer &&
                !settingsMenu.contains(event.target) &&
                !profileContainer.contains(event.target)) {
                panelState.closeSettings(); // Use central store action
                // Note: Resetting internal view state will be handled by SettingsContent or its children
            }
        }
    }

    // Add click outside listener on mount
    import { onMount } from 'svelte';
    onMount(() => {
        document.addEventListener('click', handleClickOutside);
        return () => {
            document.removeEventListener('click', handleClickOutside);
        };
    });

    // Update DOM elements opacity and classes based on menu state (moved from Settings.svelte)
    $: if (typeof window !== 'undefined') {
        const activeChatContainer = document.querySelector('.active-chat-container');
        if (activeChatContainer) {
            // Use $panelState.isSettingsOpen and $isMobileView
            // Use $isMobileView directly here as it's a readable store from uiStateStore
            if ($isMobileView && $panelState.isSettingsOpen) {
                activeChatContainer.classList.add('dimmed');
            } else {
                activeChatContainer.classList.remove('dimmed');
            }
        }

        const chatContainer = document.querySelector('.chat-container');
        if (chatContainer) {
            // Use $panelState.isSettingsOpen for class binding
            if ($panelState.isSettingsOpen) {
                 chatContainer.classList.add('menu-open');
            } else {
                 chatContainer.classList.remove('menu-open');
            }
        }
    }

</script>

<div class="settings-container" class:signup-mode={isInSignupMode}>
    {#if showSettingsIcon}
        <button
            type="button"
            class="profile-container"
            class:active={$panelState.isSettingsOpen}
            on:click={toggleMenu}
            aria-haspopup="true"
            aria-expanded={$panelState.isSettingsOpen}
            aria-label={$text('settings.open_settings_menu.text')}
        >
            {#if $userProfile.profile_image_url}
                <img src={$userProfile.profile_image_url} alt="Profile" class="profile-image" />
            {:else}
                <div class="profile-placeholder">
                    <span class="icon icon_user"></span>
                </div>
            {/if}
        </button>
    {/if}

    {#if $panelState.isSettingsOpen}
        <div
            class="settings-menu"
            class:visible={$panelState.isSettingsOpen}
            transition:fly={{ x: 20, duration: 300, easing: cubicOut }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-menu-title"
        >
            <SettingsHeader on:navigateSettings={handleNavigateSettings} on:closeSettings={panelState.closeSettings} />
            <SettingsContent on:navigateSettings={handleNavigateSettings} on:quickSettingToggled={handleQuickSettingToggled} />
            <SettingsFooter />
        </div>
    {/if}
</div>

<style>
    /* Styles for profile icon and settings menu container */
    .settings-container {
        /* Positioning and z-index for the whole settings area */
        position: fixed;
        top: 10px;
        right: 10px;
        z-index: 1005; /* Ensure it's above most other content */
    }

    .profile-container {
        all: unset;
        width: 57px;
        height: 57px;
        border-radius: 50%;
        cursor: pointer;
        transition: transform 0.4s cubic-bezier(0.215, 0.61, 0.355, 1), opacity 0.3s ease;
        opacity: 1;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); /* Add shadow for better visibility */
        display: flex; /* Use flexbox for centering content */
        align-items: center;
        justify-content: center;
        background-color: var(--color-grey-20); /* Add a background color */
    }

    .profile-container.active {
         /* Optional: Add a visual indicator when active */
         outline: 2px solid var(--color-primary);
         outline-offset: 2px;
    }

    .profile-image {
        width: 100%;
        height: 100%;
        border-radius: 50%;
        object-fit: cover; /* Ensure image covers the container */
    }

    .profile-placeholder {
        width: 100%;
        height: 100%;
        border-radius: 50%;
        background-color: var(--color-grey-40); /* Placeholder background */
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .profile-placeholder .icon {
        font-size: 32px; /* Adjust icon size */
        color: var(--color-grey-0); /* Icon color */
    }

    .settings-menu {
        background-color: var(--color-grey-20);
        height: 100%; /* Will be overridden by fixed positioning on mobile */
        width: 0px; /* Starts closed */
        border-radius: 17px;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        display: flex;
        flex-direction: column;
        overflow: hidden; /* Hide content when closed */
        transition: width 0.3s ease;
        z-index: 1001; /* Below profile icon, above main content */
        position: absolute; /* Position relative to settings-container */
        top: 0;
        right: 0;
        bottom: 0;
    }

    @media (max-width: 1100px) {
        .settings-menu {
            position: fixed; /* Use fixed positioning on mobile */
            right: 20px;
            top: 80px;
            bottom: 25px;
            height: auto; /* Adjust height for fixed positioning */
            z-index: 1000; /* Adjust z-index for mobile overlay */
            visibility: hidden; /* Hide by default on mobile */
        }

        .settings-menu.visible {
            visibility: visible;
            z-index: 1006; /* Higher than profile-container-wrapper on mobile */
        }
    }

    .settings-menu.visible {
        width: 323px; /* Open width */
        visibility: visible; /* Make visible when open */
    }

    /* Styles for dimming the active chat container */
    :global(.active-chat-container) {
        transition: opacity 0.3s ease;
    }

    :global(.active-chat-container.dimmed) {
        opacity: 0.3;
    }

    /* Styles for adjusting chat container margin when settings is open */
    :global(.chat-container) {
        transition: gap 0.3s ease; /* Keep existing transition */
    }

    /* Only apply gap on larger screens */
    @media (min-width: 1100px) {
        :global(.chat-container.menu-open) {
            gap: 20px;
        }
    }

    /* Ensure no gap on mobile */
    @media (max-width: 1099px) {
        :global(.chat-container.menu-open) {
            gap: 0px;
        }
    }
</style>