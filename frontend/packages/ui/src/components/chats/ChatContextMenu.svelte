<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui'; // Import text store for translations
    import type { Chat } from '../../types/chat';

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
        (e: 'close' | 'delete' | 'download' | 'copy' | 'enterSelectMode' | 'unselect' | 'selectChat', detail: string): void;
    } = createEventDispatcher();
    let menuElement = $state<HTMLDivElement>();
    let adjustedX = $state(x);
    let adjustedY = $state(y);
    let deleteConfirmMode = $state(false);
    let deleteConfirmTimeout: number | undefined;
    
    // Check if the current chat is selected
    let isChatSelected = $derived(chat ? selectedChatIds.has(chat.chat_id) : false);

    // Adjust positioning to prevent cutoff
    $effect(() => {
        if (show) {
            // Use a more reliable positioning approach
            const viewportWidth = window.innerWidth;
            const menuWidth = 150; // Estimated menu width
            const menuHeight = 100; // Estimated menu height

            let newX = x;
            let newY = y;

            // Adjust X if it goes off the right edge
            if (newX + menuWidth/2 > viewportWidth) {
                newX = viewportWidth - menuWidth/2 - 10;
            }
            // Adjust X if it goes off the left edge
            if (newX - menuWidth/2 < 10) {
                newX = menuWidth/2 + 10;
            }

            // Adjust Y if it goes off the bottom edge (menu appears above cursor)
            if (newY - menuHeight < 10) {
                newY = newY + 20; // Show below cursor instead
            }
            // Adjust Y if it goes off the top edge
            if (newY < 10) {
                newY = 10;
            }

            adjustedX = newX;
            adjustedY = newY;
        } else {
            adjustedX = x;
            adjustedY = y;
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
</script>

{#if show}
    <div
        class="menu-container {show ? 'show' : ''}"
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

            {#if !hideDelete}
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
        transform: translate(-50%, -100%);
        background: var(--color-grey-blue);
        border-radius: 12px;
        padding: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 10000;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease-in-out;
        min-width: 120px;
    }

    .menu-container.show {
        opacity: 1;
        pointer-events: all;
    }

    /* Add a small arrow at the bottom */
    .menu-container::after {
        content: '';
        position: absolute;
        bottom: -8px;
        left: 50%;
        transform: translateX(-50%);
        border-left: 8px solid transparent;
        border-right: 8px solid transparent;
        border-top: 8px solid var(--color-grey-blue);
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
</style>
