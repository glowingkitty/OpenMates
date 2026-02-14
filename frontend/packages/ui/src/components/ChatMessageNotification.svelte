<!-- frontend/packages/ui/src/components/ChatMessageNotification.svelte -->
<!--
    Chat message notification component for background chat messages.
    Shows the chat title, message preview, mate profile image, and includes a reply input.
    
    Features:
    - Mate profile image based on category (like assistant messages in ReadonlyMessage)
    - AI sparkle badge on profile image
    - 430px width or 100% viewport (with 5px margin on smaller screens)
    - var(--color-grey-20) background
    - Auto-dismisses after duration unless user interacts (click/tap/hover)
    - Reply input with Enter to send, Shift+Enter for newline
    - Clicking anywhere on notification interrupts auto-dismiss timer
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import { onDestroy, tick } from 'svelte';
    import { notificationStore, type Notification } from '../stores/notificationStore';
    import { text } from '@repo/ui';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import Placeholder from '@tiptap/extension-placeholder';
    import { chatDB } from '../services/db';
    import { chatSyncService } from '../services/chatSyncService';
    import { websocketStatus } from '../stores/websocketStatusStore';
    import { get } from 'svelte/store';
    import type { Message } from '../types/chat';
    
    // Note: icons.css and mates.css are loaded globally via index.ts and +layout.svelte
    // No need to import them here - global icon classes and mate-profile classes are available
    
    // Props using Svelte 5 runes
    let { notification }: { notification: Notification } = $props();
    
    // State
    let isExpanded = $state(false); // Whether the reply input is expanded
    let replyText = $state('');
    let editorElement = $state<HTMLElement | null>(null);
    let editor: Editor | null = null;
    let isFocused = $state(false);
    let userInteracted = $state(false); // Track if user has interacted (clicked/tapped) to interrupt auto-dismiss
    
    /**
     * Handle notification dismissal
     */
    function handleDismiss(): void {
        notificationStore.removeNotification(notification.id);
    }
    
    /**
     * Interrupt auto-dismiss when user clicks/taps anywhere on notification.
     * Cancels the store-level auto-dismiss timer so the notification stays
     * visible until explicitly dismissed by the user.
     */
    function handleNotificationInteraction(): void {
        if (!userInteracted) {
            userInteracted = true;
            // Cancel the store-level auto-dismiss timer
            notificationStore.cancelAutoDismiss(notification.id);
        }
    }
    
    /**
     * Handle clicking the reply button to expand input
     */
    function handleReplyClick(event: MouseEvent): void {
        event.stopPropagation(); // Prevent navigating to chat
        handleNotificationInteraction();
        isExpanded = true;
        // Focus the editor after expansion
        tick().then(() => {
            editor?.commands.focus();
        });
    }
    
    /**
     * Handle clicking on notification content to navigate to chat
     */
    function handleNotificationClick(): void {
        handleNotificationInteraction();
        if (notification.chatId) {
            // Navigate to the chat using the correct hash format: #chat-id={chatId}
            window.location.hash = `chat-id=${notification.chatId}`;
            handleDismiss();
        }
    }
    
    /**
     * Handle sending the reply message directly to the background chat.
     * Sends via chatSyncService WITHOUT navigating to or switching the active chat.
     * This follows the same IndexedDB save + WebSocket send flow as the normal message pipeline.
     */
    async function handleSendReply(): Promise<void> {
        const trimmedText = replyText.trim();
        if (!trimmedText || !notification.chatId) return;
        
        const chatId = notification.chatId;
        
        try {
            // 1. Look up the existing chat in IndexedDB
            const existingChat = await chatDB.getChat(chatId);
            if (!existingChat) {
                console.error(`[ChatMessageNotification] Chat ${chatId} not found in IndexedDB, cannot send reply`);
                return;
            }
            
            // 2. Create message payload (same structure as sendHandlers.createMessagePayload)
            const messageId = `${chatId.slice(-10)}-${crypto.randomUUID()}`;
            const wsStatus = get(websocketStatus);
            const isConnected = wsStatus.status === 'connected';
            const initialStatus: Message['status'] = isConnected ? 'sending' : 'waiting_for_internet';
            
            const messagePayload: Message = {
                message_id: messageId,
                chat_id: chatId,
                role: 'user',
                content: trimmedText,
                status: initialStatus,
                created_at: Math.floor(Date.now() / 1000),
                sender_name: 'user',
                encrypted_content: null,
            };
            
            // 3. Save message to IndexedDB (chatDB handles encryption with chat key)
            await chatDB.saveMessage(messagePayload);
            
            // 4. Update chat metadata (increment messages_v, update timestamps)
            existingChat.messages_v = (existingChat.messages_v || 0) + 1;
            existingChat.last_edited_overall_timestamp = messagePayload.created_at;
            existingChat.updated_at = Math.floor(Date.now() / 1000);
            await chatDB.updateChat(existingChat);
            
            // 5. Dismiss the notification immediately so user sees feedback
            handleDismiss();
            
            // 6. Send message to backend via chatSyncService
            // CRITICAL: Do NOT call sendSetActiveChat — we don't want to switch chats
            await chatSyncService.sendNewMessage(messagePayload);
            
            // 7. Dispatch chatUpdated event so sidebar/chat list reflects the new message
            window.dispatchEvent(new CustomEvent('chatUpdated', {
                detail: { chat_id: chatId, chat: existingChat },
                bubbles: true,
                composed: true,
            }));
            
            console.info(`[ChatMessageNotification] Reply sent to chat ${chatId} without switching active chat`);
        } catch (error) {
            console.error('[ChatMessageNotification] Error sending reply:', error);
            notificationStore.error('Failed to send reply. Please try again.');
        }
    }
    
    /**
     * Pause auto-dismiss when user hovers over notification
     */
    function handleMouseEnter(): void {
        // Cancel the store-level timer on hover
        notificationStore.cancelAutoDismiss(notification.id);
    }
    
    /**
     * Resume auto-dismiss when user leaves notification (only if not interacted and not expanded)
     * Note: We don't restart the store timer here because we can't set store timers from here.
     * If the user hasn't interacted (clicked/tapped), the notification will remain until the
     * next hover-leave cycle. This is acceptable UX - hovering shows intent to interact.
     */
    function handleMouseLeave(): void {
        // If user hasn't clicked/tapped and hasn't expanded the reply, they just hovered briefly.
        // The auto-dismiss was already cancelled by hover. We don't restart it - hovering
        // counts as an interaction signal and the notification should stay visible.
    }
    
    // Initialize TipTap editor when the reply input element appears in the DOM.
    // The editorElement is inside an {#if isExpanded} block, so it's null on mount.
    // Using $effect ensures the editor is created when the element becomes available.
    $effect(() => {
        if (editorElement && !editor) {
            editor = new Editor({
                element: editorElement,
                extensions: [
                    StarterKit,
                    Placeholder.configure({
                        placeholder: 'Type your reply...',
                    }),
                ],
                content: '',
                onUpdate: ({ editor: ed }) => {
                    replyText = ed.getText();
                },
                onFocus: () => {
                    isFocused = true;
                    handleNotificationInteraction();
                },
                onBlur: () => {
                    isFocused = false;
                },
                editorProps: {
                    attributes: {
                        class: 'notification-reply-editor',
                    },
                    handleKeyDown: (_view, event) => {
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
        editor?.destroy();
    });
</script>

<!-- Chat message notification wrapper -->
<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions a11y_no_noninteractive_element_interactions -->
<div
    class="notification notification-chat-message"
    class:expanded={isExpanded}
    transition:slide={{ axis: 'y', duration: 300 }}
    role="alert"
    aria-live="polite"
    onmouseenter={handleMouseEnter}
    onmouseleave={handleMouseLeave}
    onclick={handleNotificationInteraction}
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
    
    <!-- Content row with mate profile image and message -->
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="notification-content" onclick={handleNotificationClick}>
        <div class="notification-avatar">
            {#if notification.avatarUrl}
                <img src={notification.avatarUrl} alt="" class="avatar-image" />
            {:else if notification.category}
                <!-- Mate profile image based on category (like assistant messages) -->
                <div class="mate-profile notification-mate-profile {notification.category}"></div>
            {:else}
                <!-- Default mate avatar with user icon -->
                <div class="avatar-placeholder">
                    <span class="clickable-icon icon_user avatar-user-icon"></span>
                </div>
                <!-- AI sparkle badge (only for non-mate-profile avatars, mate-profile has its own badge) -->
                <div class="avatar-badge">
                    <span class="clickable-icon icon_ai avatar-badge-icon"></span>
                </div>
            {/if}
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
                {$text('enter_message.send', { default: 'Send' })}
            </button>
        </div>
    {:else}
        <!-- Collapsed reply button -->
        <button
            class="notification-reply-button"
            onclick={handleReplyClick}
        >
            {$text('notifications.click_to_respond')}
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
        
        /* Enable pointer events (parent container has pointer-events: none) */
        pointer-events: auto;
        
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
    
    /* Mate profile image in notification - smaller than chat message (40px vs 60px) */
    /* Uses global .mate-profile class from mates.css for category-based background images */
    .notification-avatar :global(.notification-mate-profile) {
        width: 40px;
        height: 40px;
        margin: 0;
        opacity: 1;
        animation: none;
    }
    
    /* Adjust AI badge position for the smaller notification mate profile */
    .notification-avatar :global(.notification-mate-profile)::after {
        bottom: -4px;
        right: -4px;
        width: 16px;
        height: 16px;
    }
    
    .notification-avatar :global(.notification-mate-profile)::before {
        bottom: -2px;
        right: -2px;
        width: 10px;
        height: 10px;
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
    /* Use :global() to ensure mask-image from icons.css is applied */
    .avatar-placeholder :global(.avatar-user-icon) {
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
    /* Use :global() to ensure mask-image from icons.css is applied */
    .avatar-badge :global(.avatar-badge-icon) {
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
        cursor: text;
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
