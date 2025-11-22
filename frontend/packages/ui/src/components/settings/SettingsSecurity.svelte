<!--
Security Settings - Menu for security-related settings including Passkeys
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    /**
     * Navigate to Passkeys submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToPasskeys() {
        dispatch('openSettings', {
            settingsPath: 'account/security/passkeys',
            direction: 'forward',
            icon: 'passkeys',
            title: $text('settings.account.passkeys.text')
        });
    }
</script>

<!-- Main Security Settings Menu -->
<div class="security-container">
    <!-- Passkeys Menu Item -->
    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_passkeys"
        title={$text('settings.account.security.passkeys.text')}
        onClick={navigateToPasskeys}
    />
</div>

<style>
    /* Main Container */
    .security-container {
        width: 100%;
        padding: 0 10px;
    }
</style>

