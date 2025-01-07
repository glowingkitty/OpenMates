<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';

    // Props
    export let x: number = 0;  // X position of menu
    export let y: number = 0;  // Y position of menu
    export let show: boolean = false;
    export let type: 'web' | 'default' = 'default';  // Add type prop

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
        event.stopPropagation();  // Stop event from bubbling
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
            Delete
        </button>
        
        {#if type === 'web'}
            <button 
                class="menu-item copy"
                on:click={(event) => handleMenuItemClick('copy', event)}
            >
                <div class="clickable-icon icon_copy"></div>
                Copy link
            </button>
        {:else}
            <button 
                class="menu-item download"
                on:click={(event) => handleMenuItemClick('download', event)}
            >
                <div class="clickable-icon icon_download"></div>
                Download
            </button>
        {/if}

        <button 
            class="menu-item view"
            on:click={(event) => handleMenuItemClick('view', event)}
        >
            <div class="clickable-icon icon_fullscreen"></div>
            View
        </button>
    </div>
{/if}

<style>
    .menu {
        position: fixed;
        width: 180px;
        background: white;
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
        background-color: #f5f5f5;
    }

    .menu-item.delete {
        color: #E80000;
    }

    .menu-item.delete .clickable-icon {
        background: #E80000;
    }
</style>
