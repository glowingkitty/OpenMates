<!-- frontend/packages/ui/src/components/ChatMessageNotification.svelte -->
<!--
    Chat message notification component for background chat messages.
    Shows the chat title, message preview, avatar, and includes a reply input.
    
    Based on Figma design:
    - 430px width or 100% viewport (with 5px margin on smaller screens)
    - var(--color-grey-20) background
    - Auto-dismisses after 3 seconds unless user interacts
    - Reply input with mention dropdown support (dropdown shows BELOW input)
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import { onMount, onDestroy, tick } from 'svelte';
    import { notificationStore, type Notification } from '../stores/notificationStore';
    import { text } from '@repo/ui';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import Placeholder from '@tiptap/extension-placeholder';
    
    // Import icons.css for clickable-icon classes
    import '../styles/icons.css';
    
    // Props using Svelte 5 runes
    let { notification }: { notification: Notification } = $props();
    
    // State
    let isExpanded = $state(false); // Whether the reply input is expanded
    let replyText = $state('');
    let editorElement = $state<HTMLElement | null>(null);
    let editor: Editor | null = null;
    let isFocused = $state(false);
    let dismissTimeout: ReturnType<typeof setTimeout> | null = null;
    
    /**
     * Handle notification dismissal
     */
    function handleDismiss(): void {
        notificationStore.removeNotification(notification.id);
    }
    
    /**
     * Handle clicking the reply button to expand input
     */
    function handleReplyClick(): void {
        isExpanded = true;
        // Cancel auto-dismiss when user starts typing
        if (dismissTimeout) {
            clearTimeout(dismissTimeout);
            dismissTimeout = null;
        }
        // Focus the editor after expansion
        tick().then(() => {
            editor?.commands.focus();
        });
    }
    
    /**
     * Handle clicking on notification to navigate to chat
     */
    function handleNotificationClick(): void {
        if (notification.chatId) {
            // Navigate to the chat
            window.location.hash = `#chat/${notification.chatId}`;
            handleDismiss();
        }
    }
    
    /**
     * Handle sending the reply message
     */
    async function handleSendReply(): Promise<void> {
        if (!replyText.trim() || !notification.chatId) return;
        
        // TODO: Implement actual message sending through chatSyncService
        // For now, navigate to chat and dismiss
        console.debug('[ChatMessageNotification] Would send reply:', replyText, 'to chat:', notification.chatId);
        
        // Navigate to the chat
        window.location.hash = `#chat/${notification.chatId}`;
        handleDismiss();
    }
    
    /**
     * Pause auto-dismiss when user hovers over notification
     */
    function handleMouseEnter(): void {
        if (dismissTimeout) {
            clearTimeout(dismissTimeout);
            dismissTimeout = null;
        }
    }
    
    /**
     * Resume auto-dismiss when user leaves notification (if not expanded)
     */
    function handleMouseLeave(): void {
        if (!isExpanded && notification.duration) {
            dismissTimeout = setTimeout(() => {
                handleDismiss();
            }, notification.duration);
        }
    }
    
    // Initialize TipTap editor for reply input
    onMount(() => {
        if (editorElement) {
            editor = new Editor({
                element: editorElement,
                extensions: [
                    StarterKit,
                    Placeholder.configure({
                        placeholder: 'Type your reply...',
                    }),
                ],
                content: '',
                onUpdate: ({ editor }) => {
                    replyText = editor.getText();
                },
                onFocus: () => {
                    isFocused = true;
                    // Cancel auto-dismiss on focus
                    if (dismissTimeout) {
                        clearTimeout(dismissTimeout);
                        dismissTimeout = null;
                    }
                },
                onBlur: () => {
                    isFocused = false;
                },
                editorProps: {
                    attributes: {
                        class: 'notification-reply-editor',
                    },
                    handleKeyDown: (view, event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                            handleSendReply();
                            return true;
                        }
                        return false;
                    },
                },
            });
        }
    });
    
    onDestroy(() => {
        if (dismissTimeout) {
            clearTimeout(dismissTimeout);
        }
        editor?.destroy();
    });
</script>

<!-- Chat message notification wrapper -->
<div
    class="notification notification-chat-message"
    class:expanded={isExpanded}
    transition:slide={{ axis: 'y', duration: 300 }}
    role="alert"
    aria-live="polite"
    onmouseenter={handleMouseEnter}
    onmouseleave={handleMouseLeave}
>
    <!-- Header row with announcement icon, title, and close button -->
    <div class="notification-header">
        <span class="clickable-icon icon_announcement notification-bell-icon"></span>
        <span class="notification-title">{notification.chatTitle || notification.title || ''}</span>
        <button
            class="notification-dismiss"
            onclick={handleDismiss}
            aria-label="Dismiss notification"
        >
            <span class="clickable-icon icon_close"></span>
        </button>
    </div>
    
    <!-- Content row with avatar and message -->
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="notification-content" onclick={handleNotificationClick}>
        <div class="notification-avatar">
            {#if notification.avatarUrl}
                <img src={notification.avatarUrl} alt="" class="avatar-image" />
            {:else}
                <!-- Default mate avatar with user icon -->
                <div class="avatar-placeholder">
                    <span class="clickable-icon icon_user avatar-user-icon"></span>
                </div>
            {/if}
            <!-- AI sparkle badge -->
            <div class="avatar-badge">
                <span class="clickable-icon icon_ai avatar-badge-icon"></span>
            </div>
        </div>
        <div class="notification-message-wrapper">
            <span class="notification-message-primary">{notification.message}</span>
        </div>
    </div>
    
    <!-- Reply input section -->
    {#if isExpanded}
        <div class="notification-reply-section" transition:slide={{ duration: 200 }}>
            <div
                class="notification-reply-input"
                bind:this={editorElement}
                class:focused={isFocused}
            ></div>
            <button
                class="notification-send-btn"
                onclick={handleSendReply}
                disabled={!replyText.trim()}
                aria-label="Send reply"
            >
                {$text('enter_message.send.text', { default: 'Send' })}
            </button>
        </div>
    {:else}
        <!-- Collapsed reply button -->
        <button
            class="notification-reply-button"
            onclick={handleReplyClick}
        >
            {$text('notifications.click_to_respond.text')}
        </button>
    {/if}
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
    .notification-bell-icon {
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
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
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
        cursor: pointer;
    }
    
    .notification-content:hover {
        opacity: 0.9;
    }
    
    .notification-avatar {
        position: relative;
        width: 40px;
        height: 40px;
        flex-shrink: 0;
    }
    
    .avatar-image {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        object-fit: cover;
    }
    
    .avatar-placeholder {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background-color: var(--color-grey-30);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    /* User icon inside avatar placeholder */
    .avatar-user-icon {
        width: 24px;
        height: 24px;
        background: var(--color-grey-60);
    }
    
    .avatar-badge {
        position: absolute;
        bottom: -2px;
        right: -2px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--color-primary);
        display: flex;
        align-items: center;
        justify-content: center;
        border: 2px solid var(--color-grey-20);
    }
    
    /* AI sparkle icon inside badge */
    .avatar-badge-icon {
        width: 10px;
        height: 10px;
        background: white;
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
        font-weight: 600;
        line-height: 1.4;
        color: var(--color-font-primary);
        /* Limit to 2 lines with ellipsis */
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    
    /* Reply button (collapsed state) */
    .notification-reply-button {
        all: unset;
        cursor: pointer;
        display: block;
        width: 100%;
        margin-top: 12px;
        padding: 12px 16px;
        background-color: var(--color-grey-0);
        border-radius: 8px;
        font-size: 14px;
        font-weight: 400;
        color: var(--color-grey-50);
        text-align: center;
        transition: background-color 0.2s ease;
    }
    
    .notification-reply-button:hover {
        background-color: var(--color-grey-10);
    }
    
    /* Reply input section (expanded state) */
    .notification-reply-section {
        margin-top: 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    
    .notification-reply-input {
        background-color: var(--color-grey-0);
        border-radius: 8px;
        padding: 12px 16px;
        min-height: 44px;
        font-size: 14px;
        line-height: 1.5;
        transition: box-shadow 0.2s ease;
    }
    
    .notification-reply-input.focused {
        box-shadow: 0 0 0 2px var(--color-primary-start);
    }
    
    /* TipTap editor styles */
    .notification-reply-input :global(.notification-reply-editor) {
        outline: none;
        min-height: 20px;
    }
    
    .notification-reply-input :global(.notification-reply-editor p) {
        margin: 0;
    }
    
    .notification-reply-input :global(.notification-reply-editor .is-editor-empty:first-child::before) {
        content: attr(data-placeholder);
        float: left;
        color: var(--color-grey-50);
        pointer-events: none;
        height: 0;
    }
    
    /* Send button */
    .notification-send-btn {
        align-self: flex-end;
        padding: 8px 20px;
        background-color: var(--color-button-primary);
        color: var(--color-font-button);
        border: none;
        border-radius: 20px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background-color 0.2s ease, opacity 0.2s ease;
    }
    
    .notification-send-btn:hover:not(:disabled) {
        background-color: var(--color-button-primary-hover);
    }
    
    .notification-send-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    /* Mobile responsiveness - 5px margin on each side */
    @media (max-width: 440px) {
        .notification {
            width: calc(100vw - 10px);
            margin: 0 5px;
        }
    }
</style>
