<!--
Chat Settings - Chat-related settings and AI behavior preferences.
Notification preferences have moved to the top-level Notifications hub.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';

    const dispatch = createEventDispatcher();

    /**
     * Navigate to the AI app settings page where users can configure
     * additional chat behavior and preferences.
     */
    function navigateToAiAppSettings() {
        dispatch('openSettings', {
            settingsPath: 'app_store/ai',
            direction: 'forward',
            icon: 'app',
            title: $text('apps.ai')
        });
    }
</script>

<div class="chat-settings-container">
    <SettingsItem
        type="submenu"
        icon="ai"
        title={$text('settings.chat.ai_app_settings')}
        subtitle={$text('settings.chat.ai_app_settings_info')}
        onClick={navigateToAiAppSettings}
    />

    <!-- Future: Additional chat settings can be added here -->
    <!-- Examples: Chat appearance, message bubbles, typing indicators, etc. -->
</div>

<style>
    .chat-settings-container {
        width: 100%;
        padding: 0 10px;
    }
</style>
