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
    
    // Enhanced URL parsing
    const urlObj = new URL(url);
    const parts = {
        subdomain: '',
        domain: '',
        path: ''
    };

    // Split hostname into parts
    const hostParts = urlObj.hostname.split('.');
    if (hostParts.length > 2) {
        parts.subdomain = hostParts[0] + '.';
        parts.domain = hostParts.slice(1).join('.');
    } else {
        parts.domain = urlObj.hostname;
    }

    // Get path and query parameters
    // Only set path if it's more than just a forward slash
    const fullPath = urlObj.pathname + urlObj.search + urlObj.hash;
    parts.path = fullPath === '/' ? '' : fullPath;
    
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
        <div class="url">
            <div class="domain-line">
                <span class="subdomain">{parts.subdomain}</span>
                <span class="main-domain">{parts.domain}</span>
            </div>
            {#if parts.path}
                <span class="path">{parts.path}</span>
            {/if}
        </div>
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
        display: flex;
        flex-direction: column;
        line-height: 1.3;
        font-size: 14px;
        width: 100%;
        word-break: break-word;
        max-height: 2.6em;
        overflow: hidden;
    }

    .domain-line {
        display: flex;
        flex-direction: row;
        align-items: baseline;
    }

    .subdomain {
        color: #7C7C7C;
    }

    .main-domain {
        color: #333;
    }

    .path {
        color: #7C7C7C;
        display: block;
        text-overflow: ellipsis;
        overflow: hidden;
        white-space: nowrap;
    }
</style>
