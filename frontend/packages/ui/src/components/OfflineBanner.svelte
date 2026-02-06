<script lang="ts">
    /**
     * OfflineBanner.svelte
     *
     * A headless component that watches browser connectivity status and
     * shows/hides a notification via the notification store.
     *
     * Instead of rendering a blocking fixed banner at the top of the viewport,
     * it triggers a persistent "connection" notification that:
     * - Does NOT auto-dismiss (duration: 0)
     * - Can be manually dismissed via close button or swipe
     * - Auto-dismisses when the connection is restored
     *
     * Uses the i18n translation system for user-facing text so that the
     * notification is displayed in the user's selected language.
     */
    import { isOnline } from '../stores/networkStatusStore';
    import { notificationStore } from '../stores/notificationStore';
    import { text } from '../i18n/translations';

    /**
     * Track the notification ID so we can auto-dismiss it when back online.
     * Null means no offline notification is currently shown.
     */
    let offlineNotificationId: string | null = $state(null);

    /**
     * Effect that reacts to online/offline status changes.
     * - When going offline: show a persistent connection notification
     * - When coming back online: auto-dismiss the offline notification
     */
    $effect(() => {
        const online = $isOnline;

        if (!online && offlineNotificationId === null) {
            // Gone offline — show persistent notification
            const message = $text(
                'notifications.connection.offline_banner.text',
                { default: 'You are offline. Your chats are still available.' }
            );
            const title = $text(
                'notifications.connection.offline_banner.title',
                { default: 'You are offline' }
            );

            offlineNotificationId = notificationStore.addNotificationWithOptions('connection', {
                title,
                message,
                duration: 0, // Persistent — does not auto-dismiss
                dismissible: true, // User can close or swipe away
            });
        } else if (online && offlineNotificationId !== null) {
            // Back online — auto-dismiss the offline notification
            notificationStore.removeNotification(offlineNotificationId);
            offlineNotificationId = null;
        }
    });
</script>

<!-- Headless component: no visual output, only manages notifications -->
