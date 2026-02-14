<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { _ } from 'svelte-i18n'; // Import translation function

    // Props using Svelte 5 $props()
    interface Props {
        x?: number;
        y?: number;
        show?: boolean;
        type?: 'default' | 'pdf' | 'web' | 'video-transcript' | 'video';
        isYouTube?: boolean;
        originalUrl?: string | undefined;
        hideDelete?: boolean;
    }
    let { 
        x = 0,
        y = 0,
        show = false,
        type = 'default',
        isYouTube = false,
        originalUrl = undefined,
        hideDelete = false
    }: Props = $props();

    const dispatch: {
        (e: 'close' | 'delete' | 'download' | 'view' | 'copy' | 'share'): void;
    } = createEventDispatcher();
    let menuElement = $state<HTMLDivElement>();

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

    function handleView(event: MouseEvent) {
        event.stopPropagation();
        if (originalUrl) {
            window.open(originalUrl, '_blank');
        }
        dispatch('view');
        dispatch('close');
    }
</script>

{#if show}
    <div 
        class="menu-container {show ? 'show' : ''}"
        style="--menu-x: {x}px; --menu-y: {y}px;"
        bind:this={menuElement}
    >
        {#if !hideDelete}
            <button 
                class="menu-item delete"
                onclick={(event) => handleMenuItemClick('delete', event)}
            >
                <div class="clickable-icon icon_delete"></div>
                {$_('enter_message.press_and_hold_menu.delete')}
            </button>
        {/if}
        
        {#if type === 'video-transcript'}
            <!-- Video Transcript Embed: Share, Copy, Download -->
            <button 
                class="menu-item share"
                onclick={(event) => handleMenuItemClick('share', event)}
            >
                <div class="clickable-icon icon_share"></div>
                {$_('enter_message.press_and_hold_menu.share', { default: 'Share' })}
            </button>
            <button 
                class="menu-item copy"
                onclick={(event) => handleMenuItemClick('copy', event)}
            >
                <div class="clickable-icon icon_copy"></div>
                {$_('enter_message.press_and_hold_menu.copy', { default: 'Copy' })}
            </button>
            <button 
                class="menu-item download"
                onclick={(event) => handleMenuItemClick('download', event)}
            >
                <div class="clickable-icon icon_download"></div>
                {$_('enter_message.press_and_hold_menu.download')}
            </button>
        {:else if type === 'video'}
            <!-- Video Embed: Share, Copy -->
            <button 
                class="menu-item share"
                onclick={(event) => handleMenuItemClick('share', event)}
            >
                <div class="clickable-icon icon_share"></div>
                {$_('enter_message.press_and_hold_menu.share', { default: 'Share' })}
            </button>
            <button 
                class="menu-item copy"
                onclick={(event) => handleMenuItemClick('copy', event)}
            >
                <div class="clickable-icon icon_copy"></div>
                {$_('enter_message.press_and_hold_menu.copy_link')}
            </button>
        {:else if type === 'web' || isYouTube}
            <button 
                class="menu-item copy"
                onclick={(event) => handleMenuItemClick('copy', event)}
            >
                <div class="clickable-icon icon_copy"></div>
                {$_('enter_message.press_and_hold_menu.copy_link')}
            </button>
            <button 
                class="menu-item view"
                onclick={(event) => handleView(event)}
            >
                <div class="clickable-icon icon_fullscreen"></div>
                {$_('enter_message.press_and_hold_menu.view')}
            </button>
        {:else if type === 'pdf'}
            <button 
                class="menu-item download"
                onclick={(event) => handleMenuItemClick('download', event)}
            >
                <div class="clickable-icon icon_download"></div>
                {$_('enter_message.press_and_hold_menu.download')}
            </button>
            <button 
                class="menu-item view"
                onclick={(event) => handleView(event)}
            >
                <div class="clickable-icon icon_fullscreen"></div>
                {$_('enter_message.press_and_hold_menu.view')}
            </button>
        {:else}
            {#if !isYouTube && (type === 'default' || type === 'pdf')}
                <button 
                    class="menu-item download"
                    onclick={(event) => handleMenuItemClick('download', event)}
                >
                    <div class="clickable-icon icon_download"></div>
                    {$_('enter_message.press_and_hold_menu.download')}
                </button>
            {/if}
            <button 
                class="menu-item view"
                onclick={(event) => handleView(event)}
            >
                <div class="clickable-icon icon_fullscreen"></div>
                {$_('enter_message.press_and_hold_menu.view')}
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
