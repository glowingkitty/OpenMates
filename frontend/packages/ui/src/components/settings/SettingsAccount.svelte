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
</script>

<SettingsItem 
    type="subsubmenu"
    icon="clock"
    subtitle={$text('settings.account.timezone')}
    title={getTimezoneDisplayLabel(currentTimezone)}
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
    icon="delete"
    title={$text('settings.account.delete')}
    onClick={navigateToDeleteAccount}
/>