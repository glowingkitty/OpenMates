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

<!-- Main Account Settings Menu -->
<div class="account-container">
    <!-- Security Menu Item -->
    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_security"
        title={$text('settings.account.security.text')}
        onClick={navigateToSecurity}
    />
</div>

<style>
    /* Main Container */
    .account-container {
        width: 100%;
        padding: 0 10px;
    }
</style>

