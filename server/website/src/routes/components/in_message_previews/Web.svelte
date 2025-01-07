<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import PressAndHoldMenu from './PressAndHoldMenu.svelte';
    
    // Props
    export let url: string;
    
    const dispatch = createEventDispatcher();
    
    // Menu state
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;
    
    // Get domain name for display
    const domain = new URL(url).hostname;
    
    // Handle mouse events
    function handleContextMenu(event: MouseEvent) {
        event.preventDefault();
        showMenu = true;
        menuX = event.clientX;
        menuY = event.clientY;
    }
    
    // Handle touch events for press & hold
    function handleTouchStart(event: TouchEvent) {
        const touch = event.touches[0];
        const pressTimer = setTimeout(() => {
            showMenu = true;
            menuX = touch.clientX;
            menuY = touch.clientY;
        }, 500);
        
        function cleanup() {
            clearTimeout(pressTimer);
            document.removeEventListener('touchend', cleanup);
            document.removeEventListener('touchmove', cleanup);
        }
        
        document.addEventListener('touchend', cleanup);
        document.addEventListener('touchmove', cleanup);
    }
    
    function handleClick(event: MouseEvent) {
        if (!showMenu) {
            window.open(url, '_blank');
        }
        showMenu = false;
    }
    
    function handleKeyDown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            window.open(url, '_blank');
        }
    }
    
    // Handle menu actions
    function handleCopy() {
        navigator.clipboard.writeText(url);
        showMenu = false;
    }
    
    function handleOpen() {
        window.open(url, '_blank');
        showMenu = false;
    }
</script>

<div 
    class="web-preview-container"
    role="button"
    tabindex="0"
    on:click={handleClick}
    on:keydown={handleKeyDown}
    on:contextmenu={handleContextMenu}
    on:touchstart={handleTouchStart}
>
    <!-- Web icon -->
    <div class="icon_rounded web"></div>
    
    <!-- URL -->
    <div class="url-container">
        <span class="url">{domain}</span>
    </div>
    
    <PressAndHoldMenu
        show={showMenu}
        x={menuX}
        y={menuY}
        on:close={() => showMenu = false}
        on:delete={handleCopy}
        on:download={handleOpen}
        on:view={handleOpen}
    />
</div>

<style>
    .web-preview-container {
        width: 300px;
        height: 60px;
        background-color: #F8F8F8;
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
        display: flex;
        align-items: center;
    }

    .web-preview-container:hover {
        background-color: #F0F0F0;
    }

    .url-container {
        position: absolute;
        left: 65px;
        right: 16px;
        min-height: 40px;
        padding: 5px 0;
        display: flex;
        align-items: center;
    }

    .url {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.3;
        font-size: 14px;
        color: #333;
        width: 100%;
        word-break: break-word;
        max-height: 2.6em;
    }
</style>
