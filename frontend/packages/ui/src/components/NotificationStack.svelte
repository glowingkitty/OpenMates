<!-- frontend/packages/ui/src/components/NotificationStack.svelte -->
<!--
  Shared global notification deck for route shells.
  Renders the front notification fully interactive and places the next two
  notifications behind it with reduced scale, upward offset, and opacity.
  Keeping this in the UI package prevents route-specific toast layout drift.
-->
<script lang="ts">
    import Notification from './Notification.svelte';
    import ChatMessageNotification from './ChatMessageNotification.svelte';
    import { notificationStore } from '../stores/notificationStore';

    const MAX_VISIBLE_NOTIFICATIONS = 3;
    const STACK_OFFSET_PX = 10;
    const STACK_SCALE_STEP = 0.045;
    const STACK_OPACITY_BY_DEPTH = [1, 0.72, 0.48] as const;

    let visibleNotifications = $derived(
        $notificationStore.notifications.slice(0, MAX_VISIBLE_NOTIFICATIONS),
    );

    function getStackItemStyle(depth: number): string {
        const yOffset = depth * -STACK_OFFSET_PX;
        const scale = 1 - depth * STACK_SCALE_STEP;
        const opacity = STACK_OPACITY_BY_DEPTH[depth] ?? STACK_OPACITY_BY_DEPTH.at(-1) ?? 0.48;
        const zIndex = MAX_VISIBLE_NOTIFICATIONS - depth;

        return `--notification-stack-y: ${yOffset}px; --notification-stack-scale: ${scale}; --notification-stack-opacity: ${opacity}; --notification-stack-z: ${zIndex};`;
    }
</script>

{#if visibleNotifications.length > 0}
    <div class="notification-stack" data-testid="notification-stack">
        {#each visibleNotifications as notification, depth (notification.id)}
            <div
                class="notification-stack-item"
                class:notification-stack-item-front={depth === 0}
                data-testid="notification-stack-item"
                data-stack-depth={depth}
                style={getStackItemStyle(depth)}
                aria-hidden={depth > 0 ? 'true' : undefined}
                inert={depth > 0}
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
        transition:
            transform 320ms cubic-bezier(0.32, 0, 0.2, 1),
            opacity var(--duration-normal) var(--easing-default),
            filter var(--duration-normal) var(--easing-default);
        will-change: transform, opacity;
    }

    .notification-stack-item-front {
        pointer-events: auto;
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
            transition: opacity var(--duration-fast) var(--easing-default);
        }
    }

    :global(body.media-mode) .notification-stack {
        display: none !important;
    }
</style>
