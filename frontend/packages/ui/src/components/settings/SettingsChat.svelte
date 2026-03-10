<!--
Chat Settings - Notification preferences and chat-related settings
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { pushNotificationStore } from '../../stores/pushNotificationStore';
    import { userProfile } from '../../stores/userProfile';

    const dispatch = createEventDispatcher();
    
    // Determine if any notification channel is active (push or email)
    let pushEnabled = $derived($pushNotificationStore.permission === 'granted' && $pushNotificationStore.enabled);
    let emailEnabled = $derived($userProfile.email_notifications_enabled ?? false);
    
    // Get current notification status for subtitle display.
    // Shows "Enabled" if either push or email notifications are active,
    // "Blocked by browser" only when push is blocked AND email is not enabled,
    // "Disabled" when nothing is enabled.
    let notificationStatus = $derived(
        pushEnabled || emailEnabled
            ? $text('settings.chat.notifications.enabled')
            : $pushNotificationStore.permission === 'denied'
                ? $text('settings.chat.notifications.blocked')
                : $text('settings.chat.notifications.disabled')
    );
    
    /**
     * Navigate to the top-level Notifications hub which consolidates all
     * notification preferences (chat + backup reminders).
     */
    function navigateToNotifications() {
        dispatch('openSettings', {
            settingsPath: 'notifications',
            direction: 'forward',
            icon: 'notification',
            title: $text('settings.notifications')
        });
    }

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
        icon="subsetting_icon announcement"
        title={$text('settings.notifications')}
        subtitleTop={notificationStatus}
        onClick={navigateToNotifications}
    />

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
