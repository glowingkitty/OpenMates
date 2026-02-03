<script lang="ts">
    import { createEventDispatcher, onMount, tick } from 'svelte';
    import { text } from '@repo/ui'; // Import text store for translations
    import type { Chat } from '../../types/chat';
    import { authStore } from '../../stores/authStore'; // Import authStore to check authentication
    import { isDemoChat, isLegalChat, isPublicChat } from '../../demo_chats'; // Import chat type checks

    // Props using Svelte 5 $props()
    interface Props {
        x?: number;
        y?: number;
        show?: boolean;
        chat?: Chat;
        hideDelete?: boolean;
        hideDownload?: boolean;
        hideCopy?: boolean;
        selectMode?: boolean; // Whether we're in select mode (managed by Chats.svelte)
        selectedChatIds?: Set<string>; // Set of selected chat IDs (managed by Chats.svelte)
    }
    let { 
        x = 0,
        y = 0,
        show = false,
        chat,
        hideDelete = false,
        hideDownload = false,
        hideCopy = false,
        selectMode = false,
        selectedChatIds = new Set<string>()
    }: Props = $props();

    const dispatch: {
        (e: 'close' | 'delete' | 'download' | 'copy' | 'hide' | 'unhide' | 'enterSelectMode' | 'unselect' | 'selectChat' | 'pin' | 'unpin' | 'markUnread', detail: string): void;
    } = createEventDispatcher();
    let menuElement = $state<HTMLDivElement>();
    let adjustedX = $state(x);
    let adjustedY = $state(y);
    let showBelow = $state(false); // Track whether menu should appear below clicked point
    let deleteConfirmMode = $state(false);
    let deleteConfirmTimeout: number | undefined;
    
    // Check if the current chat is selected
    let isChatSelected = $derived(chat ? selectedChatIds.has(chat.chat_id) : false);

    // Calculate initial position using estimated dimensions to prevent visual jump
    function calculatePosition(menuWidth: number, menuHeight: number) {
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const padding = 10; // Minimum distance from viewport edges
        const arrowHeight = 8; // Height of the arrow

        let newX = x;
        let newY = y;
        let shouldShowBelow = false;

        // Adjust X if it goes off the right edge
        if (newX + menuWidth/2 > viewportWidth - padding) {
            newX = viewportWidth - menuWidth/2 - padding;
        }
        // Adjust X if it goes off the left edge
        if (newX - menuWidth/2 < padding) {
            newX = menuWidth/2 + padding;
        }

        // Check if there's enough space above the clicked point
        // Menu appears above by default (transform: translate(-50%, -100%))
        // So we need to check if y - menuHeight - arrowHeight >= padding
        const spaceAbove = y - menuHeight - arrowHeight;
        
        if (spaceAbove < padding) {
            // Not enough space above, show below instead
            shouldShowBelow = true;
            // Check if there's enough space below
            const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
            if (spaceBelow < padding) {
                // Not enough space below either, position at viewport edge
                if (spaceAbove > spaceBelow) {
                    // More space above, show above but adjust Y
                    shouldShowBelow = false;
                    newY = menuHeight + arrowHeight + padding;
                } else {
                    // More space below, show below but adjust Y
                    shouldShowBelow = true;
                    newY = viewportHeight - menuHeight - arrowHeight - padding;
                }
            }
        } else {
            // Enough space above, check if we should still show below for better UX
            // (e.g., if clicked point is very high on screen)
            const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
            // Only show below if there's significantly more space below
            if (spaceBelow > spaceAbove + 50) {
                shouldShowBelow = true;
            }
        }

        return { newX, newY, shouldShowBelow };
    }

    // Adjust positioning to prevent cutoff
    $effect(() => {
        if (show) {
            // First, calculate with estimated dimensions to prevent visual jump
            const estimatedWidth = 150;
            const estimatedHeight = 100;
            const initial = calculatePosition(estimatedWidth, estimatedHeight);
            adjustedX = initial.newX;
            adjustedY = initial.newY;
            showBelow = initial.shouldShowBelow;

            // Then refine with actual dimensions after render
            requestAnimationFrame(() => {
                if (!menuElement) return;
                
                const menuRect = menuElement.getBoundingClientRect();
                const actualWidth = menuRect.width || estimatedWidth;
                const actualHeight = menuRect.height || estimatedHeight;
                
                // Only recalculate if dimensions differ significantly
                if (Math.abs(actualWidth - estimatedWidth) > 20 || Math.abs(actualHeight - estimatedHeight) > 20) {
                    const refined = calculatePosition(actualWidth, actualHeight);
                    adjustedX = refined.newX;
                    adjustedY = refined.newY;
                    showBelow = refined.shouldShowBelow;
                }
            });
        } else {
            adjustedX = x;
            adjustedY = y;
            showBelow = false;
        }
    });

    // Handle clicking outside the menu
    function handleClickOutside(event: MouseEvent | TouchEvent) {
        if (menuElement && !menuElement.contains(event.target as Node)) {
            dispatch('close', 'close');
        }
    }


    // No local select mode management - this is handled by Chats.svelte

    // Unified handler for both mouse and touch events
    function handleMenuAction(action: Parameters<typeof dispatch>[0], event: MouseEvent | TouchEvent) {
        event.stopPropagation();
        event.preventDefault();

        console.debug('[ChatContextMenu] Menu action triggered:', action, 'Event type:', event.type);

        // Handle enter select mode
        if (action === 'enterSelectMode') {
            dispatch('enterSelectMode', 'enterSelectMode');
            dispatch('close', 'close');
            return;
        }

        // Handle unselect action (when in select mode and chat is selected)
        if (action === 'unselect') {
            if (chat?.chat_id) {
                dispatch('unselect', chat.chat_id);
            }
            dispatch('close', 'close');
            return;
        }

        // Handle select action (when in select mode and chat is not selected)
        if (action === 'selectChat') {
            if (chat?.chat_id) {
                dispatch('selectChat', chat.chat_id);
            }
            dispatch('close', 'close');
            return;
        }

        if (action === 'delete') {
            if (!deleteConfirmMode) {
                deleteConfirmMode = true;
                deleteConfirmTimeout = window.setTimeout(() => {
                    deleteConfirmMode = false;
                }, 3000);
                return;
            }
            if (deleteConfirmTimeout) {
                clearTimeout(deleteConfirmTimeout);
            }
        }

        dispatch(action, action);
        dispatch('close', 'close');
    }


    // Single event handler that works for all input types (iOS-compatible)
    function handleButtonClick(action: Parameters<typeof dispatch>[0], event: Event) {
        event.stopPropagation();
        event.preventDefault();
        
        console.debug('[ChatContextMenu] Button click handled:', action, 'Event type:', event.type);
        
        // Handle the action with appropriate delay for touch events
        if (event.type === 'touchend') {
            setTimeout(() => {
                handleMenuAction(action, event as TouchEvent);
            }, 10);
        } else {
            handleMenuAction(action, event as MouseEvent);
        }
    }

    // Add scroll handler
    function handleScroll() {
        if (show) {
            dispatch('close', 'close');
        }
    }

    // Add and remove event listeners
    onMount(() => {
        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('touchstart', handleClickOutside);
        document.addEventListener('scroll', handleScroll, true);

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('touchstart', handleClickOutside);
            document.removeEventListener('scroll', handleScroll, true);
            if (deleteConfirmTimeout) {
                clearTimeout(deleteConfirmTimeout);
            }
            // Cleanup: remove menu from body if it's still there
            if (menuElement && menuElement.parentNode === document.body) {
                document.body.removeChild(menuElement);
            }
        };
    });

    $effect(() => {
        if (!show) {
            deleteConfirmMode = false;
            if (deleteConfirmTimeout) {
                clearTimeout(deleteConfirmTimeout);
            }
        }
    });

    // Render menu at body level to avoid stacking context issues
    // Move the menu element to document.body when shown to escape any parent stacking contexts
    $effect(() => {
        if (show && menuElement) {
            // Wait for element to be rendered in DOM first, then move to body
            tick().then(() => {
                if (menuElement && menuElement.parentNode && menuElement.parentNode !== document.body) {
                    // Move to body to escape stacking context
                    document.body.appendChild(menuElement);
                }
            });
        } else if (!show && menuElement && menuElement.parentNode === document.body) {
            // Cleanup: remove from body when hidden
            document.body.removeChild(menuElement);
        }
    });
</script>

{#if show}
    <div
        class="menu-container {show ? 'show' : ''} {showBelow ? 'below' : 'above'}"
        style="--menu-x: {adjustedX}px; --menu-y: {adjustedY}px;"
        bind:this={menuElement}
    >
        {#if selectMode}
            <!-- In select mode: show different options based on whether this chat is selected -->
            {#if isChatSelected}
                <!-- Chat is selected: show bulk actions and unselect -->
                {#if !hideDownload}
                    <button
                        class="menu-item download"
                        onclick={(event) => handleButtonClick('download', event)}
                    >
                        <div class="clickable-icon icon_download"></div>
                        {$text('chats.context_menu.download_selected.text', { default: 'Download selected' })}
                    </button>
                {/if}

                {#if !hideCopy}
                    <button
                        class="menu-item copy"
                        onclick={(event) => handleButtonClick('copy', event)}
                    >
                        <div class="clickable-icon icon_copy"></div>
                        {$text('chats.context_menu.copy_selected.text', { default: 'Copy selected' })}
                    </button>
                {/if}

                {#if !hideDelete}
                    <button
                        class="menu-item delete"
                        onclick={(event) => handleButtonClick('delete', event)}
                    >
                        <div class="clickable-icon icon_delete"></div>
                        {deleteConfirmMode ? $text('chats.context_menu.confirm.text') : $text('chats.context_menu.delete_selected.text', { default: 'Delete selected' })}
                    </button>
                {/if}

                <button
                    class="menu-item unselect"
                    onclick={(event) => handleButtonClick('unselect', event)}
                >
                    <div class="clickable-icon icon_close"></div>
                    {$text('chats.context_menu.unselect.text', { default: 'Unselect' })}
                </button>
            {:else}
                <!-- Chat is not selected: show only select option -->
                <button
                    class="menu-item select"
                    onclick={(event) => handleButtonClick('selectChat', event)}
                >
                    <div class="clickable-icon icon_select"></div>
                    {$text('chats.context_menu.select.text')}
                </button>
            {/if}
        {:else}
            <!-- Not in select mode: show normal menu with option to enter select mode -->
            <button
                class="menu-item select"
                onclick={(event) => handleButtonClick('enterSelectMode', event)}
            >
                <div class="clickable-icon icon_select"></div>
                {$text('chats.context_menu.select.text')}
            </button>

            {#if !hideDownload}
                <button
                    class="menu-item download"
                    onclick={(event) => handleButtonClick('download', event)}
                >
                    <div class="clickable-icon icon_download"></div>
                    {$text('chats.context_menu.download.text')}
                </button>
            {/if}

            {#if !hideCopy}
                <button
                    class="menu-item copy"
                    onclick={(event) => handleButtonClick('copy', event)}
                >
                    <div class="clickable-icon icon_copy"></div>
                    {$text('chats.context_menu.copy.text')}
                </button>
            {/if}

            {#if chat && !chat.is_incognito && !(chat as any).is_hidden && !isPublicChat(chat.chat_id)}
                <button
                    class="menu-item hide"
                    class:disabled={!$authStore.isAuthenticated}
                    disabled={!$authStore.isAuthenticated}
                    onclick={(event) => {
                        if ($authStore.isAuthenticated) {
                            handleButtonClick('hide', event);
                        }
                    }}
                >
                    <div class="clickable-icon icon_hidden"></div>
                    {$text('chats.context_menu.hide.text', { default: 'Hide' })}
                </button>
            {/if}

            {#if chat && (chat as any).is_hidden}
                <button
                    class="menu-item unhide"
                    class:disabled={!$authStore.isAuthenticated}
                    disabled={!$authStore.isAuthenticated}
                    onclick={(event) => {
                        if ($authStore.isAuthenticated) {
                            handleButtonClick('unhide', event);
                        }
                    }}
                >
                    <div class="clickable-icon icon_unhide"></div>
                    {$text('chats.context_menu.unhide.text', { default: 'Unhide' })}
                </button>
            {/if}

            {#if chat && !chat.is_incognito && !isPublicChat(chat.chat_id)}
                {#if chat.pinned}
                    <button
                        class="menu-item unpin"
                        class:disabled={!$authStore.isAuthenticated}
                        disabled={!$authStore.isAuthenticated}
                        onclick={(event) => {
                            if ($authStore.isAuthenticated) {
                                handleButtonClick('unpin', event);
                            }
                        }}
                    >
                        <div class="clickable-icon icon_pin_off"></div>
                        {$text('chats.context_menu.unpin.text', { default: 'Unpin' })}
                    </button>
                {:else}
                    <button
                        class="menu-item pin"
                        class:disabled={!$authStore.isAuthenticated}
                        disabled={!$authStore.isAuthenticated}
                        onclick={(event) => {
                            if ($authStore.isAuthenticated) {
                                handleButtonClick('pin', event);
                            }
                        }}
                    >
                        <div class="clickable-icon icon_pin"></div>
                        {$text('chats.context_menu.pin.text', { default: 'Pin' })}
                    </button>
                {/if}
            {/if}

            {#if chat && !chat.is_incognito && !isPublicChat(chat.chat_id)}
                <button
                    class="menu-item mark-unread"
                    onclick={(event) => handleButtonClick('markUnread', event)}
                >
                    <div class="clickable-icon icon_mail"></div>
                    {$text('chats.context_menu.mark_unread.text', { default: 'Mark unread' })}
                </button>
            {/if}

            {#if !hideDelete && !(chat && (isDemoChat(chat.chat_id) || isLegalChat(chat.chat_id)) && !$authStore.isAuthenticated)}
                <button
                    class="menu-item delete"
                    onclick={(event) => handleButtonClick('delete', event)}
                >
                    <div class="clickable-icon icon_delete"></div>
                    {deleteConfirmMode ? $text('chats.context_menu.confirm.text') : $text('chats.context_menu.delete.text')}
                </button>
            {/if}
        {/if}
    </div>
{/if}

<style>
    .menu-container {
        position: fixed;
        left: var(--menu-x);
        top: var(--menu-y);
        background: var(--color-grey-blue);
        border-radius: 12px;
        padding: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 99999; /* Very high z-index to ensure it's above everything */
        isolation: isolate; /* Create new stacking context */
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease-in-out;
        min-width: 120px;
    }

    /* Position menu above clicked point (default) */
    .menu-container.above {
        transform: translate(-50%, -100%);
    }

    /* Position menu below clicked point */
    .menu-container.below {
        transform: translate(-50%, 0);
    }

    .menu-container.show {
        opacity: 1;
        pointer-events: all;
    }

    /* Arrow pointing down (when menu is above clicked point) */
    .menu-container.above::after {
        content: '';
        position: absolute;
        bottom: -8px;
        left: 50%;
        transform: translateX(-50%);
        border-left: 8px solid transparent;
        border-right: 8px solid transparent;
        border-top: 8px solid var(--color-grey-blue);
    }

    /* Arrow pointing up (when menu is below clicked point) */
    .menu-container.below::after {
        content: '';
        position: absolute;
        top: -8px;
        left: 50%;
        transform: translateX(-50%);
        border-left: 8px solid transparent;
        border-right: 8px solid transparent;
        border-bottom: 8px solid var(--color-grey-blue);
    }

    .menu-item {
        all: unset;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 16px;
        border-radius: 25px;
        cursor: pointer;
        transition: background-color 0.2s ease;
        width: 100%;
        box-sizing: border-box;
        /* iOS-specific touch improvements */
        -webkit-tap-highlight-color: transparent;
        -webkit-touch-callout: none;
        -webkit-user-select: none;
        user-select: none;
        /* Ensure proper touch target size for iOS */
        min-height: 44px;
        min-width: 44px;
    }

    .menu-item:hover {
        background-color: var(--color-grey-20);
    }

    /* iOS touch feedback */
    .menu-item:active {
        background-color: var(--color-grey-20);
        transform: scale(0.98);
    }

    .menu-item.delete {
        color: #E80000;
    }

    .menu-item.delete .clickable-icon {
        background: #E80000;
    }

    .menu-item.select {
        color: var(--color-primary);
    }

    .menu-item.select .clickable-icon {
        background: var(--color-primary);
    }

    .menu-item.unselect {
        color: var(--color-grey-60);
    }

    .menu-item.unselect .clickable-icon {
        background: var(--color-grey-60);
    }

    /* Hide and unhide buttons use default text and icon colors for better visibility */

    .menu-item.pin {
        color: var(--color-primary);
    }

    .menu-item.pin .clickable-icon {
        background: var(--color-primary);
    }

    .menu-item.unpin {
        color: var(--color-grey-60);
    }

    .menu-item.unpin .clickable-icon {
        background: var(--color-grey-60);
    }

    .menu-item.disabled {
        opacity: 0.5;
        cursor: not-allowed !important;
        pointer-events: none;
    }

    .menu-item.disabled:hover {
        background-color: transparent;
    }

    .menu-item.disabled:active {
        transform: none;
    }

    .menu-item.hide.disabled,
    .menu-item.unhide.disabled {
        cursor: not-allowed !important;
    }
</style>
