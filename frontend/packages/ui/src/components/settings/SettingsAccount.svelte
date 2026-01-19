<!--
Account Settings - Main menu for account-related settings including Security, Export Data, and Delete Account
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

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