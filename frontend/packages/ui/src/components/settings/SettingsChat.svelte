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

    /**
     * Navigate to the Chat Notifications sub-page (push + email preferences).
     * Kept here as a convenience shortcut so users who expect notification
     * preferences under Chat can still find them — the canonical hub lives
     * at Settings > Notifications, but this direct link skips the hub.
     */
    function navigateToNotifications() {
        dispatch('openSettings', {
            settingsPath: 'notifications/chat',
            direction: 'forward',
            icon: 'notification',
            title: $text('settings.notifications.chat')
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

    <SettingsItem
        type="submenu"
        icon="notification"
        title={$text('settings.notifications.chat')}
        subtitle={$text('settings.notifications.description')}
        onClick={navigateToNotifications}
    />
</div>

<style>
    .chat-settings-container {
        width: 100%;
        padding: 0 10px;
    }
</style>
