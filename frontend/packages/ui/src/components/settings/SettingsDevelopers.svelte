<!--
Developers Settings - API keys management and developer tools
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();
    
    /**
     * Navigate to API Keys submenu by dispatching openSettings event.
     * This event bubbles up through CurrentSettingsPage to Settings.svelte,
     * which handles the navigation. This is the same pattern used by
     * SettingsBilling.svelte and other subsettings components.
     */
    function navigateToApiKeys() {
        dispatch('openSettings', {
            settingsPath: 'developers/api-keys',
            direction: 'forward',
            icon: 'api-keys',
            title: $text('settings.developers_api_keys.text')
        });
    }

    /**
     * Navigate to Devices submenu for API key device management.
     */
    function navigateToDevices() {
        dispatch('openSettings', {
            settingsPath: 'developers/devices',
            direction: 'forward',
            icon: 'devices',
            title: $text('settings.developers_devices_text.text')
        });
    }
</script>

<div class="developers-container">
    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_key"
        title={$text('settings.developers_api_keys.text')}
        subtitleTop={$text('settings.developers_api_keys_description.text')}
        onClick={navigateToApiKeys}
    />

    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_devices"
        title={$text('settings.developers_devices_text.text')}
        subtitleTop={$text('settings.developers_devices_description.text')}
        onClick={navigateToDevices}
    />
</div>

<style>
    .developers-container {
        width: 100%;
        padding: 0 10px;
    }
</style>