<script lang="ts">
    import { createEventDispatcher, onMount, tick } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../stores/authStore';

    interface Props {
        x?: number;
        y?: number;
        show?: boolean;
        suggestionText?: string;
        encryptedSuggestion?: string;
    }

    let {
        x = 0,
        y = 0,
        show = false,
        suggestionText = '',
        encryptedSuggestion = ''
    }: Props = $props();

    const dispatch: {
        (e: 'close' | 'delete', detail: string): void;
    } = createEventDispatcher();

    let menuElement = $state<HTMLDivElement>();
    let adjustedX = $state(x);
    let adjustedY = $state(y);
    let showBelow = $state(false);
    let deleteConfirmMode = $state(false);
    let deleteConfirmTimeout: number | undefined;

    // Calculate position to prevent cutoff
    function calculatePosition(menuWidth: number, menuHeight: number) {
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const padding = 10;
        const arrowHeight = 8;

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

        // Check if there's enough space above
        const spaceAbove = y - menuHeight - arrowHeight;

        if (spaceAbove < padding) {
            // Not enough space above, show below instead
            shouldShowBelow = true;
            // Check if there's enough space below
            const spaceBelow = viewportHeight - y - menuHeight - arrowHeight;
            if (spaceBelow < padding) {
                // Not enough space below either, position at viewport edge
                if (spaceAbove > spaceBelow) {
                    shouldShowBelow = false;
                    newY = menuHeight + arrowHeight + padding;
                } else {
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
            const estimatedWidth = 120;
            const estimatedHeight = 60;
            const initial = calculatePosition(estimatedWidth, estimatedHeight);
            adjustedX = initial.newX;
            adjustedY = initial.newY;
            showBelow = initial.shouldShowBelow;

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

    // Handle menu actions
    function handleMenuAction(action: Parameters<typeof dispatch>[0], event: MouseEvent | TouchEvent) {
        event.stopPropagation();
        event.preventDefault();

        console.debug('[NewChatSuggestionContextMenu] Menu action triggered:', action);

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

    // Single event handler for all input types
    function handleButtonClick(action: Parameters<typeof dispatch>[0], event: Event) {
        event.stopPropagation();
        event.preventDefault();

        console.debug('[NewChatSuggestionContextMenu] Button click handled:', action, 'Event type:', event.type);

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

    // Move the menu element to document.body when shown
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
        <button
            class="menu-item delete"
            onclick={(event) => handleButtonClick('delete', event)}
        >
            <div class="clickable-icon icon_delete"></div>
            {deleteConfirmMode ? $text('chats.context_menu.confirm.text') : $text('chats.context_menu.delete.text')}
        </button>
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
        min-width: 120px;
    }

    .menu-container.above {
        transform: translate(-50%, -100%);
    }

    .menu-container.below {
        transform: translate(-50%, 0);
    }

    .menu-container.show {
        opacity: 1;
        pointer-events: all;
    }

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
        -webkit-tap-highlight-color: transparent;
        -webkit-touch-callout: none;
        -webkit-user-select: none;
        user-select: none;
        min-height: 44px;
        min-width: 44px;
    }

    .menu-item:hover {
        background-color: var(--color-grey-20);
    }

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