<script lang="ts">
    import { notificationStore, type Notification } from '../stores/notificationStore';
    
    // Props using Svelte 5 runes
    let { notification }: { notification: Notification } = $props();
    
    // State for swipe-to-dismiss gesture
    let isDragging = $state(false);
    let startY = $state(0);
    let currentY = $state(0);
    let dragOffset = $state(0);
    let isExiting = $state(false);
    let notificationElement: HTMLDivElement | null = $state(null);
    
    // Threshold for swipe dismissal (pixels)
    const SWIPE_THRESHOLD = 50;
    // Velocity threshold for fast swipes (pixels per ms)
    const VELOCITY_THRESHOLD = 0.3;
    
    // Track swipe timing for velocity calculation
    let swipeStartTime = 0;
    
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
     * Handle notification dismissal with exit animation
     * Triggers exit animation then removes the notification from the store
     */
    function handleDismiss(): void {
        isExiting = true;
        // Wait for exit animation to complete before removing
        setTimeout(() => {
            notificationStore.removeNotification(notification.id);
        }, 200);
    }
    
    /**
     * Handle touch/mouse start for swipe gesture
     */
    function handlePointerDown(event: PointerEvent): void {
        // Only track vertical swipes
        isDragging = true;
        startY = event.clientY;
        currentY = event.clientY;
        dragOffset = 0;
        swipeStartTime = Date.now();
        
        // Capture pointer for consistent tracking
        (event.target as HTMLElement).setPointerCapture(event.pointerId);
    }
    
    /**
     * Handle touch/mouse move for swipe gesture
     */
    function handlePointerMove(event: PointerEvent): void {
        if (!isDragging) return;
        
        currentY = event.clientY;
        const delta = currentY - startY;
        
        // Only allow upward swipes (negative delta) for dismissal
        // Add resistance for downward swipes
        if (delta < 0) {
            dragOffset = delta;
        } else {
            // Rubber band effect for downward drag
            dragOffset = delta * 0.3;
        }
    }
    
    /**
     * Handle touch/mouse end for swipe gesture
     */
    function handlePointerUp(event: PointerEvent): void {
        if (!isDragging) return;
        
        isDragging = false;
        
        // Calculate swipe velocity
        const swipeTime = Date.now() - swipeStartTime;
        const velocity = Math.abs(dragOffset) / swipeTime;
        
        // Dismiss if swiped far enough OR fast enough (upward only)
        if (dragOffset < -SWIPE_THRESHOLD || (dragOffset < 0 && velocity > VELOCITY_THRESHOLD)) {
            // Animate out and dismiss
            isExiting = true;
            setTimeout(() => {
                notificationStore.removeNotification(notification.id);
            }, 200);
        } else {
            // Snap back
            dragOffset = 0;
        }
        
        // Release pointer capture
        (event.target as HTMLElement).releasePointerCapture(event.pointerId);
    }
    
    /**
     * Handle pointer cancel (e.g., touch interrupted)
     */
    function handlePointerCancel(event: PointerEvent): void {
        isDragging = false;
        dragOffset = 0;
        (event.target as HTMLElement).releasePointerCapture(event.pointerId);
    }
    
    // Get the appropriate icon type
    let iconType = $derived(getNotificationIconType(notification.type));
    
    // Compute transform style for drag gesture
    let dragStyle = $derived(
        isDragging || dragOffset !== 0
            ? `transform: translateY(${dragOffset}px); opacity: ${Math.max(0.3, 1 - Math.abs(dragOffset) / 150)};`
            : ''
    );
</script>

<!-- 
    Notification wrapper with:
    - Slide-in from top with opacity transition on mount
    - Slide-out to top with opacity fade on dismiss
    - Swipe-to-dismiss gesture (swipe up to dismiss, like iOS)
-->
<div
    bind:this={notificationElement}
    class="notification"
    class:notification-auto-logout={notification.type === 'auto_logout'}
    class:notification-connection={notification.type === 'connection'}
    class:notification-software-update={notification.type === 'software_update'}
    class:notification-success={notification.type === 'success'}
    class:notification-warning={notification.type === 'warning'}
    class:notification-error={notification.type === 'error'}
    class:notification-info={notification.type === 'info'}
    class:notification-exiting={isExiting}
    class:notification-dragging={isDragging}
    style={dragStyle}
    role="alert"
    aria-live="polite"
    onpointerdown={handlePointerDown}
    onpointermove={handlePointerMove}
    onpointerup={handlePointerUp}
    onpointercancel={handlePointerCancel}
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
            {#if notification.onAction && notification.actionLabel}
                <button
                    class="notification-action-btn"
                    onclick={(e: MouseEvent) => {
                        e.stopPropagation();
                        notification.onAction?.();
                    }}
                >
                    {notification.actionLabel}
                </button>
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
        
        /* Animation for slide-in from outside viewport with opacity */
        animation: slideInFromTop 0.2s ease-out forwards;
        
        /* Smooth transition for drag gestures when not actively dragging */
        transition: transform 0.2s ease-out, opacity 0.2s ease-out;
        
        /* Enable touch manipulation for swipe gestures */
        touch-action: pan-x;
        cursor: grab;
        
        /* Prevent text selection during drag */
        user-select: none;
    }
    
    /* Remove transition during active drag for responsive feel */
    .notification-dragging {
        transition: none;
        cursor: grabbing;
    }
    
    /* Exit animation - slide out to top with opacity fade */
    .notification-exiting {
        animation: slideOutToTop 0.2s ease-in forwards;
    }
    
    @keyframes slideInFromTop {
        from {
            /* Start from outside viewport (above) */
            transform: translateY(calc(-100% - 20px));
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutToTop {
        from {
            transform: translateY(0);
            opacity: 1;
        }
        to {
            /* Exit to outside viewport (above) */
            transform: translateY(calc(-100% - 20px));
            opacity: 0;
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
    
    /* Action button for interactive notifications (e.g., "Tap to reconnect") */
    .notification-action-btn {
        all: unset;
        cursor: pointer;
        margin-top: 6px;
        padding: 6px 14px;
        font-size: 13px;
        font-weight: 600;
        line-height: 1.4;
        color: var(--color-primary);
        background-color: var(--color-grey-40);
        border-radius: 8px;
        transition: background-color 0.15s ease, opacity 0.15s ease;
        align-self: flex-start;
    }
    
    .notification-action-btn:hover {
        background-color: var(--color-grey-50);
    }
    
    .notification-action-btn:active {
        opacity: 0.8;
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
    
    /* Mobile responsiveness - ensure notification fits within viewport */
    @media (max-width: 450px) {
        .notification {
            /* Use 100% of container width minus safe margins */
            width: calc(100vw - 20px);
            max-width: calc(100vw - 20px);
            /* Reduce padding slightly on very small screens */
            padding: 10px 12px;
        }
    }
</style>

