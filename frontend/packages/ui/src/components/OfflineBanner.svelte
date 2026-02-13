<script lang="ts">
    /**
     * OfflineBanner.svelte
     *
     * A headless component that watches connectivity status and
     * shows/hides a notification via the notification store.
     *
     * Detects offline status using TWO mechanisms:
     * 1. Browser's navigator.onLine / online/offline events (instant but unreliable)
     * 2. WebSocket disconnection status (reliable but may take a few seconds)
     *
     * The notification is shown when EITHER:
     * - Browser reports offline, OR
     * - WebSocket has been disconnected/reconnecting for more than 3 seconds
     *
     * This dual approach ensures:
     * - Instant detection when browser events fire correctly (e.g., mobile flight mode)
     * - Reliable detection via WebSocket when browser events don't fire (e.g., some desktop browsers)
     *
     * Uses the i18n translation system for user-facing text so that the
     * notification is displayed in the user's selected language.
     */
    import { isOnline } from '../stores/networkStatusStore';
    import { websocketStatus } from '../stores/websocketStatusStore';
    import { notificationStore } from '../stores/notificationStore';
    import { text } from '../i18n/translations';
    import { authStore } from '../stores/authStore';
    import { webSocketService } from '../services/websocketService';

    /**
     * Track the notification ID so we can auto-dismiss it when back online.
     * Null means no offline notification is currently shown.
     */
    let offlineNotificationId: string | null = $state(null);

    /**
     * Track when WebSocket first went into disconnected/reconnecting state.
     * Used to add a delay before showing notification (avoid flashing during brief reconnects).
     */
    let wsDisconnectedSince: number | null = $state(null);

    /**
     * Timer ID for delayed WebSocket offline notification.
     */
    let wsOfflineTimerId: ReturnType<typeof setTimeout> | null = $state(null);

    /**
     * How long to wait (ms) after WebSocket disconnects before showing offline notification.
     * This prevents flashing the notification during brief reconnection attempts.
     */
    const WS_OFFLINE_DELAY_MS = 3000;

    /**
     * Show the offline notification.
     */
    function showOfflineNotification(): void {
        if (offlineNotificationId !== null) return; // Already showing

        const message = $text(
            'notifications.connection.offline_banner.text',
            { default: 'You are offline. Your chats are still available.' }
        ) as string;
        const title = $text(
            'notifications.connection.offline_banner.title.text',
            { default: 'You are offline' }
        ) as string;

        // For authenticated users, show a "Tap to reconnect" action button
        // that triggers an immediate WebSocket reconnection attempt
        const isAuthenticated = $authStore.isAuthenticated;
        const actionLabel = isAuthenticated
            ? $text(
                'notifications.connection.tap_to_reconnect.text',
                { default: 'Tap to reconnect' }
              ) as string
            : undefined;

        offlineNotificationId = notificationStore.addNotificationWithOptions('connection', {
            title,
            message,
            duration: 0, // Persistent — does not auto-dismiss
            dismissible: true, // User can close or swipe away
            ...(isAuthenticated && {
                onAction: () => {
                    console.info('[OfflineBanner] User tapped reconnect — triggering WebSocket retry');
                    webSocketService.retryConnection();
                },
                actionLabel,
            }),
        });
    }

    /**
     * Hide the offline notification.
     */
    function hideOfflineNotification(): void {
        if (offlineNotificationId === null) return; // Not showing

        notificationStore.removeNotification(offlineNotificationId);
        offlineNotificationId = null;
    }

    /**
     * Clear any pending WebSocket offline timer.
     */
    function clearWsOfflineTimer(): void {
        if (wsOfflineTimerId !== null) {
            clearTimeout(wsOfflineTimerId);
            wsOfflineTimerId = null;
        }
    }

    /**
     * Effect that reacts to browser online/offline status changes.
     * Browser events are instant (when they work), so we show/hide immediately.
     *
     * For unauthenticated users: Only use browser online/offline status.
     * For authenticated users: Also check WebSocket status before hiding.
     */
    $effect(() => {
        const online = $isOnline;
        const isAuthenticated = $authStore.isAuthenticated;

        if (!online) {
            // Browser says offline — show immediately
            showOfflineNotification();
        } else if (online && offlineNotificationId !== null) {
            // Browser says online — decide whether to hide based on auth status
            if (!isAuthenticated) {
                // Unauthenticated users don't use WebSocket, so trust browser status
                hideOfflineNotification();
                clearWsOfflineTimer();
                wsDisconnectedSince = null;
            } else {
                // Authenticated users: only hide if WebSocket is also connected
                // (to avoid premature dismissal when browser event fires but WS is still down)
                const wsState = $websocketStatus;
                if (wsState.status === 'connected') {
                    hideOfflineNotification();
                    clearWsOfflineTimer();
                    wsDisconnectedSince = null;
                }
            }
        }
    });

    /**
     * Effect that reacts to WebSocket status changes.
     * WebSocket disconnection is a reliable signal that we've lost connectivity,
     * but we add a small delay to avoid flashing during brief reconnects.
     *
     * IMPORTANT: WebSocket-based offline detection is ONLY used for authenticated users.
     * Unauthenticated users don't connect to WebSocket, so 'disconnected' status is expected
     * and should NOT trigger the offline notification.
     */
    $effect(() => {
        const wsState = $websocketStatus;
        const browserOnline = $isOnline;
        const isAuthenticated = $authStore.isAuthenticated;

        // Skip WebSocket-based detection for unauthenticated users
        // They don't use WebSocket, so 'disconnected' is the normal state
        if (!isAuthenticated) {
            clearWsOfflineTimer();
            wsDisconnectedSince = null;
            return;
        }

        if (wsState.status === 'connected') {
            // WebSocket connected — hide notification and reset state
            clearWsOfflineTimer();
            wsDisconnectedSince = null;
            if (browserOnline) {
                hideOfflineNotification();
            }
        } else if (wsState.status === 'disconnected' || wsState.status === 'reconnecting' || wsState.status === 'error') {
            // WebSocket is not connected
            if (wsDisconnectedSince === null) {
                // First time noticing disconnection — record timestamp
                wsDisconnectedSince = Date.now();
            }

            // If browser already says offline, notification is already shown
            if (!browserOnline) return;

            // Browser thinks we're online but WebSocket is down
            // Start a timer to show notification after delay (if not already started)
            if (wsOfflineTimerId === null && offlineNotificationId === null) {
                wsOfflineTimerId = setTimeout(() => {
                    wsOfflineTimerId = null;
                    // Double-check we're still disconnected before showing
                    if (wsDisconnectedSince !== null) {
                        console.info('[OfflineBanner] WebSocket disconnected for', WS_OFFLINE_DELAY_MS, 'ms — showing offline notification');
                        showOfflineNotification();
                    }
                }, WS_OFFLINE_DELAY_MS);
            }
        }
    });

    /**
     * Cleanup timers on component destroy.
     */
    $effect(() => {
        return () => {
            clearWsOfflineTimer();
        };
    });
</script>

<!-- Headless component: no visual output, only manages notifications -->
