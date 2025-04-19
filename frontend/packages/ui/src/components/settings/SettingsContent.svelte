<script lang="ts">
    import { get, writable } from 'svelte/store';
    import { fly, fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { text } from '@repo/ui';
    import { authStore, isCheckingAuth } from '../../stores/authStore';
    import { panelState } from '../../stores/panelStateStore';
    import { isMobileView } from '../../stores/uiStateStore';
    import { isSignupSettingsStep, isInSignupProcess, isLoggingOut, currentSignupStep } from '../../stores/signupState';
    import { userProfile } from '../../stores/userProfile';
    import { settingsDeepLink } from '../../stores/settingsDeepLinkStore'; // Keep for potential deep link handling here
    import { settingsNavigationStore } from '../../stores/settingsNavigationStore'; // Keep for navigation state

    import { createEventDispatcher, type SvelteComponent, onMount } from 'svelte'; // Added SvelteComponent, onMount
    const dispatch = createEventDispatcher<{
        navigate: { settingsPath: string; direction: 'forward' | 'backward'; icon?: string; title?: string };
        toggleQuickSetting: { toggleName: string; isChecked: boolean };
        logout: void;
    }>();

    // --- Props ---
    export let activeSettingsView: string = 'main';
    export let direction: 'forward' | 'backward' = 'forward';
    export let isTeamEnabled: boolean = true; // Bindable prop
    export let isIncognitoEnabled: boolean = false; // Bindable prop
    export let isGuestEnabled: boolean = false; // Bindable prop

    // --- Imports ---
    import CurrentSettingsPage from './CurrentSettingsPage.svelte';

    // Import all settings components
    import SettingsInterface from './SettingsInterface.svelte';
    import SettingsPrivacy from './SettingsPrivacy.svelte';
    import SettingsUser from './SettingsUser.svelte';
    import SettingsUsage from './SettingsUsage.svelte';
    import SettingsBilling from './SettingsBilling.svelte';
    import SettingsApps from './SettingsApps.svelte';
    import SettingsMates from './SettingsMates.svelte';
    import SettingsShared from './SettingsShared.svelte';
    import SettingsMessengers from './SettingsMessengers.svelte';
    import SettingsDevelopers from './SettingsDevelopers.svelte';
    import SettingsServer from './SettingsServer.svelte';
    import SettingsItem from '../SettingsItem.svelte';
    import SettingsLanguage from './interface/SettingsLanguage.svelte';
    import SettingsSoftwareUpdate from './server/SettingsSoftwareUpdate.svelte';

    // Removed local toggle state, using props now

    // --- Refs ---
    let settingsContentElement: HTMLDivElement;

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

    // Removed local activeSettingsView and direction state, using props now

    // --- Internal State ---
    let menuItemsCount = 0; // Used for footer height calculation, keep internal
    let calculatedContentHeight = 0; // Derived internal state

    // Calculate the content height based on the number of menu items
    $: {
        const baseHeight = 200; // Base height for user info and padding
        const itemHeight = 50; // Average height per menu item
        calculatedContentHeight = baseHeight + (menuItemsCount * itemHeight);
    }

    // --- Event Handlers ---

    // Dispatch navigation events UP to Settings.svelte
    function dispatchNavigate(settingsPath: string, direction: 'forward' | 'backward', icon?: string, title?: string) {
        dispatch('navigate', { settingsPath, direction, icon, title });
        // Scroll is handled by #key block below
    }

    // Dispatch quick setting toggle events UP to Settings.svelte
    function dispatchToggleQuickSetting(toggleName: string, isChecked: boolean) {
        dispatch('toggleQuickSetting', { toggleName, isChecked });
    }

    // Dispatch logout event UP to Settings.svelte
    function dispatchLogout() {
        dispatch('logout');
    }

    // --- Lifecycle ---
    // No onMount needed for deep links here, handled by parent

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
                            on:toggle={(e) => dispatchToggleQuickSetting('team', e.detail)}
                        />
                        <SettingsItem
                            icon="icon_incognito"
                            title={$text('settings.incognito.text')}
                            hasToggle={true}
                            bind:checked={isIncognitoEnabled}
                            on:toggle={(e) => dispatchToggleQuickSetting('incognito', e.detail)}
                        />
                        <SettingsItem
                            icon="icon_guest"
                            title={$text('settings.guest.text')}
                            hasToggle={true}
                            bind:checked={isGuestEnabled}
                            on:toggle={(e) => dispatchToggleQuickSetting('guest', e.detail)}
                        />
                        <!-- Removed Offline Quick Setting -->
                    </div>

                    <div class="settings-menu-items" bind:clientHeight={menuItemsCount}>
                        {#each Object.entries(settingsViews) as [key, component]}
                            {#if !key.includes('/')}
                                <SettingsItem
                                    icon={`icon_${key}`}
                                    title={$text(`settings.${key}.text`)}
                                    on:click={() => dispatchNavigate(key, 'forward', key, $text(`settings.${key}.text`))}
                                />
                            {/if}
                        {/each}
                    </div>

                    <div class="logout-section">
                        <button class="logout-button" on:click={dispatchLogout}>
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
                    on:openSettings={(e) => dispatchNavigate(e.detail.settingsPath, e.detail.direction, e.detail.icon, e.detail.title)}
                />
            {/if}
        </div>
    {/key}
</div>

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