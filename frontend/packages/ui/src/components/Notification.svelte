<script lang="ts">
    import { slide } from 'svelte/transition';
    import { notificationStore, type Notification } from '../stores/notificationStore';
    
    // Props using Svelte 5 runes
    let { notification }: { notification: Notification } = $props();
    
    /**
     * Get the appropriate CSS class based on notification type
     * @param type The notification type
     * @returns CSS class string for styling
     */
    function getNotificationClass(type: string): string {
        switch (type) {
            case 'success':
                return 'notification-success';
            case 'warning':
                return 'notification-warning';
            case 'error':
                return 'notification-error';
            case 'info':
            default:
                return 'notification-info';
        }
    }
    
    /**
     * Handle notification dismissal
     * Removes the notification from the store when user clicks dismiss
     */
    function handleDismiss(): void {
        notificationStore.removeNotification(notification.id);
    }
</script>

<!-- Notification wrapper with slide-in animation from top -->
<div
    class="notification"
    class:notification-success={notification.type === 'success'}
    class:notification-warning={notification.type === 'warning'}
    class:notification-error={notification.type === 'error'}
    class:notification-info={notification.type === 'info'}
    transition:slide={{ axis: 'y', duration: 300 }}
    role="alert"
    aria-live="polite"
>
    <div class="notification-content">
        <span class="notification-message">{notification.message}</span>
        <button
            class="notification-dismiss"
            onclick={handleDismiss}
            aria-label="Dismiss notification"
        >
            <div class="clickable-icon icon_close"></div>
        </button>
    </div>
</div>

<style>
    .notification {
        /* Position at top of main-content, centered horizontally */
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 10000; /* High z-index to appear above all content */
        
        /* Base styling */
        min-width: 300px;
        max-width: 600px;
        padding: 16px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        
        /* Animation for slide-in */
        animation: slideInFromTop 0.3s ease-out;
    }
    
    @keyframes slideInFromTop {
        from {
            transform: translateX(-50%) translateY(-100%);
            opacity: 0;
        }
        to {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }
    }
    
    .notification-content {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }
    
    .notification-message {
        flex: 1;
        font-size: 14px;
        line-height: 1.5;
        color: var(--color-font-primary);
    }
    
    .notification-dismiss {
        all: unset;
        cursor: pointer;
        padding: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.7;
        transition: opacity 0.2s ease;
        flex-shrink: 0;
    }
    
    .notification-dismiss:hover {
        opacity: 1;
    }
    
    .notification-dismiss .clickable-icon {
        width: 18px;
        height: 18px;
    }
    
    /* Type-specific styling */
    .notification-success {
        background-color: var(--color-success-light, #d4edda);
        border-left: 4px solid var(--color-success, #28a745);
        color: var(--color-success-dark, #155724);
    }
    
    .notification-warning {
        background-color: var(--color-warning-light, #fff3cd);
        border-left: 4px solid var(--color-warning, #ffc107);
        color: var(--color-warning-dark, #856404);
    }
    
    .notification-error {
        background-color: var(--color-error-light, #f8d7da);
        border-left: 4px solid var(--color-error, #dc3545);
        color: var(--color-error-dark, #721c24);
    }
    
    .notification-info {
        background-color: var(--color-info-light, #d1ecf1);
        border-left: 4px solid var(--color-info, #17a2b8);
        color: var(--color-info-dark, #0c5460);
    }
    
    /* Ensure notification text is readable on colored backgrounds */
    .notification-success .notification-message,
    .notification-warning .notification-message,
    .notification-error .notification-message,
    .notification-info .notification-message {
        color: inherit;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 730px) {
        .notification {
            left: 10px;
            right: 10px;
            max-width: none;
            transform: none;
        }
        
        @keyframes slideInFromTop {
            from {
                transform: translateY(-100%);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }
    }
</style>

