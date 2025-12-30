<!--
Account Settings - Main menu for account-related settings including Security, Export Data, and Delete Account
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

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
            settingsPath: 'account/export-data',
            direction: 'forward',
            icon: 'download',
            title: $text('settings.account.export_data.text')
        });
    }

    /**
     * Navigate to Delete Account submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToDeleteAccount() {
        dispatch('openSettings', {
            settingsPath: 'account/delete-account',
            direction: 'forward',
            icon: 'delete',
            title: $text('settings.account.delete_account.text')
        });
    }
</script>

<SettingsItem
    type="submenu"
    icon="security"
    title={$text('settings.account.security.text')}
    onClick={navigateToSecurity}
/>

<SettingsItem
    type="submenu"
    icon="download"
    title={$text('settings.account.export_data.text')}
    onClick={navigateToExportData}
/>

<SettingsItem
    type="submenu"
    icon="delete"
    title={$text('settings.account.delete_account.text')}
    onClick={navigateToDeleteAccount}
/>