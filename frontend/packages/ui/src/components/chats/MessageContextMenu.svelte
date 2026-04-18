<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../stores/authStore';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import { chatDebugStore } from '../../stores/chatDebugStore'; // Chat debug mode toggle
    import { userProfile } from '../../stores/userProfile';
    import { isMobile } from '../../utils/platform';
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
        onFork?: () => void;        // Callback to open the fork conversation settings panel
        onEdit?: () => void;        // Callback to enter edit mode for a user message
        onHighlight?: () => void;   // Callback to add a yellow highlight to the current selection
        onHighlightAndComment?: () => void; // Highlight AND open the comment popover immediately
        disableDelete?: boolean; // When true, shows delete button greyed out (e.g., first message in chat)
        disableFork?: boolean;   // When true, fork is disabled (e.g., incognito chat)
        /** Hide the Highlight / Highlight & comment items. True when there is no
         *  valid text selection inside this message, or when the viewer is not
         *  authenticated. Separate from the "pass no callback" case so the parent
         *  can offer the action but show it disabled if needed in future. */
        hideHighlight?: boolean;
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
        onFork,
        onEdit,
        onHighlight,
        onHighlightAndComment,
        disableDelete = false,
        disableFork = false,
        hideHighlight = false,
        messageId = undefined,
        userMessageId = undefined,
        role = undefined
    }: Props = $props();
    
    // Touch device detection — evaluated once (device type doesn't change mid-session)
    const isTouchDevice = isMobile();

    // Two-step delete confirmation state
    let confirmingDelete = $state(false);

    let menuElement = $state<HTMLDivElement>();
    // Initialised to 0; the position-calculation $effect below runs before first
    // render and overrides these with the viewport-adjusted values. Keeping the
    // initializer literal avoids Svelte 5 `state_referenced_locally` warnings
    // that fire when $state() captures a prop.
    let adjustedX = $state(0);
    let adjustedY = $state(0);
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
    function handleAction(action: 'copy' | 'select' | 'delete' | 'fork' | 'edit' | 'highlight' | 'highlight_and_comment', event: Event) {
        event.stopPropagation();
        event.preventDefault();

        console.debug('[MessageContextMenu] Action triggered:', action);

        if (action === 'copy') onCopy?.();
        if (action === 'select') onSelect?.();
        if (action === 'edit') onEdit?.();
        if (action === 'highlight') onHighlight?.();
        if (action === 'highlight_and_comment') onHighlightAndComment?.();
        if (action === 'fork') {
            if (!disableFork) onFork?.();
        }
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

    async function handleToggleDebug(event: Event) {
        event.stopPropagation();
        event.preventDefault();
        await chatDebugStore.toggle();
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
                {formatCredits(messageCredits)} {$text('common.credits')}
            </div>
        {/if}
        
        <button
            class="menu-item copy"
            onclick={(event) => handleAction('copy', event)}
        >
            <div class="clickable-icon icon_copy"></div>
            {$text('common.copy')}
        </button>

        {#if isTouchDevice}
            <button
                class="menu-item select"
                onclick={(event) => handleAction('select', event)}
            >
                <div class="clickable-icon icon_select"></div>
                {$text('chats.context_menu.select')}
            </button>
        {/if}

        {#if onEdit}
            <button
                class="menu-item edit"
                onclick={(event) => handleAction('edit', event)}
            >
                <div class="clickable-icon icon_modify"></div>
                {$text('chats.context_menu.edit')}
            </button>
        {/if}

        <!-- Highlight (text selection) — only shown when the parent confirms a
             valid selection exists inside the message, the viewer is authenticated,
             and an onHighlight handler is wired. Stays visually consistent with
             the other action rows. -->
        {#if onHighlight && !hideHighlight && $authStore.isAuthenticated}
            <button
                class="menu-item highlight"
                data-testid="chat-context-highlight"
                onclick={(event) => handleAction('highlight', event)}
            >
                <div class="clickable-icon icon_quote"></div>
                {$text('chats.context_menu.highlight')}
            </button>
        {/if}
        {#if onHighlightAndComment && !hideHighlight && $authStore.isAuthenticated}
            <button
                class="menu-item highlight-and-comment"
                data-testid="chat-context-highlight-and-comment"
                onclick={(event) => handleAction('highlight_and_comment', event)}
            >
                <div class="clickable-icon icon_quote"></div>
                {$text('chats.context_menu.highlight_and_comment')}
            </button>
        {/if}

        <!-- Fork conversation — always visible, disabled when not authenticated or fork unavailable -->
        <button
            class="menu-item fork"
            data-testid="chat-context-fork"
            class:disabled={disableFork || !$authStore.isAuthenticated}
            disabled={disableFork || !$authStore.isAuthenticated}
            onclick={(event) => handleAction('fork', event)}
        >
            <div class="clickable-icon icon_planning"></div>
            {$text('chats.context_menu.fork')}
        </button>

        <div class="menu-separator"></div>
        <button
            class="menu-item delete"
            class:confirming={confirmingDelete}
            class:disabled={disableDelete || !$authStore.isAuthenticated}
            disabled={disableDelete || !$authStore.isAuthenticated}
            onclick={(event) => handleAction('delete', event)}
        >
            <div class="clickable-icon icon_delete"></div>
            {#if confirmingDelete}
                {$text('chats.context_menu.confirm')}
            {/if}
            {#if !confirmingDelete}
                {$text('common.delete')}
            {/if}
        </button>

        {#if $userProfile.is_admin}
            <!-- Debug mode toggle: admin only -->
            <div class="menu-separator"></div>
            <button
                data-testid="context-menu-toggle-debug"
                class="menu-item debug"
                class:debug-active={$chatDebugStore.rawTextMode}
                onclick={handleToggleDebug}
            >
                <div class="clickable-icon icon_bug"></div>
                {$chatDebugStore.rawTextMode ? $text('chats.context_menu.end_debugging') : $text('chats.context_menu.start_debugging')}
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
        border-radius: var(--radius-5);
        padding: var(--spacing-4);
        box-shadow: var(--shadow-md);
        z-index: var(--z-index-popover);
        isolation: isolate;
        opacity: 0;
        pointer-events: none;
        transition: opacity var(--duration-normal) var(--easing-in-out);
        min-width: 140px;
    }
    
    /* Message credits displayed above the action buttons */
    .message-credits {
        display: flex;
        align-items: center;
        gap: var(--spacing-3);
        padding: var(--spacing-4) var(--spacing-8);
        margin-bottom: var(--spacing-2);
        color: var(--color-grey-50);
        font-size: var(--font-size-xxs);
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
        gap: var(--spacing-4);
        padding: var(--spacing-6) var(--spacing-8);
        border-radius: 25px;
        cursor: pointer;
        transition: background-color var(--duration-normal) var(--easing-default);
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
        margin: var(--spacing-2) var(--spacing-4);
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

    .menu-item.delete.disabled {
        opacity: 0.35;
        cursor: not-allowed;
        pointer-events: none;
    }

    .menu-item.fork {
        color: white;
    }

    .menu-item.fork .clickable-icon {
        background-color: white;
    }

    /* Highlight + Highlight-and-comment: yellow-tinted icon so the action is
       visually associated with the yellow annotation layer. Label stays white
       to keep the menu readable on the dark background. */
    .menu-item.highlight .clickable-icon,
    .menu-item.highlight-and-comment .clickable-icon {
        background-color: var(--color-highlight-yellow-solid, #ffd500);
    }

    .menu-item.fork.disabled {
        opacity: 0.35;
        cursor: not-allowed;
        pointer-events: none;
    }

    /* Debug mode button */
    .menu-item.debug {
        color: var(--color-font-secondary);
    }

    .menu-item.debug .clickable-icon {
        background: var(--color-font-secondary);
    }

    .menu-item.debug.debug-active {
        color: var(--color-warning, #e67e22);
    }

    .menu-item.debug.debug-active .clickable-icon {
        background: var(--color-warning, #e67e22);
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
