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
    
    // Add state for showing copied message
    let showCopiedMessage = false;
    let urlVisible = true;  // New state to control URL visibility
    
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
    
    // Handle click to show menu instead of opening URL
    function handleClick(event: MouseEvent) {
        // Show menu instead of opening URL
        showMenu = true;
        menuX = event.clientX;
        menuY = event.clientY;
    }
    
    function handleKeyDown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            window.open(url, '_blank');
        }
    }
    
    // Handle copy action with improved animation
    async function handleCopy() {
        await navigator.clipboard.writeText(url);
        
        // Hide URL first
        urlVisible = false;
        
        // Show copied message after URL is hidden
        setTimeout(() => {
            showCopiedMessage = true;
            
            // Hide copied message and show URL again after 1500ms
            setTimeout(() => {
                showCopiedMessage = false;
                setTimeout(() => {
                    urlVisible = true;
                }, 300); // Wait for fade out animation to complete
            }, 1500);
        }, 300); // Wait for fade out animation to complete
        
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
        <div class="url" class:fade-out={!urlVisible} class:hidden={!urlVisible}>
            <div class="domain-line">
                <span class="subdomain">{parts.subdomain}</span>
                <span class="main-domain">{parts.domain}</span>
            </div>
            {#if parts.path}
                <span class="path">{parts.path}</span>
            {/if}
        </div>
        {#if showCopiedMessage}
            <div class="copied-message fade-in">
                Copied to clipboard
            </div>
        {/if}
    </div>
    
    <PressAndHoldMenu
        show={showMenu}
        x={menuX}
        y={menuY}
        on:close={() => showMenu = false}
        on:delete={() => dispatch('delete')}
        on:copy={handleCopy}
        on:view={handleOpen}
        type="web"
    />
</div>

<style>
    .web-preview-container {
        width: 300px;
        height: 60px;
        background-color: var(--color-grey-20);
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
        display: flex;
        align-items: center;
    }

    .web-preview-container:hover {
        background-color: var(--color-grey-30);
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
        color: var(--color-font-tertiary);
    }

    .main-domain {
        color: var(--color-font-primary);
    }

    .path {
        color: var(--color-font-tertiary);
        display: block;
        text-overflow: ellipsis;
        overflow: hidden;
        white-space: nowrap;
    }

    .copied-message {
        position: absolute;
        top: 50%;
        transform: translateY(-50%);
        width: 100%;
        text-align: center;
        color: var(--color-font-primary);
        font-weight: 500;
    }

    .hidden {
        display: none;
    }

    .fade-in {
        animation: fadeIn 0.3s ease-in;
    }

    .fade-out {
        animation: fadeOut 0.3s ease-in;
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; }
    }
</style>
