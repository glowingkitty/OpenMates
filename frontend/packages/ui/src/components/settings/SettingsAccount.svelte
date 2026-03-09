<!--
Account Settings - Main menu for account-related settings including Security, Export Data, and Delete Account
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { userProfile } from '../../stores/userProfile';

    const dispatch = createEventDispatcher();

    // Get display label for current timezone
    function getTimezoneDisplayLabel(timezoneId: string | null): string {
        if (!timezoneId) return 'Not set';
        // Convert IANA timezone to readable format
        // e.g., "Europe/Berlin" -> "Berlin"
        const parts = timezoneId.split('/');
        return parts[parts.length - 1].replace(/_/g, ' ');
    }

    // Current timezone from user profile
    let currentTimezone = $derived($userProfile.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone);

    // Current username from user profile (displayed as subtitle in the menu item)
    let currentUsername = $derived($userProfile.username || '');
    let isAdminUser = $derived($userProfile.is_admin === true);
    let accountDebugOutput = $state<string>('');
    let accountDebugLoading = $state(false);

    async function loadAccountDebugOutput() {
        if (!isAdminUser || typeof window === 'undefined') return;
        const debugApi = (window as unknown as { debug?: { user?: () => unknown } }).debug;
        if (!debugApi?.user) {
            accountDebugOutput = 'window.debug.user() is not available in this runtime.';
            return;
        }

        accountDebugLoading = true;
        try {
            const result = await Promise.resolve(debugApi.user());
            if (typeof result === 'string') {
                accountDebugOutput = result;
            } else if (result === undefined) {
                accountDebugOutput = 'window.debug.user() executed. Check console output and logs below.';
            } else {
                accountDebugOutput = JSON.stringify(result, null, 2);
            }
        } catch (error) {
            accountDebugOutput = error instanceof Error
                ? `window.debug.user() failed: ${error.message}`
                : `window.debug.user() failed: ${String(error)}`;
        } finally {
            accountDebugLoading = false;
        }
    }

    $effect(() => {
        if (isAdminUser) {
            void loadAccountDebugOutput();
        }
    });

    /**
     * Navigate to Username submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToUsername() {
        dispatch('openSettings', {
            settingsPath: 'account/username',
            direction: 'forward',
            icon: 'user',
            title: $text('settings.account.username')
        });
    }

    /**
     * Navigate to Profile Picture submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToProfilePicture() {
        dispatch('openSettings', {
            settingsPath: 'account/profile-picture',
            direction: 'forward',
            icon: 'image',
            title: $text('settings.account.profile_picture')
        });
    }

    /**
     * Navigate to Timezone submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToTimezone() {
        dispatch('openSettings', {
            settingsPath: 'account/timezone',
            direction: 'forward',
            icon: 'clock',
            title: $text('settings.account.timezone')
        });
    }

    /**
     * Navigate to Email submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToEmail() {
        dispatch('openSettings', {
            settingsPath: 'account/email',
            direction: 'forward',
            icon: 'mail',
            title: $text('settings.account.email')
        });
    }

    /**
     * Navigate to Security submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToSecurity() {
        dispatch('openSettings', {
            settingsPath: 'account/security',
            direction: 'forward',
            icon: 'security',
            title: $text('settings.account.security')
        });
    }

    /**
     * Navigate to Export Data submenu.
     * Dispatches navigation event to parent Settings component.
     * GDPR Article 20 - Right to Data Portability
     */
    function navigateToExportData() {
        dispatch('openSettings', {
            settingsPath: 'account/export',
            direction: 'forward',
            icon: 'download',
            title: $text('settings.account.export')
        });
    }

    /**
     * Navigate to Storage overview submenu.
     * Shows total storage usage, per-category breakdown, and billing info.
     */
    function navigateToStorage() {
        dispatch('openSettings', {
            settingsPath: 'account/storage',
            direction: 'forward',
            icon: 'storage',
            title: $text('settings.storage')
        });
    }

    /**
     * Navigate to Delete Account submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToDeleteAccount() {
        dispatch('openSettings', {
            settingsPath: 'account/delete',
            direction: 'forward',
            icon: 'delete',
            title: $text('settings.account.delete')
        });
    }

    /**
     * Navigate to Chats submenu.
     * Shows total chat count, creation timeline graph, and bulk delete tools.
     */
    function navigateToChats() {
        dispatch('openSettings', {
            settingsPath: 'account/chats',
            direction: 'forward',
            icon: 'chat',
            title: $text('settings.account.chats')
        });
    }
</script>

{#if isAdminUser}
    <div class="account-debug-box selectable">
        <div class="account-debug-header-row">
            <span class="account-debug-title">window.debug.user()</span>
            <button class="account-debug-refresh" onclick={loadAccountDebugOutput} disabled={accountDebugLoading}>
                {accountDebugLoading ? 'Loading...' : 'Refresh'}
            </button>
        </div>
        <pre class="account-debug-pre selectable">{accountDebugOutput || 'No debug output yet.'}</pre>
    </div>
{/if}

<SettingsItem
    type="subsubmenu"
    icon="user"
    title={$text('settings.account.username')}
    subtitle={currentUsername}
    onClick={navigateToUsername}
/>

<SettingsItem
    type="submenu"
    icon="user"
    title={$text('settings.account.profile_picture')}
    onClick={navigateToProfilePicture}
/>

<SettingsItem 
    type="subsubmenu"
    icon="clock"
    title={$text('settings.account.timezone')}
    subtitle={getTimezoneDisplayLabel(currentTimezone)}
    onClick={navigateToTimezone}
/>

<SettingsItem
    type="submenu"
    icon="mail"
    title={$text('settings.account.email')}
    onClick={navigateToEmail}
/>

<SettingsItem
    type="submenu"
    icon="security"
    title={$text('settings.account.security')}
    onClick={navigateToSecurity}
/>

<SettingsItem
    type="submenu"
    icon="download"
    title={$text('settings.account.export')}
    onClick={navigateToExportData}
/>

<SettingsItem
    type="submenu"
    icon="storage"
    title={$text('settings.storage')}
    onClick={navigateToStorage}
/>

<SettingsItem
    type="submenu"
    icon="chat"
    title={$text('settings.account.chats')}
    onClick={navigateToChats}
/>

<SettingsItem
    type="submenu"
    icon="delete"
    title={$text('settings.account.delete')}
    onClick={navigateToDeleteAccount}
/>

<style>
    .account-debug-box {
        margin: 0 0 0.75rem;
        padding: 0.75rem;
        border-radius: 0.75rem;
        border: 1px solid var(--color-grey-30);
        background: var(--color-grey-10);
    }

    .account-debug-header-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.5rem;
    }

    .account-debug-title {
        font-size: 0.82rem;
        font-weight: 600;
        color: var(--color-font-secondary);
    }

    .account-debug-refresh {
        all: unset;
        cursor: pointer;
        font-size: 0.78rem;
        color: var(--color-primary);
    }

    .account-debug-refresh:disabled {
        opacity: 0.6;
        cursor: default;
    }

    .account-debug-pre {
        margin: 0;
        max-height: 12rem;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
        font-family: monospace;
        font-size: 0.76rem;
        line-height: 1.4;
        color: var(--color-font-primary);
        user-select: text;
        -webkit-user-select: text;
        -moz-user-select: text;
        -ms-user-select: text;
    }
</style>
