<script lang="ts">
    import { get, writable } from 'svelte/store';
    import { fly, fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { text } from '@repo/ui';
    import { authStore, isCheckingAuth } from '../stores/authStore';
    import { panelState } from '../stores/panelStateStore';
    import { isMobileView } from '../stores/uiStateStore';
    import { isSignupSettingsStep, isInSignupProcess, isLoggingOut, currentSignupStep } from '../stores/signupState';
    import { userProfile } from '../stores/userProfile';
    import { settingsDeepLink } from '../stores/settingsDeepLinkStore'; // Keep for potential deep link handling here
    import { settingsNavigationStore } from '../stores/settingsNavigationStore'; // Keep for navigation state

    import { createEventDispatcher, type SvelteComponent } from 'svelte'; // Added SvelteComponent
    const dispatch = createEventDispatcher();

    // Import modular components
    import SettingsFooter from './settings/SettingsFooter.svelte'; // Keep if footer is part of content area
    import CurrentSettingsPage from './settings/CurrentSettingsPage.svelte';

    // Import all settings components
    import SettingsInterface from './settings/SettingsInterface.svelte';
    import SettingsPrivacy from './settings/SettingsPrivacy.svelte';
    import SettingsUser from './settings/SettingsUser.svelte';
    import SettingsUsage from './settings/SettingsUsage.svelte';
    import SettingsBilling from './settings/SettingsBilling.svelte';
    import SettingsApps from './settings/SettingsApps.svelte';
    import SettingsMates from './settings/SettingsMates.svelte';
    import SettingsShared from './settings/SettingsShared.svelte';
    import SettingsMessengers from './settings/SettingsMessengers.svelte';
    import SettingsDevelopers from './settings/SettingsDevelopers.svelte';
    import SettingsServer from './settings/SettingsServer.svelte';
    import SettingsItem from './SettingsItem.svelte';
    import SettingsLanguage from './settings/interface/SettingsLanguage.svelte';
    import SettingsSoftwareUpdate from './settings/server/SettingsSoftwareUpdate.svelte';

    // State for toggles (These might be better in a separate store or passed down)
    let isTeamEnabled = true;
    let isIncognitoEnabled = false;
    let isGuestEnabled = false;
    // Removed isOfflineEnabled as it's not used and will be removed from template

    // Add reference to settings content element
    let settingsContentElement;

    // Define base settingsViews map for component mapping
    const allSettingsViews: Record<string, any> = {
        'privacy': SettingsPrivacy,
        'user': SettingsUser,
        'usage': SettingsUsage,
        'billing': SettingsBilling,
        'apps': SettingsApps,
        'mates': SettingsMates,
        'shared': SettingsShared,
        'messengers': SettingsMessengers,
        'developers': SettingsDevelopers,
        'interface': SettingsInterface,
        'server': SettingsServer,
        'interface/language': SettingsLanguage,
        'server/software-update': SettingsSoftwareUpdate
    };

    // Reactive settingsViews that filters out server options for non-admins
    $: settingsViews = Object.entries(allSettingsViews).reduce((filtered, [key, component]) => {
        // Include all non-server settings, or include server settings if user is admin
        if (!key.startsWith('server') || $userProfile.is_admin) {
            filtered[key] = component;
        }
        return filtered;
    }, {} as Record<string, typeof SvelteComponent>); // Corrected type assertion

    // State to track active submenu view (This state should likely be managed higher up or in a store)
    let activeSettingsView = 'main';
    let direction = 'forward'; // Keep direction for transitions

    // Add reference for content height calculation
    let menuItemsCount = 0;
    let calculatedContentHeight = 0;

    // Calculate the content height based on the number of menu items
    $: {
        const baseHeight = 200; // Base height for user info and padding
        const itemHeight = 50; // Average height per menu item
        calculatedContentHeight = baseHeight + (menuItemsCount * itemHeight);
    }

    // Function to set active settings view with transitions (This will need to receive events from header/items)
    // This function should update the activeSettingsView state
    function handleNavigateSettings(event) {
         const { settingsPath, direction: newDirection } = event.detail;
         direction = newDirection;
         activeSettingsView = settingsPath;

         // Scroll to the top of the settings content when navigating
         if (settingsContentElement) {
             settingsContentElement.scrollTo({
                 top: 0,
                 behavior: 'smooth'
             });
         }
    }


    // Handler for quicksettings menu item clicks (This should dispatch an event up)
    function handleQuickSettingClick(event) {
        const { toggleName } = event.detail;

        switch(toggleName) {
            case 'team':
                isTeamEnabled = !isTeamEnabled;
                // teamEnabled.set(isTeamEnabled); // This should be handled by a store or parent
                break;
            case 'incognito':
                isIncognitoEnabled = !isIncognitoEnabled;
                break;
            case 'guest':
                isGuestEnabled = !isGuestEnabled;
                break;
            // Removed offline case
        }
        // Dispatch event to parent
        dispatch('quickSettingToggled', { toggleName, isChecked: event.detail.isChecked });
    }

    // Handler for logout (This should dispatch an event up)
    async function handleLogout() {
        // Dispatch event to parent to handle logout logic
        // dispatch('logout');
        try {
            isLoggingOut.set(true);
            isInSignupProcess.set(false); // Ensure signup process is exited

            await authStore.logout({
                beforeServerLogout: () => {
                    isCheckingAuth.set(false); // Ensure auth check stops
                    // Rely on reactive block in +page.svelte triggered by isLoggingOut=true
                },
                afterServerLogout: async () => {
                    // Reset scroll position after successful logout actions
                    if (settingsContentElement) {
                        settingsContentElement.scrollTop = 0;
                    }
                }
            });

            console.debug("[SettingsContent.svelte] Logout successful.");

        } catch (error) {
            console.error('[SettingsContent.svelte] Error during logout:', error);
            // Error handling: Log error, UI state reset happens in finally block.
            // Do NOT call authStore.logout() again here.
        } finally {
            // This block executes whether the try block succeeded or failed.
            isLoggingOut.set(false); // CRITICAL: Ensure isLoggingOut is always reset
            isCheckingAuth.set(false); // Ensure auth check state is also reset
            isInSignupProcess.set(false); // Ensure signup state is reset
            console.debug("[SettingsContent.svelte] Logout process finished (finally block). isLoggingOut set to false.");

            // REMOVED explicit menu closing. Rely solely on reactive logic in +page.svelte
            // triggered by isLoggingOut changing from true to false.
        }
    }

    // Need to handle receiving navigation events from SettingsHeader
    // Need to handle receiving quick setting toggle events from SettingsItem
    // Need to handle receiving logout event from logout button

    // Lifecycle hook for potential deep link handling or initial view setting
    import { onMount } from 'svelte';
    onMount(() => {
        // TODO: Handle deep links here if this component is responsible
        // Example: Check window.location.hash and call handleNavigateSettings
    });

</script>

<div class="settings-content" bind:this={settingsContentElement}>
    {#key activeSettingsView}
        <div
            class="settings-view"
            in:fly={{ x: direction === 'forward' ? 100 : -100, duration: 300, easing: cubicOut }}
            out:fly={{ x: direction === 'forward' ? -100 : 100, duration: 300, easing: cubicOut }}
        >
            {#if activeSettingsView === 'main'}
                <div class="main-settings-view">
                    <div class="user-info">
                        {#if $userProfile.profile_image_url}
                            <img src={$userProfile.profile_image_url} alt="Profile" class="profile-image-large" />
                        {:else}
                            <div class="profile-placeholder-large">
                                <span class="icon icon_user"></span>
                            </div>
                        {/if}
                        <div class="user-details">
                            <span class="username">{$userProfile.username || 'Loading...'}</span>
                            {#if $userProfile.credits !== undefined && $userProfile.credits !== null}
                                <span class="credits">{$userProfile.credits} {$text('settings.credits.text')}</span>
                            {/if}
                        </div>
                    </div>

                    <div class="quick-settings">
                        <SettingsItem
                            icon="icon_team"
                            title={$text('settings.team.text')}
                            hasToggle={true}
                            bind:checked={isTeamEnabled}
                            on:toggle={() => handleQuickSettingClick({ detail: { toggleName: 'team', isChecked: isTeamEnabled } })}
                        />
                        <SettingsItem
                            icon="icon_incognito"
                            title={$text('settings.incognito.text')}
                            hasToggle={true}
                            bind:checked={isIncognitoEnabled}
                            on:toggle={() => handleQuickSettingClick({ detail: { toggleName: 'incognito', isChecked: isIncognitoEnabled } })}
                        />
                        <SettingsItem
                            icon="icon_guest"
                            title={$text('settings.guest.text')}
                            hasToggle={true}
                            bind:checked={isGuestEnabled}
                            on:toggle={() => handleQuickSettingClick({ detail: { toggleName: 'guest', isChecked: isGuestEnabled } })}
                        />
                        <!-- Removed Offline Quick Setting -->
                    </div>

                    <div class="settings-menu-items" bind:clientHeight={menuItemsCount}>
                        {#each Object.entries(settingsViews) as [key, component]}
                            {#if !key.includes('/')}
                                <SettingsItem
                                    icon={`icon_${key}`}
                                    title={$text(`settings.${key}.text`)}
                                    on:click={() => handleNavigateSettings({ detail: { settingsPath: key, direction: 'forward', icon: key, title: $text(`settings.${key}.text`) } })}
                                />
                            {/if}
                        {/each}
                    </div>

                    <div class="logout-section">
                        <button class="logout-button" on:click={handleLogout}>
                            <span class="icon icon_logout"></span>
                            {$text('settings.logout.text')}
                        </button>
                    </div>
                </div>
            {:else}
                <CurrentSettingsPage
                    activeSettingsView={activeSettingsView}
                    direction={direction}
                    username={$userProfile.username}
                    isInSignupMode={$isInSignupProcess}
                    settingsViews={settingsViews}
                    isIncognitoEnabled={isIncognitoEnabled}
                    isGuestEnabled={isGuestEnabled}
                    on:openSettings={handleNavigateSettings}
                />
            {/if}
        </div>
    {/key}
</div>

<!-- Settings Footer Component (This should be in Settings.svelte or passed down) -->
<!-- <SettingsFooter /> -->

<style>
    .settings-content {
        display: flex;
        flex-direction: column;
        flex: 1;
        overflow-y: auto;
        padding: 16px; /* Add padding */
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }

    .settings-content:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .settings-content::-webkit-scrollbar {
        width: 8px;
    }

    .settings-content::-webkit-scrollbar-track {
        background: transparent;
    }

    .settings-content::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid var(--color-grey-20);
        transition: background-color 0.2s ease;
    }

    .settings-content:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .settings-content::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }

    .settings-view {
        /* Styles for the transitioning views */
    }

    .main-settings-view {
        display: flex;
        flex-direction: column;
        gap: 20px; /* Space between sections */
    }

    .user-info {
        display: flex;
        align-items: center;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--color-grey-30);
    }

    .profile-image-large {
        width: 64px; /* Larger size for user info */
        height: 64px;
        border-radius: 50%;
        object-fit: cover;
        margin-right: 12px;
    }

    .profile-placeholder-large {
        width: 64px;
        height: 64px;
        border-radius: 50%;
        background-color: var(--color-grey-40);
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 12px;
    }

    .profile-placeholder-large .icon {
        font-size: 40px; /* Adjust icon size */
        color: var(--color-grey-0);
    }

    .user-details {
        display: flex;
        flex-direction: column;
    }

    .username {
        font-weight: 600;
        font-size: 18px; /* Larger font size */
        color: var(--color-grey-90);
        margin-bottom: 4px;
    }

    .credits {
        font-size: 15px; /* Slightly larger font size */
        color: var(--color-grey-60);
    }

    .quick-settings {
        display: flex;
        flex-direction: column;
        gap: 10px; /* Space between quick settings items */
        padding-bottom: 20px;
        border-bottom: 1px solid var(--color-grey-30);
    }

    .settings-menu-items {
        display: flex;
        flex-direction: column;
        gap: 10px; /* Space between settings menu items */
        padding-bottom: 20px;
        border-bottom: 1px solid var(--color-grey-30);
    }

    .logout-section {
        padding-top: 20px;
        display: flex;
        justify-content: center; /* Center the logout button */
    }

    .logout-button {
        all: unset; /* Remove default button styles */
        background-color: var(--color-error); /* Red color for logout */
        color: var(--color-white);
        padding: 10px 20px;
        border-radius: 8px;
        cursor: pointer;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 8px; /* Space between icon and text */
        transition: background-color 0.2s ease;
    }

    .logout-button:hover {
        background-color: var(--color-error-dark); /* Darker red on hover */
    }

    .logout-button .icon {
        font-size: 18px; /* Adjust icon size */
    }
</style>