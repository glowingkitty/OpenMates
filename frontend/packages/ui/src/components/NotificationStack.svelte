<!-- frontend/packages/ui/src/components/NotificationStack.svelte -->
<!--
  Shared global notification deck for route shells.
  Renders the front notification fully interactive and places the next two
  notifications behind it with reduced scale, upward offset, and opacity.
  Keeping this in the UI package prevents route-specific toast layout drift.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import Notification from './Notification.svelte';
    import ChatMessageNotification from './ChatMessageNotification.svelte';
    import {
        NOTIFICATION_OUTRO_DURATION_MS,
        notificationStore,
        type NotificationType,
    } from '../stores/notificationStore';

    const MAX_VISIBLE_NOTIFICATIONS = 3;
    const STACK_OFFSET_PX = 10;
    const STACK_SCALE_STEP = 0.045;
    const STACK_OPACITY_BY_DEPTH = [1, 0.72, 0.48] as const;
    const NOTIFICATION_MOTION_OFFSET_PX = 120;
    const NOTIFICATION_INTRO_DURATION_MS = 320;
    const E2E_LOG_FORWARDING_SESSION_KEY = 'openmates_e2e_log_forwarding';
    const E2E_NOTIFICATION_STACK_READY_KEY = 'openmates_e2e_notification_stack_ready';
    const E2E_ADD_NOTIFICATIONS_EVENT = 'openmates:e2e:add-notifications';

    type E2ENotificationRequest = {
        type?: NotificationType;
        title?: string;
        message?: string;
        duration?: number;
        dismissible?: boolean;
        isProcessing?: boolean;
        dedupeKey?: string;
        actionLabel?: string;
        actionEventName?: string;
    };

    let visibleNotifications = $derived(
        $notificationStore.notifications.slice(-MAX_VISIBLE_NOTIFICATIONS).reverse(),
    );

    function e2eNotificationInjectionAllowed(): boolean {
        try {
            return typeof sessionStorage !== 'undefined' && Boolean(sessionStorage.getItem(E2E_LOG_FORWARDING_SESSION_KEY));
        } catch {
            return false;
        }
    }

    onMount(() => {
        if (!e2eNotificationInjectionAllowed()) return;

        const handleE2ENotifications = (event: Event): void => {
            if (!e2eNotificationInjectionAllowed()) return;

            const notifications = (event as CustomEvent<{ notifications?: E2ENotificationRequest[] }>).detail?.notifications;
            if (!Array.isArray(notifications)) {
                console.warn('[NotificationStack] Ignoring malformed E2E notification request');
                return;
            }

            notifications.slice(0, MAX_VISIBLE_NOTIFICATIONS).forEach((notification, index) => {
                if (!notification.message) return;
                const actionEventName = notification.actionEventName;
                notificationStore.addNotificationWithOptions(notification.type ?? 'info', {
                    title: notification.title,
                    message: notification.message,
                    duration: notification.duration ?? 0,
                    dismissible: notification.dismissible ?? true,
                    isProcessing: notification.isProcessing ?? false,
                    dedupeKey: notification.dedupeKey ?? `e2e-notification-stack-${index}`,
                    actionLabel: actionEventName ? notification.actionLabel : undefined,
                    onAction: actionEventName ? () => window.dispatchEvent(new CustomEvent(actionEventName)) : undefined,
                });
            });
        };

        window.addEventListener(E2E_ADD_NOTIFICATIONS_EVENT, handleE2ENotifications);
        sessionStorage.setItem(E2E_NOTIFICATION_STACK_READY_KEY, 'true');
        return () => {
            window.removeEventListener(E2E_ADD_NOTIFICATIONS_EVENT, handleE2ENotifications);
            sessionStorage.removeItem(E2E_NOTIFICATION_STACK_READY_KEY);
        };
    });

    function getStackItemStyle(depth: number): string {
        const yOffset = depth * -STACK_OFFSET_PX;
        const scale = 1 - depth * STACK_SCALE_STEP;
        const opacity = STACK_OPACITY_BY_DEPTH[depth] ?? STACK_OPACITY_BY_DEPTH.at(-1) ?? 0.48;
        const zIndex = MAX_VISIBLE_NOTIFICATIONS - depth;

        return `--notification-stack-y: ${yOffset}px; --notification-stack-scale: ${scale}; --notification-stack-opacity: ${opacity}; --notification-stack-z: ${zIndex}; --notification-intro-duration: ${NOTIFICATION_INTRO_DURATION_MS}ms; --notification-outro-duration: ${NOTIFICATION_OUTRO_DURATION_MS}ms; --notification-motion-offset: ${NOTIFICATION_MOTION_OFFSET_PX}px;`;
    }
</script>

{#if visibleNotifications.length > 0}
    <div class="notification-stack" data-testid="notification-stack">
        {#each visibleNotifications as notification, depth (notification.id)}
            <div
                class="notification-stack-item"
                class:notification-stack-item-front={depth === 0}
                class:notification-stack-item-exiting={notification.isExiting}
                data-testid="notification-stack-item"
                data-stack-depth={depth}
                data-motion-state={notification.isExiting ? 'exiting' : 'entered'}
                style={getStackItemStyle(depth)}
                aria-hidden={depth > 0 || notification.isExiting ? 'true' : undefined}
                inert={depth > 0 || notification.isExiting}
            >
                {#if notification.type === 'chat_message'}
                    <ChatMessageNotification {notification} />
                {:else}
                    <Notification {notification} />
                {/if}
            </div>
        {/each}
    </div>
{/if}

<style>
    .notification-stack {
        position: fixed;
        top: 20px;
        inset-inline-start: 50%;
        z-index: 10000;
        display: grid;
        place-items: start center;
        width: max-content;
        max-width: calc(100vw - 20px);
        pointer-events: none;
        transform: translateX(-50%);
    }

    .notification-stack-item {
        grid-area: 1 / 1;
        z-index: var(--notification-stack-z);
        opacity: var(--notification-stack-opacity);
        pointer-events: none;
        transform: translateY(var(--notification-stack-y)) scale(var(--notification-stack-scale));
        transform-origin: top center;
        animation: notificationSlideIn var(--notification-intro-duration) cubic-bezier(0.32, 0, 0.2, 1) backwards;
        transition:
            transform 320ms cubic-bezier(0.32, 0, 0.2, 1),
            opacity var(--duration-normal) var(--easing-default),
            filter var(--duration-normal) var(--easing-default);
        will-change: transform, opacity;
    }

    .notification-stack-item-front {
        pointer-events: auto;
    }

    .notification-stack-item-exiting {
        pointer-events: none;
        animation: notificationSlideOut var(--notification-outro-duration) cubic-bezier(0.4, 0, 1, 1) forwards;
    }

    @keyframes notificationSlideIn {
        from {
            opacity: 0;
            transform: translateY(calc(var(--notification-stack-y) - var(--notification-motion-offset))) scale(var(--notification-stack-scale));
        }
        to {
            opacity: var(--notification-stack-opacity);
            transform: translateY(var(--notification-stack-y)) scale(var(--notification-stack-scale));
        }
    }

    @keyframes notificationSlideOut {
        from {
            opacity: var(--notification-stack-opacity);
            transform: translateY(var(--notification-stack-y)) scale(var(--notification-stack-scale));
        }
        to {
            opacity: 0;
            transform: translateY(calc(var(--notification-stack-y) - var(--notification-motion-offset))) scale(var(--notification-stack-scale));
        }
    }

    .notification-stack-item:not(.notification-stack-item-front) {
        filter: saturate(0.9) brightness(0.9);
    }

    .notification-stack-item :global(.notification) {
        margin: 0;
    }

    @media (max-width: 730px) {
        .notification-stack {
            top: 10px;
        }
    }

    @media (prefers-reduced-motion: reduce) {
        .notification-stack-item {
            animation-duration: 1ms;
            transition: opacity var(--duration-fast) var(--easing-default);
        }
    }

    :global(body.media-mode) .notification-stack {
        display: none !important;
    }
</style>
