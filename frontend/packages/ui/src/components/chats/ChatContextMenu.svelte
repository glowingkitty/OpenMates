<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { _ } from 'svelte-i18n'; // Import translation function
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
    }
    let { 
        x = 0,
        y = 0,
        show = false,
        chat,
        hideDelete = false,
        hideDownload = false,
        hideCopy = false
    }: Props = $props();

    const dispatch: {
        (e: 'close' | 'delete' | 'download' | 'copy', detail: string): void;
    } = createEventDispatcher();
    let menuElement = $state<HTMLDivElement>();
    let adjustedX = $state(x);
    let adjustedY = $state(y);
    let deleteConfirmMode = $state(false);
    let deleteConfirmTimeout: number | undefined;

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


    // Unified handler for both mouse and touch events
    function handleMenuAction(action: Parameters<typeof dispatch>[0], event: MouseEvent | TouchEvent) {
        event.stopPropagation();
        event.preventDefault();
        
        console.debug('[ChatContextMenu] Menu action triggered:', action, 'Event type:', event.type);

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
        {#if !hideDownload}
            <button 
                class="menu-item download"
                onclick={(event) => handleButtonClick('download', event)}
            >
                <div class="clickable-icon icon_download"></div>
                {$_('chats.context_menu.download.text', { default: 'Download' })}
            </button>
        {/if}
        
        {#if !hideCopy}
            <button 
                class="menu-item copy"
                onclick={(event) => handleButtonClick('copy', event)}
            >
                <div class="clickable-icon icon_copy"></div>
                {$_('chats.context_menu.copy.text', { default: 'Copy' })}
            </button>
        {/if}
        
        {#if !hideDelete}
            <button
                class="menu-item delete"
                onclick={(event) => handleButtonClick('delete', event)}
            >
                <div class="clickable-icon icon_delete"></div>
                {deleteConfirmMode ? $_('chats.context_menu.confirm.text', { default: 'Confirm' }) : $_('chats.context_menu.delete.text', { default: 'Delete' })}
            </button>
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
</style>
