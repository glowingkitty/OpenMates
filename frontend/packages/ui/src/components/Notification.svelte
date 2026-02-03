<script lang="ts">
    import { slide } from 'svelte/transition';
    import { notificationStore, type Notification } from '../stores/notificationStore';
    
    // Note: icons.css is loaded globally via index.ts and +layout.svelte
    // No need to import it here - global icon classes (clickable-icon, icon_*) are available
    
    // Props using Svelte 5 runes
    let { notification }: { notification: Notification } = $props();
    
    /**
     * Get the CSS icon class based on notification type
     * Uses existing icon classes from icons.css
     * @param type The notification type
     * @returns CSS class name for the icon
     */
    function getNotificationIconClass(type: string): string {
        switch (type) {
            case 'auto_logout':
                return 'icon_logout';
            case 'connection':
                return 'icon_cloud';
            case 'software_update':
                return 'icon_download';
            case 'success':
                return 'icon_check';
            case 'warning':
                return 'icon_warning';
            case 'error':
                return 'icon_warning';
            case 'info':
            default:
                return 'icon_announcement';
        }
    }
    
    /**
     * Handle notification dismissal
     * Removes the notification from the store when user clicks dismiss
     */
    function handleDismiss(): void {
        notificationStore.removeNotification(notification.id);
    }
    
    // Get the appropriate icon class
    let iconClass = $derived(getNotificationIconClass(notification.type));
</script>

<!-- Notification wrapper with slide-in animation from top -->
<div
    class="notification"
    class:notification-auto-logout={notification.type === 'auto_logout'}
    class:notification-connection={notification.type === 'connection'}
    class:notification-software-update={notification.type === 'software_update'}
    class:notification-success={notification.type === 'success'}
    class:notification-warning={notification.type === 'warning'}
    class:notification-error={notification.type === 'error'}
    class:notification-info={notification.type === 'info'}
    transition:slide={{ axis: 'y', duration: 300 }}
    role="alert"
    aria-live="polite"
>
    <!-- Header row with bell/announcement icon, title, and close button -->
    <div class="notification-header">
        <span class="clickable-icon icon_announcement notification-bell-icon"></span>
        <span class="notification-title">{notification.title || ''}</span>
        <button
            class="notification-dismiss"
            onclick={handleDismiss}
            aria-label="Dismiss notification"
        >
            <span class="clickable-icon icon_close"></span>
        </button>
    </div>
    
    <!-- Content row with type icon and message -->
    <div class="notification-content">
        <div class="notification-icon">
            <span class="clickable-icon {iconClass} notification-type-icon"></span>
        </div>
        <div class="notification-message-wrapper">
            <span class="notification-message-primary">{notification.message}</span>
            {#if notification.messageSecondary}
                <span class="notification-message-secondary">{notification.messageSecondary}</span>
            {/if}
        </div>
    </div>
</div>

<style>
    .notification {
        /* Position relative - parent container handles absolute positioning */
        position: relative;
        
        /* Figma design: 430px or 100% viewport width, with 5px margin on smaller screens */
        width: 430px;
        max-width: calc(100vw - 10px);
        
        /* Base styling */
        padding: 12px 16px;
        border-radius: 12px;
        background-color: var(--color-grey-20);
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
        
        /* Animation for slide-in */
        animation: slideInFromTop 0.3s ease-out;
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
    
    /* Header row */
    .notification-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
    }
    
    /* Bell/announcement icon in header - grey color, smaller size */
    /* Use :global() to ensure mask-image from icons.css is applied */
    .notification-header :global(.notification-bell-icon) {
        width: 16px;
        height: 16px;
        background: var(--color-grey-50);
        flex-shrink: 0;
    }
    
    .notification-title {
        flex: 1;
        font-size: 12px;
        font-weight: 500;
        color: var(--color-grey-50);
        line-height: 1.4;
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
    
    .notification-dismiss :global(.clickable-icon) {
        width: 20px;
        height: 20px;
        background: var(--color-primary-start);
    }
    
    .notification-dismiss:hover {
        opacity: 1;
    }
    
    /* Content row */
    .notification-content {
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }
    
    .notification-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        border-radius: 10px;
        background-color: var(--color-grey-30);
        flex-shrink: 0;
    }
    
    /* Type-specific icon styling - larger size inside the icon box */
    /* Use :global() to ensure mask-image from icons.css is applied */
    .notification-icon :global(.notification-type-icon) {
        width: 24px;
        height: 24px;
        background: var(--color-primary-start);
    }
    
    .notification-message-wrapper {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }
    
    .notification-message-primary {
        font-size: 14px;
        font-weight: 500;
        line-height: 1.4;
        color: var(--color-primary-start);
    }
    
    .notification-message-secondary {
        font-size: 14px;
        font-weight: 600;
        line-height: 1.4;
        color: var(--color-font-primary);
    }
    
    /* Type-specific icon background colors */
    .notification-auto-logout .notification-icon,
    .notification-connection .notification-icon,
    .notification-software-update .notification-icon,
    .notification-info .notification-icon {
        background-color: var(--color-grey-30);
    }
    
    .notification-success .notification-icon {
        background-color: rgba(40, 167, 69, 0.15);
    }
    
    .notification-warning .notification-icon {
        background-color: rgba(255, 193, 7, 0.15);
    }
    
    .notification-error .notification-icon {
        background-color: rgba(220, 53, 69, 0.15);
    }
    
    /* Mobile responsiveness - 5px margin on each side */
    @media (max-width: 440px) {
        .notification {
            width: calc(100vw - 10px);
            margin: 0 5px;
        }
    }
</style>

