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

<SettingsItem
    type="submenu"
    icon="passkeys"
    title={$text('settings.account.passkeys.text')}
    onClick={navigateToPasskeys}
/>