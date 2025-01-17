<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { _ } from 'svelte-i18n'; // Import translation function

    // Props
    export let x: number = 0;  // X position of menu
    export let y: number = 0;  // Y position of menu
    export let show: boolean = false;
    export let type: 'default' | 'pdf' | 'web' = 'default';  // Add type prop

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
        class="menu"
        role="menu"
        bind:this={menuElement}
        style="left: {x}px; top: {y}px;"
    >
        <button 
            class="menu-item delete"
            on:click={(event) => handleMenuItemClick('delete', event)}
        >
            <div class="clickable-icon icon_delete"></div>
            {$_('enter_message.press_and_hold_menu.delete.text')}
        </button>
        
        {#if type === 'web'}
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
                {$_('enter_message.press_and_hold_menu.open_link.text')}
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
        {/if}
    </div>
{/if}

<style>
    .menu {
        position: fixed;
        width: 180px;
        background: var(--color-grey-0);
        border-radius: 30px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        padding: 8px;
        z-index: 1000;
        display: flex;
        flex-direction: column;
        gap: 4px;
        transform: translate(-50%, -100%) translateY(-8px);
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

    .menu-item.copy {
        color: var(--color-font-primary);
    }

    .menu-item.copy .clickable-icon {
        background: var(--color-font-primary);
    }
</style>
