<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import type { MessageRole } from '../../types/chat';

    // Props using Svelte 5 $props()
    interface Props {
        x?: number;
        y?: number;
        show?: boolean;
        onClose?: () => void;
        onCopy?: () => void;
        onSelect?: () => void;
        onDelete?: () => void;
        messageId?: string;
        userMessageId?: string; // The user message ID that triggered this assistant response (used for cost lookup)
        role?: MessageRole;
    }
    let { 
        x = 0,
        y = 0,
        show = false,
        onClose,
        onCopy,
        onSelect,
        onDelete,
        messageId = undefined,
        userMessageId = undefined,
        role = undefined
    }: Props = $props();
    
    // Two-step delete confirmation state
    let confirmingDelete = $state(false);

    let menuElement = $state<HTMLDivElement>();
    let adjustedX = $state(x);
    let adjustedY = $state(y);
    let showBelow = $state(false);
    
    // State for message credits (only for assistant messages)
    let messageCredits = $state<number | null>(null);
    
    // Format credits with dots as thousand separators (European style)
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }
    
    // Fetch message credits when menu is shown (only for authenticated assistant messages)
    // Usage records are stored with the user's message ID (the message that triggered the AI response),
    // so we use userMessageId for the API lookup, falling back to messageId if not available
    $effect(() => {
        const lookupId = userMessageId || messageId;
        if (show && lookupId && role === 'assistant' && $authStore.isAuthenticated) {
            const endpoint = `${getApiEndpoint(apiEndpoints.usage.messageCost)}?message_id=${encodeURIComponent(lookupId)}`;
            fetch(endpoint, { credentials: 'include' })
                .then(res => res.ok ? res.json() : null)
                .then(data => {
                    if (data && typeof data.credits === 'number') {
                        messageCredits = data.credits;
                    } else {
                        messageCredits = null;
                    }
                })
                .catch(() => {
                    messageCredits = null;
                });
        } else {
            messageCredits = null;
        }
    });

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
            const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
            if (spaceBelow > spaceAbove + 50) {
                shouldShowBelow = true;
            }
        }

        return { newX, newY, shouldShowBelow };
    }

    // Adjust positioning to prevent cutoff
    $effect(() => {
        if (show) {
            const estimatedWidth = 150;
            const estimatedHeight = (role === 'assistant' && messageId) ? 180 : 150;
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
                
                if (Math.abs(actualWidth - estimatedWidth) > 20 || Math.abs(actualHeight - estimatedHeight) > 20) {
                    const refined = calculatePosition(actualWidth, actualHeight);
                    adjustedX = refined.newX;
                    adjustedY = refined.newY;
                    showBelow = refined.shouldShowBelow;
                }
            });
        }
    });

    // Reset confirm state when menu is closed
    $effect(() => {
        if (!show) {
            confirmingDelete = false;
        }
    });

    // Handle clicking outside the menu
    function handleClickOutside(event: MouseEvent | TouchEvent) {
        if (menuElement && !menuElement.contains(event.target as Node)) {
            onClose?.();
        }
    }

    // Unified handler for menu actions
    function handleAction(action: 'copy' | 'select' | 'delete', event: Event) {
        event.stopPropagation();
        event.preventDefault();
        
        console.debug('[MessageContextMenu] Action triggered:', action);
        
        if (action === 'copy') onCopy?.();
        if (action === 'select') onSelect?.();
        if (action === 'delete') {
            if (!confirmingDelete) {
                // First click: show confirmation
                confirmingDelete = true;
                return; // Don't close the menu yet
            }
            // Second click (confirm): execute delete
            confirmingDelete = false;
            onDelete?.();
        }
        onClose?.();
    }

    // Add scroll handler
    function handleScroll() {
        if (show) {
            onClose?.();
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
            // Cleanup: remove menu from body if it's still there
            if (menuElement && menuElement.parentNode === document.body) {
                document.body.removeChild(menuElement);
            }
        };
    });

    // Render menu at body level to avoid stacking context issues
    $effect(() => {
        if (show && menuElement) {
            tick().then(() => {
                if (menuElement && menuElement.parentNode && menuElement.parentNode !== document.body) {
                    document.body.appendChild(menuElement);
                }
            });
        } else if (!show && menuElement && menuElement.parentNode === document.body) {
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
        {#if messageCredits !== null && messageCredits > 0}
            <div class="message-credits">
                <div class="clickable-icon icon_coins"></div>
                {formatCredits(messageCredits)} {$text('chats.context_menu.credits.text', { default: 'credits' })}
            </div>
        {/if}
        
        <button
            class="menu-item copy"
            onclick={(event) => handleAction('copy', event)}
        >
            <div class="clickable-icon icon_copy"></div>
            {$text('chats.context_menu.copy.text', { default: 'Copy' })}
        </button>

        <button
            class="menu-item select"
            onclick={(event) => handleAction('select', event)}
        >
            <div class="clickable-icon icon_select"></div>
            {$text('chats.context_menu.select.text', { default: 'Select' })}
        </button>

        {#if onDelete}
            <div class="menu-separator"></div>
            <button
                class="menu-item delete"
                class:confirming={confirmingDelete}
                onclick={(event) => handleAction('delete', event)}
            >
                <div class="clickable-icon icon_delete"></div>
                {#if confirmingDelete}
                    {$text('chats.context_menu.confirm.text', { default: 'Confirm' })}
                {/if}
                {#if !confirmingDelete}
                    {$text('chats.context_menu.delete_message.text', { default: 'Delete' })}
                {/if}
            </button>
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
        z-index: 99999;
        isolation: isolate;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease-in-out;
        min-width: 140px;
    }
    
    /* Message credits displayed above the action buttons */
    .message-credits {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 16px;
        margin-bottom: 4px;
        color: var(--color-grey-50);
        font-size: 12px;
        font-variant-numeric: tabular-nums;
        border-bottom: 1px solid var(--color-grey-30);
    }
    
    .message-credits .clickable-icon {
        width: 14px;
        height: 14px;
        background: var(--color-grey-50);
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
        color: white;
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

    .menu-separator {
        height: 1px;
        background-color: var(--color-grey-30);
        margin: 4px 8px;
    }

    .menu-item.delete {
        color: var(--color-error, #ff4444);
    }

    .menu-item.delete .clickable-icon {
        background-color: var(--color-error, #ff4444);
    }

    .menu-item.delete.confirming {
        background-color: var(--color-error, #ff4444);
        color: white;
    }

    .menu-item.delete.confirming .clickable-icon {
        background-color: white;
    }

    .clickable-icon {
        width: 20px;
        height: 20px;
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background-color: white;
    }
</style>
