<!--
Account Settings - Main menu for account-related settings including Security
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
</script>

<SettingsItem
    type="submenu"
    icon="security"
    title={$text('settings.account.security.text')}
    onClick={navigateToSecurity}
/>