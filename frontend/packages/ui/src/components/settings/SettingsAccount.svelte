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
            title: $text('settings.account.timezone.text')
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
            title: $text('settings.account.email.text')
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
            title: $text('settings.account.security.text')
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
            title: $text('settings.account.export.text')
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
            title: $text('settings.account.delete.text')
        });
    }
</script>

<SettingsItem 
    type="subsubmenu"
    icon="clock"
    subtitle={$text('settings.account.timezone.text')}
    title={getTimezoneDisplayLabel(currentTimezone)}
    onClick={navigateToTimezone}
/>

<SettingsItem
    type="submenu"
    icon="mail"
    title={$text('settings.account.email.text')}
    onClick={navigateToEmail}
/>

<SettingsItem
    type="submenu"
    icon="security"
    title={$text('settings.account.security.text')}
    onClick={navigateToSecurity}
/>

<SettingsItem
    type="submenu"
    icon="download"
    title={$text('settings.account.export.text')}
    onClick={navigateToExportData}
/>

<SettingsItem
    type="submenu"
    icon="delete"
    title={$text('settings.account.delete.text')}
    onClick={navigateToDeleteAccount}
/>