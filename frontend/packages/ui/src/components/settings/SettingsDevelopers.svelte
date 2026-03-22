<!--
Developers Settings - API keys management and developer tools
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { getApiUrl } from '../../config/api';

    const dispatch = createEventDispatcher();
    
    /**
     * Get the API documentation URL.
     * Returns the API domain with /docs path appended.
     */
    function getApiDocsUrl(): string {
        return `${getApiUrl()}/docs`;
    }
    
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
            title: $text('settings.developers_api_keys')
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
            title: $text('settings.developers_devices_text')
        });
    }

    /**
     * Open API documentation in a new tab.
     */
    function openApiDocs() {
        window.open(getApiDocsUrl(), '_blank', 'noopener,noreferrer');
    }
</script>

<div class="developers-container">
    <SettingsItem
        type="submenu"
        icon="subsetting_icon key"
        title={$text('settings.developers_api_keys')}
        subtitleTop={$text('settings.developers_api_keys_description')}
        onClick={navigateToApiKeys}
    />

    <SettingsItem
        type="submenu"
        icon="subsetting_icon devices"
        title={$text('settings.developers_devices_text')}
        subtitleTop={$text('settings.developers_devices_description')}
        onClick={navigateToDevices}
    />

    <SettingsItem
        type="submenu"
        icon="subsetting_icon document"
        title={$text('settings.api_docs')}
        subtitleTop=""
        onClick={openApiDocs}
    />
</div>

<style>
    .developers-container {
        width: 100%;
        padding: 0 10px;
    }
</style>