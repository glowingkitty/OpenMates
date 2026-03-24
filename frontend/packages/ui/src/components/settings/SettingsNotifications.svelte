<!--
  Notifications Settings Hub — top-level settings section that groups all notification
  preferences in one place.

  Currently contains:
  - Chat Notifications (push + email for AI responses)
  - Backup Reminders (periodic data export reminder emails)

  Easily extensible: add new SettingsItem rows here as new notification types are added.
  Each item dispatches an openSettings event to navigate to the relevant sub-page.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { pushNotificationStore } from '../../stores/pushNotificationStore';
    import { userProfile } from '../../stores/userProfile';

    const dispatch = createEventDispatcher();

    // --- Chat notifications status ---
    let pushEnabled = $derived(
        $pushNotificationStore.permission === 'granted' && $pushNotificationStore.enabled
    );
    let emailEnabled = $derived($userProfile.email_notifications_enabled ?? false);
    let chatNotificationStatus = $derived(
        pushEnabled || emailEnabled
            ? $text('settings.chat.notifications.enabled')
            : $pushNotificationStore.permission === 'denied'
                ? $text('settings.chat.notifications.blocked')
                : $text('settings.chat.notifications.disabled')
    );

    // --- Backup reminder status ---
    let backupReminderEnabled = $derived(
        $userProfile.email_notification_preferences?.backupReminder ?? true
    );
    let backupReminderInterval = $derived(
        $userProfile.backup_reminder_interval_days ?? 30
    );
    let backupReminderStatus = $derived(
        backupReminderEnabled
            ? $text('settings.notifications.backup.interval_days', { values: { count: backupReminderInterval } })
            : $text('settings.notifications.backup.disabled')
    );

    function navigateToChatNotifications() {
        dispatch('openSettings', {
            settingsPath: 'notifications/chat',
            direction: 'forward',
            icon: 'notification',
            title: $text('settings.notifications.chat'),
        });
    }

    function navigateToBackupReminders() {
        dispatch('openSettings', {
            settingsPath: 'notifications/backup',
            direction: 'forward',
            icon: 'download',
            title: $text('settings.notifications.backup'),
        });
    }

    function navigateToReminders() {
        dispatch('openSettings', {
            settingsPath: 'notifications/reminders',
            direction: 'forward',
            icon: 'bell',
            title: $text('reminder.settings.title'),
        });
    }
</script>

<div class="notifications-settings-container">
    <SettingsItem
        type="submenu"
        icon="subsetting_icon announcement"
        title={$text('settings.notifications.chat')}
        subtitleTop={chatNotificationStatus}
        onClick={navigateToChatNotifications}
    />

    <SettingsItem
        type="submenu"
        icon="subsetting_icon download"
        title={$text('settings.notifications.backup')}
        subtitleTop={backupReminderStatus}
        onClick={navigateToBackupReminders}
    />

    <SettingsItem
        type="submenu"
        icon="subsetting_icon bell"
        title={$text('reminder.settings.title')}
        onClick={navigateToReminders}
    />
</div>

<style>
    .notifications-settings-container {
        width: 100%;
        padding: 0 10px;
    }
</style>
