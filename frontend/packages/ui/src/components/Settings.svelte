<script lang="ts">
    import { get, writable } from 'svelte/store';
    import { onMount } from 'svelte';
    import { fly, fade } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { text } from '@repo/ui';
    import { panelState } from '../stores/panelStateStore';
    import { isMobileView } from '../stores/uiStateStore';
    import { isSignupSettingsStep, isInSignupProcess, isLoggingOut, currentSignupStep } from '../stores/signupState';
    import { userProfile } from '../stores/userProfile';
    import { settingsDeepLink } from '../stores/settingsDeepLinkStore';
    import { authStore, isCheckingAuth } from '../stores/authStore';
    import { isMenuOpen } from '../stores/menuState'; // Needed for logout

    // Import the new components
    import SettingsHeader from './settings/SettingsHeader.svelte';
    import SettingsContent from './settings/SettingsContent.svelte';
    import SettingsFooter from './settings/SettingsFooter.svelte';

    // Import quick settings store (assuming one exists or will be created)
    // import { teamEnabled, incognitoEnabled, guestEnabled } from '../stores/quickSettingsStore'; // Example
    // For now, manage locally and update old stores if they exist
    import { teamEnabled } from '../stores/teamStore'; // Assuming this exists based on old code

    // Props for user and team information
    export let isLoggedIn = false;

    // --- Centralized State ---
    let activeSettingsView: string = 'main';
    let direction: 'forward' | 'backward' = 'forward'; // Explicit type
    let activeSubMenuIcon: string = '';
    let activeSubMenuTitle: string = '';

    // Quick Settings State (managed here, update relevant stores)
    let isTeamEnabled: boolean = get(teamEnabled); // Initialize from store & type explicitly
    let isIncognitoEnabled: boolean = false; // Type explicitly
    let isGuestEnabled: boolean = false; // Type explicitly

    // --- Refs ---
    let profileContainerWrapper;
    let profileContainer;
    let settingsMenuElement; // Ref for the settings menu itself

    // --- Reactive Variables ---
    $: showSettingsIcon = (isLoggedIn && !$isInSignupProcess && !$isLoggingOut) ||
                          (isLoggedIn && $isInSignupProcess && $isSignupSettingsStep);
    $: isInSignupMode = $isInSignupProcess;
    $: profile_image_url = $userProfile.profile_image_url;

    // --- Event Handlers ---

    // Handle navigation events from children
    function handleNavigate(event) {
        const { settingsPath, direction: newDirection, icon, title } = event.detail;

        // Prevent navigation if already on the target path
        if (settingsPath === activeSettingsView) return;

        direction = newDirection;
        activeSettingsView = settingsPath;
        activeSubMenuIcon = icon || '';
        activeSubMenuTitle = title || '';

        // Reset scroll is handled within SettingsContent via #key block
    }

    // Handle quick setting toggles from SettingsContent
    function handleToggleQuickSetting(event) {
        const { toggleName, isChecked } = event.detail;
        console.debug(`[Settings.svelte] Quick setting toggled: ${toggleName} is ${isChecked}`);

        switch(toggleName) {
            case 'team':
                isTeamEnabled = isChecked;
                teamEnabled.set(isChecked); // Update the store
                break;
            case 'incognito':
                isIncognitoEnabled = isChecked;
                // TODO: Update relevant store or perform action if needed
                break;
            case 'guest':
                isGuestEnabled = isChecked;
                // TODO: Update relevant store or perform action if needed
                break;
        }
    }

    // Handle logout event from SettingsContent
    async function handleLogout() {
        try {
            isLoggingOut.set(true);
            isInSignupProcess.set(false); // Ensure signup process is exited

            await authStore.logout({
                beforeServerLogout: () => {
                    isCheckingAuth.set(false); // Ensure auth check stops
                },
                afterServerLogout: async () => {
                    // Reset scroll position (handled by SettingsContent #key)
                    // Close the settings menu via panelState
                    panelState.closeSettings();
                    // Small delay to allow settings menu to close visually
                    await new Promise(resolve => setTimeout(resolve, 300));
                    // Close the sidebar menu if it exists and is open
                    isMenuOpen.set(false);
                    // Small delay for sidebar animation
                    await new Promise(resolve => setTimeout(resolve, 300));
                }
            });

            console.debug("[Settings.svelte] Logout successful.");

        } catch (error) {
            console.error('[Settings.svelte] Error during logout:', error);
            // Attempt to gracefully handle error, maybe show a notification
            // Ensure state is reset even on error
            authStore.logout(); // Force reset state in store
        } finally {
            // This block executes whether the try block succeeded or failed.
            isLoggingOut.set(false); // CRITICAL: Ensure isLoggingOut is always reset
            isCheckingAuth.set(false); // Ensure auth check state is also reset
            isInSignupProcess.set(false); // Ensure signup state is reset
            console.debug("[Settings.svelte] Logout process finished (finally block). isLoggingOut set to false.");

            // Reset internal view state after logout actions complete
            resetInternalViewState();
        }
    }

    // Handler for profile icon click / toggle button
    function toggleMenu() {
        if ($panelState.isSettingsOpen) {
            panelState.closeSettings();
            // Reset internal view state when closing via toggle button
            resetInternalViewState();
        } else {
            panelState.openSettings();
            // Reset to main view when opening
            resetInternalViewState(); // Ensures clean state on open
            direction = 'forward'; // Set direction for opening animation
        }
    }

    // Helper to reset internal view state
    function resetInternalViewState() {
        activeSettingsView = 'main';
        direction = 'backward'; // Default direction when resetting/closing
        activeSubMenuIcon = '';
        activeSubMenuTitle = '';
    }

    // --- Lifecycle & Effects ---

    // Click outside handler
    function handleClickOutside(event) {
        if (get(isMobileView) && $panelState.isSettingsOpen) {
            // Check if the click is outside the settings menu AND the profile icon wrapper
            if (settingsMenuElement && profileContainerWrapper &&
                !settingsMenuElement.contains(event.target) &&
                !profileContainerWrapper.contains(event.target))
            {
                panelState.closeSettings();
                resetInternalViewState();
            }
        }
    }

    onMount(() => {
        document.addEventListener('click', handleClickOutside);
        return () => {
            document.removeEventListener('click', handleClickOutside);
        };
    });

    // Update DOM elements based on menu state (dimming, etc.)
    $: if (typeof window !== 'undefined') {
        const activeChatContainer = document.querySelector('.active-chat-container');
        if (activeChatContainer) {
            if ($isMobileView && $panelState.isSettingsOpen) {
                activeChatContainer.classList.add('dimmed');
            } else {
                activeChatContainer.classList.remove('dimmed');
            }
        }

        const chatContainer = document.querySelector('.chat-container');
        if (chatContainer) {
            if ($panelState.isSettingsOpen) {
                 chatContainer.classList.add('menu-open');
            } else {
                 chatContainer.classList.remove('menu-open');
            }
        }

        // Add/Remove mobile overlay class for z-index management
        if (settingsMenuElement) {
            if ($isMobileView && $panelState.isSettingsOpen) {
                settingsMenuElement.classList.add('mobile-overlay');
            } else {
                settingsMenuElement.classList.remove('mobile-overlay');
            }
        }
    }

    // Handle deep link requests
    $: if ($settingsDeepLink && typeof window !== 'undefined') {
        const settingsPath = $settingsDeepLink;
        settingsDeepLink.set(null); // Reset immediately

        // Open the settings menu if needed
        if (!$panelState.isSettingsOpen) {
            panelState.openSettings();
            // Ensure state is reset before navigating
            resetInternalViewState();
            direction = 'forward';
        }

        // Delay navigation slightly to allow menu opening animation
        setTimeout(() => {
            const pathParts = settingsPath.split('/');
            const icon = pathParts[0];
            // Attempt to get title translation dynamically - requires $text to be ready
            let title = '';
            try {
                title = $text(`settings.${icon}.text`);
            } catch (e) {
                console.warn(`Translation key not found for settings.${icon}.text`);
                title = icon; // Fallback to key part
            }

            handleNavigate({
                detail: {
                    settingsPath,
                    direction: 'forward',
                    icon,
                    title
                }
            });
        }, 100); // Adjust delay if needed
    }

    // Reset internal state when panel is closed externally
    $: if (!$panelState.isSettingsOpen && activeSettingsView !== 'main') {
        resetInternalViewState();
    }

</script>

{#if showSettingsIcon}
    <div
        class="profile-container-wrapper"
        bind:this={profileContainerWrapper}
        in:fly={{ y: - (typeof window !== 'undefined' ? window.innerHeight / 2 + 60 : 300), x: 0, duration: 800, easing: cubicOut }}
        out:fade
    >
        <!-- Profile Icon -->
        <div
            class="profile-container"
            class:menu-open={$panelState.isSettingsOpen}
            class:hidden={$panelState.isSettingsOpen && activeSettingsView !== 'main'}
            on:click={toggleMenu}
            on:keydown={e => e.key === 'Enter' && toggleMenu()}
            role="button"
            tabindex="0"
            aria-label={$text('settings.open_settings_menu.text')}
            aria-haspopup="true"
            aria-expanded={$panelState.isSettingsOpen}
            bind:this={profileContainer}
        >
            <div
                class="profile-picture"
                style={profile_image_url ? `background-image: url(${profile_image_url})` : ''}
            >
                {#if !profile_image_url}
                    <div class="default-user-icon"></div>
                {/if}
            </div>
        </div>

        <!-- Close Icon (appears where profile icon was) -->
        <div class="close-icon-container" class:visible={$panelState.isSettingsOpen}>
            <button
                class="icon-button"
                aria-label={$text('settings.close_settings_menu.text')}
                on:click={toggleMenu}
            >
                <div class="clickable-icon icon_close"></div>
            </button>
        </div>
    </div>
{/if}

<!-- Settings Menu Panel -->
{#if $panelState.isSettingsOpen}
    <div
        class="settings-menu"
        class:visible={$panelState.isSettingsOpen}
        class:mobile={$isMobileView}
        bind:this={settingsMenuElement}
        transition:fade={{ duration: 150 }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-menu-title"
    >
        <SettingsHeader
            {activeSettingsView}
            {activeSubMenuIcon}
            {activeSubMenuTitle}
            on:navigate={handleNavigate}
            on:closeSettings={toggleMenu}
        />
        <SettingsContent
            {activeSettingsView}
            {direction}
            bind:isTeamEnabled
            bind:isIncognitoEnabled
            bind:isGuestEnabled
            on:navigate={handleNavigate}
            on:toggleQuickSetting={handleToggleQuickSetting}
            on:logout={handleLogout}
        />
        <SettingsFooter />
    </div>
{/if}


<style>
    /* --- Container and Profile Icon --- */
    .profile-container-wrapper {
        position: fixed;
        top: 10px;
        right: 10px;
        width: 57px;
        height: 57px;
        z-index: 1005;
        transition: opacity 0.3s ease;
    }

    .profile-container {
        position: absolute;
        top: 0;
        right: 0;
        width: 57px;
        height: 57px;
        border-radius: 50%;
        cursor: pointer;
        transition: transform 0.4s cubic-bezier(0.215, 0.61, 0.355, 1), opacity 0.3s ease;
        opacity: 1;
        /* background-color: var(--color-grey-20); Added in profile-picture */
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .profile-container.hidden {
        opacity: 0;
        pointer-events: none;
    }

    /* Move profile icon when menu is open (adjust values as needed) */
    .profile-container.menu-open {
        transform: translate(-265px, 120px);
        /* Opacity is handled by .hidden class */
    }

    .profile-picture {
        border-radius: 50%;
        width: 100%;
        height: 100%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-color: var(--color-grey-20);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .default-user-icon {
        width: 32px;
        height: 32px;
        -webkit-mask-image: url('@openmates/ui/static/icons/user.svg');
        mask-image: url('@openmates/ui/static/icons/user.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        background-color: var(--color-grey-60);
    }

    /* --- Close Icon --- */
    .close-icon-container {
        position: absolute;
        top: 0;
        right: 0;
        width: 57px;
        height: 57px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        visibility: hidden;
        transition: all 0.3s ease;
        z-index: 1; /* Above profile icon when visible */
    }

    .close-icon-container.visible {
        opacity: 1;
        visibility: visible;
    }

    .close-icon-container button.icon-button {
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: none;
        border: none;
        padding: 0;
        cursor: pointer;
    }

    .close-icon-container .clickable-icon {
        width: 25px;
        height: 25px;
        background-color: var(--color-grey-60); /* Adjust color as needed */
    }

    /* --- Settings Menu Panel --- */
    .settings-menu {
        background-color: var(--color-grey-20);
        height: calc(100vh - 20px); /* Adjust based on top/bottom margins */
        width: 323px; /* Fixed width when open */
        border-radius: 17px;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        display: flex;
        flex-direction: column;
        overflow: hidden; /* Prevents content overflow */
        position: fixed; /* Use fixed for consistent positioning */
        top: 10px;
        right: 10px;
        z-index: 1001; /* Below profile wrapper, above main content */
        visibility: hidden; /* Hidden by default, controlled by svelte:component */
        opacity: 0; /* For fade transition */
    }

    .settings-menu.visible {
        visibility: visible;
        opacity: 1;
    }

    @media (max-width: 1100px) {
        .settings-menu {
            right: 20px;
            top: 80px;
            bottom: 25px;
            height: auto; /* Let content determine height */
            z-index: 1000; /* Default mobile z-index */
        }

        /* Add mobile overlay style for higher z-index when open */
        .settings-menu.mobile-overlay {
            z-index: 1006 !important; /* Higher than profile-container-wrapper */
        }
    }

    /* --- Global Styles --- */
    :global(.active-chat-container) {
        transition: opacity 0.3s ease;
    }

    :global(.active-chat-container.dimmed) {
        opacity: 0.3;
        pointer-events: none; /* Prevent interaction with dimmed background */
    }

    :global(.chat-container) {
        transition: gap 0.3s ease; /* Keep existing transition */
    }

    /* Only apply gap on larger screens */
    @media (min-width: 1100px) {
        :global(.chat-container.menu-open) {
            /* Adjust gap or margin as needed */
            /* Example: margin-right: 343px; /* 323px width + 20px gap */
            gap: 20px; /* Or use gap if flexbox */
        }
    }

    /* Ensure no gap/margin adjustment on mobile */
    @media (max-width: 1099px) {
        :global(.chat-container.menu-open) {
            gap: 0px;
            /* margin-right: 0; */
        }
    }
</style>