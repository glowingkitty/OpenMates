<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import PressAndHoldMenu from './PressAndHoldMenu.svelte';
    
    // Props
    export let src: string;
    export let filename: string;
    
    const dispatch = createEventDispatcher();
    
    // Menu state
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;
    
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
    
    // Handle menu actions
    function handleDelete() {
        dispatch('delete');
        showMenu = false;
    }
    
    function handleDownload() {
        const link = document.createElement('a');
        link.href = src;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showMenu = false;
    }
    
    function handleView() {
        window.open(src, '_blank');
        showMenu = false;
    }
    
    function handleClick(event: MouseEvent) {
        showMenu = true;
        menuX = event.clientX;
        menuY = event.clientY;
    }
    
    function handleKeyDown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            showMenu = true;
            const element = event.currentTarget as HTMLElement;
            const rect = element.getBoundingClientRect();
            menuX = rect.left + rect.width / 2;
            menuY = rect.top + rect.height / 2;
        }
    }
</script>

<div 
    class="pdf-preview-container"
    role="button"
    tabindex="0"
    on:click={handleClick}
    on:keydown={handleKeyDown}
    on:contextmenu={handleContextMenu}
    on:touchstart={handleTouchStart}
>
    <!-- PDF icon -->
    <div class="icon_rounded pdf"></div>
    
    <!-- Filename -->
    <div class="filename-container">
        <span class="filename">{filename}</span>
    </div>
    
    <PressAndHoldMenu
        show={showMenu}
        x={menuX}
        y={menuY}
        on:close={() => showMenu = false}
        on:delete={handleDelete}
        on:download={handleDownload}
        on:view={handleView}
    />
</div>

<style>
    .pdf-preview-container {
        width: 300px;
        height: 60px;
        background-color: #F8F8F8;
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
    }

    .pdf-preview-container:hover {
        background-color: #F0F0F0;
    }

    .filename-container {
        position: absolute;
        left: 65px;
        top: 50%;
        transform: translateY(-50%);
        right: 16px;
        overflow: hidden;
    }

    .filename {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.2;
        font-size: 14px;
        color: #333;
    }
</style>
