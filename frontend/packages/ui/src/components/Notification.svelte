<script lang="ts">
    import { slide } from 'svelte/transition';
    import { notificationStore, type Notification } from '../stores/notificationStore';
    
    // Props using Svelte 5 runes
    let { notification }: { notification: Notification } = $props();
    
    /**
     * Get the icon type for CSS styling based on notification type
     * @param type The notification type
     * @returns Icon type identifier for data attribute
     */
    function getNotificationIconType(type: string): string {
        switch (type) {
            case 'auto_logout':
                return 'logout';
            case 'connection':
                return 'cloud';
            case 'software_update':
                return 'download';
            case 'success':
                return 'check';
            case 'warning':
            case 'error':
                return 'warning';
            case 'info':
            default:
                return 'reminder';
        }
    }
    
    /**
     * Handle notification dismissal
     * Removes the notification from the store when user clicks dismiss
     */
    function handleDismiss(): void {
        notificationStore.removeNotification(notification.id);
    }
    
    // Get the appropriate icon type
    let iconType = $derived(getNotificationIconType(notification.type));
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
    <!-- Header row with reminder icon, title, and close button -->
    <div class="notification-header">
        <span class="notification-bell-icon"></span>
        <span class="notification-title">{notification.title || ''}</span>
        <button
            class="notification-dismiss"
            onclick={handleDismiss}
            aria-label="Dismiss notification"
        >
            <span class="notification-close-icon"></span>
        </button>
    </div>
    
    <!-- Content row with type icon and message -->
    <div class="notification-content">
        <div class="notification-icon">
            <span class="notification-type-icon" data-icon-type={iconType}></span>
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
        background-color: var(--color-grey-30);
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
    
    /* Bell/reminder icon in header - grey color, smaller size */
    .notification-bell-icon {
        display: inline-block;
        width: 16px;
        height: 16px;
        background: var(--color-grey-50);
        flex-shrink: 0;
        -webkit-mask-image: url('@openmates/ui/static/icons/reminder.svg');
        mask-image: url('@openmates/ui/static/icons/reminder.svg');
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        mask-size: contain;
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
    
    /* Close icon in dismiss button */
    .notification-close-icon {
        display: inline-block;
        width: 20px;
        height: 20px;
        background: var(--color-grey-90);
        -webkit-mask-image: url('@openmates/ui/static/icons/close.svg');
        mask-image: url('@openmates/ui/static/icons/close.svg');
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        mask-size: contain;
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
        background-color: var(--color-grey-40);
        flex-shrink: 0;
    }
    
    /* Type-specific icon styling - larger size inside the icon box */
    .notification-type-icon {
        display: inline-block;
        width: 24px;
        height: 24px;
        background: var(--color-grey-90);
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        mask-size: contain;
    }
    
    /* Icon type masks based on data attribute */
    .notification-type-icon[data-icon-type="reminder"] {
        -webkit-mask-image: url('@openmates/ui/static/icons/reminder.svg');
        mask-image: url('@openmates/ui/static/icons/reminder.svg');
    }
    
    .notification-type-icon[data-icon-type="logout"] {
        -webkit-mask-image: url('@openmates/ui/static/icons/logout.svg');
        mask-image: url('@openmates/ui/static/icons/logout.svg');
    }
    
    .notification-type-icon[data-icon-type="cloud"] {
        -webkit-mask-image: url('@openmates/ui/static/icons/cloud.svg');
        mask-image: url('@openmates/ui/static/icons/cloud.svg');
    }
    
    .notification-type-icon[data-icon-type="download"] {
        -webkit-mask-image: url('@openmates/ui/static/icons/download.svg');
        mask-image: url('@openmates/ui/static/icons/download.svg');
    }
    
    .notification-type-icon[data-icon-type="check"] {
        -webkit-mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-image: url('@openmates/ui/static/icons/check.svg');
    }
    
    .notification-type-icon[data-icon-type="warning"] {
        -webkit-mask-image: url('@openmates/ui/static/icons/warning.svg');
        mask-image: url('@openmates/ui/static/icons/warning.svg');
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
        color: var(--color-grey-90);
    }
    
    .notification-message-secondary {
        font-size: 14px;
        font-weight: 600;
        line-height: 1.4;
        color: var(--color-grey-90);
    }
    
    /* Type-specific icon background colors */
    .notification-auto-logout .notification-icon,
    .notification-connection .notification-icon,
    .notification-software-update .notification-icon,
    .notification-info .notification-icon {
        background-color: var(--color-grey-40);
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

