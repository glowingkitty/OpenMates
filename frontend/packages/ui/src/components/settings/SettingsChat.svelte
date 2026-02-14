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
     * Navigate to Notifications submenu by dispatching openSettings event.
     * This event bubbles up through CurrentSettingsPage to Settings.svelte,
     * which handles the navigation.
     */
    function navigateToNotifications() {
        dispatch('openSettings', {
            settingsPath: 'chat/notifications',
            direction: 'forward',
            icon: 'notification',
            title: $text('settings.chat.notifications')
        });
    }
</script>

<div class="chat-settings-container">
    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_announcement"
        title={$text('settings.chat.notifications')}
        subtitleTop={notificationStatus}
        onClick={navigateToNotifications}
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
