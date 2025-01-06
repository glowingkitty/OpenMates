<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';

    // Props
    export let x: number = 0;  // X position of menu
    export let y: number = 0;  // Y position of menu
    export let show: boolean = false;

    const dispatch: {
        (e: 'close' | 'delete' | 'download' | 'view'): void;
    } = createEventDispatcher();
    let menuElement: HTMLDivElement;

    // Handle clicking outside the menu
    function handleClickOutside(event: MouseEvent | TouchEvent) {
        if (menuElement && !menuElement.contains(event.target as Node)) {
            dispatch('close');
        }
    }

    // Handle menu item clicks
    function handleMenuItemClick(action: Parameters<typeof dispatch>[0]) {
        dispatch(action);
        dispatch('close');
    }

    // Add and remove event listeners
    onMount(() => {
        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('touchstart', handleClickOutside);

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('touchstart', handleClickOutside);
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
            on:click={() => handleMenuItemClick('delete')}
        >
            <div class="icon delete"></div>
            Delete
        </button>
        <button 
            class="menu-item download"
            on:click={() => handleMenuItemClick('download')}
        >
            <div class="icon download"></div>
            Download
        </button>
        <button 
            class="menu-item view"
            on:click={() => handleMenuItemClick('view')}
        >
            <div class="icon view"></div>
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
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        border: none;
        background: none;
        width: 100%;
        border-radius: 22px;
        cursor: pointer;
        font-size: 14px;
        color: #333;
        transition: background-color 0.2s;
    }

    .menu-item:hover {
        background-color: #f5f5f5;
    }

    .menu-item.delete {
        color: #ff3b30;
    }

    .icon {
        width: 20px;
        height: 20px;
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
    }

    .icon.delete {
        background-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%23ff3b30"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>');
    }

    .icon.download {
        background-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%23333"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>');
    }

    .icon.view {
        background-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%23333"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>');
    }
</style>
