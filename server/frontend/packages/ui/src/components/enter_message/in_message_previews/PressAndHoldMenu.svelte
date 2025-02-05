<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { _ } from 'svelte-i18n'; // Import translation function

    // Props
    export let x: number = 0;  // X position of menu
    export let y: number = 0;  // Y position of menu
    export let show: boolean = false;
    export let type: 'default' | 'pdf' | 'web' = 'default';  // Add type prop
    export let isYouTube: boolean = false;  // Add isYouTube prop

    const dispatch: {
        (e: 'close' | 'delete' | 'download' | 'view' | 'copy'): void;
    } = createEventDispatcher();
    let menuElement: HTMLDivElement;

    // Handle clicking outside the menu
    function handleClickOutside(event: MouseEvent | TouchEvent) {
        if (menuElement && !menuElement.contains(event.target as Node)) {
            dispatch('close');
        }
    }

    // Handle menu item clicks
    function handleMenuItemClick(action: Parameters<typeof dispatch>[0], event: MouseEvent) {
        event.stopPropagation();
        dispatch(action);
        dispatch('close');
    }

    // Add scroll handler
    function handleScroll() {
        if (show) {
            dispatch('close');
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
        };
    });
</script>

{#if show}
    <div 
        class="menu-container {show ? 'show' : ''}"
        style="--menu-x: {x}px; --menu-y: {y}px;"
        bind:this={menuElement}
    >
        <button 
            class="menu-item delete"
            on:click={(event) => handleMenuItemClick('delete', event)}
        >
            <div class="clickable-icon icon_delete"></div>
            {$_('enter_message.press_and_hold_menu.delete.text')}
        </button>
        
        {#if type === 'web' || isYouTube}
            <button 
                class="menu-item copy"
                on:click={(event) => handleMenuItemClick('copy', event)}
            >
                <div class="clickable-icon icon_copy"></div>
                {$_('enter_message.press_and_hold_menu.copy_link.text')}
            </button>
            <button 
                class="menu-item view"
                on:click={(event) => handleMenuItemClick('view', event)}
            >
                <div class="clickable-icon icon_fullscreen"></div>
                {$_('enter_message.press_and_hold_menu.view.text')}
            </button>
        {:else if type === 'pdf'}
            <button 
                class="menu-item download"
                on:click={(event) => handleMenuItemClick('download', event)}
            >
                <div class="clickable-icon icon_download"></div>
                {$_('enter_message.press_and_hold_menu.download.text')}
            </button>
            <button 
                class="menu-item view"
                on:click={(event) => handleMenuItemClick('view', event)}
            >
                <div class="clickable-icon icon_fullscreen"></div>
                {$_('enter_message.press_and_hold_menu.view.text')}
            </button>
        {:else}
            {#if !isYouTube && (type === 'default' || type === 'pdf')}
                <button 
                    class="menu-item download"
                    on:click={(event) => handleMenuItemClick('download', event)}
                >
                    <div class="clickable-icon icon_download"></div>
                    {$_('enter_message.press_and_hold_menu.download.text')}
                </button>
            {/if}
            <button 
                class="menu-item view"
                on:click={(event) => handleMenuItemClick('view', event)}
            >
                <div class="clickable-icon icon_fullscreen"></div>
                {$_('enter_message.press_and_hold_menu.view.text')}
            </button>
        {/if}
    </div>
{/if}

<style>
    .menu-container {
        position: absolute;
        left: var(--menu-x);
        top: var(--menu-y);
        transform: translate(-50%, -100%);
        background: var(--color-grey-blue);
        border-radius: 12px;
        padding: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 1000;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease-in-out;
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
    }

    .menu-item:hover {
        background-color: var(--color-grey-20);
    }

    .menu-item.delete {
        color: #E80000;
    }

    .menu-item.delete .clickable-icon {
        background: #E80000;
    }
</style>
