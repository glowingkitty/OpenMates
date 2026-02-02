<!--
Chat Settings - Notification preferences and chat-related settings
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { pushNotificationStore } from '../../stores/pushNotificationStore';

    const dispatch = createEventDispatcher();
    
    // Get current notification status for subtitle display
    let notificationStatus = $derived(
        $pushNotificationStore.permission === 'granted' && $pushNotificationStore.enabled
            ? $text('settings.chat.notifications.enabled.text', { default: 'Enabled' })
            : $pushNotificationStore.permission === 'denied'
                ? $text('settings.chat.notifications.blocked.text', { default: 'Blocked by browser' })
                : $text('settings.chat.notifications.disabled.text', { default: 'Disabled' })
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
            title: $text('settings.chat.notifications.text', { default: 'Notifications' })
        });
    }
</script>

<div class="chat-settings-container">
    <SettingsItem
        type="submenu"
        icon="subsetting_icon subsetting_icon_announcement"
        title={$text('settings.chat.notifications.text', { default: 'Notifications' })}
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
