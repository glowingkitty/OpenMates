<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import PressAndHoldMenu from './PressAndHoldMenu.svelte';
    import { onMount, onDestroy } from 'svelte';
    
    // Props to receive the image URL/blob and type
    export let src: string;
    export let filename: string = 'image'; // Default filename for camera photos
    
    const dispatch: {
        (e: 'delete'): void;
        (e: 'download'): void;
        (e: 'view'): void;
    } = createEventDispatcher();
    let pressTimer: ReturnType<typeof setTimeout>;
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;
    
    // Function to determine image type from src
    let imageType: 'jpg' | 'other' = 'other';
    let isTypeChecked = false;
    
    // Watch for src changes and determine image type only once per src
    $: if (src && !isTypeChecked) {
        isTypeChecked = true;

        try {
            const url = new URL(src);
            const extension = url.pathname.split('.').pop()?.toLowerCase() || '';

            // Set image type based on extension
            if (['jpg', 'jpeg'].includes(extension)) {
                imageType = 'jpg';
            } else if (url.protocol === 'blob:') {
                // For blob URLs, check type only once
                fetch(src)
                    .then(response => response.blob())
                    .then(blob => {
                        imageType = blob.type.includes('jpeg') ? 'jpg' : 'other';
                    })
                    .catch(error => {
                        console.error('Error determining image type:', error);
                    });
            }
        } catch (error) {
            console.error('Error parsing URL:', error);
        }
    }
    
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
        pressTimer = setTimeout(() => {
            showMenu = true;
            menuX = touch.clientX;
            menuY = touch.clientY;
        }, 500);
    }
    
    function handleTouchEnd() {
        clearTimeout(pressTimer);
    }
    
    // Handle menu actions
    function handleDelete() {
        dispatch('delete');
    }
    
    function handleDownload() {
        const link = document.createElement('a');
        link.href = src;
        link.download = filename; // Use the provided filename
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
    
    function handleView() {
        window.open(src, '_blank');
    }
    
    // Update to show menu on regular click as well
    function handleClick(event: MouseEvent) {
        showMenu = true;
        menuX = event.clientX;
        menuY = event.clientY;
    }
    
    // Add scroll handler to close menu
    function handleScroll() {
        showMenu = false;
    }

    // Add scroll listener on mount and remove on destroy
    onMount(() => {
        document.addEventListener('scroll', handleScroll, true);
    });
    
    onDestroy(() => {
        document.removeEventListener('scroll', handleScroll, true);
    });
</script>

<div 
    class="photo-preview-container"
    role="button"
    tabindex="0"
    on:click={handleClick}
    on:contextmenu={handleContextMenu}
    on:touchstart={handleTouchStart}
    on:touchend={handleTouchEnd}
    on:touchmove={handleTouchEnd}
>
    <!-- Checkerboard background container -->
    <div class="checkerboard-background">
        <!-- Actual image with dynamic class based on type -->
        <img
            {src}
            alt="Preview"
            class="preview-image"
            class:fill-container={imageType === 'jpg'}
            class:fit-center={imageType === 'other'}
        />
    </div>
    <!-- Photos icon -->
    <div class="icon_rounded photos"></div>
    
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
    .photo-preview-container {
        width: 300px;
        height: 200px;
        border-radius: 30px;
        position: relative;
        overflow: hidden;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    }

    .checkerboard-background {
        width: 100%;
        height: 100%;
        background-image: linear-gradient(45deg, #f0f0f0 25%, transparent 25%),
                          linear-gradient(-45deg, #f0f0f0 25%, transparent 25%),
                          linear-gradient(45deg, transparent 75%, #f0f0f0 75%),
                          linear-gradient(-45deg, transparent 75%, #f0f0f0 75%);
        background-size: 20px 20px;
        background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
        background-color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .preview-image {
        display: block;
    }

    /* Style for JPG images - fill the container */
    .fill-container {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    /* Style for PNG/SVG images - fit in center */
    .fit-center {
        max-width: 100%;
        max-height: 100%;
        object-fit: contain;
    }

    .icon_rounded {
        position: absolute;
        bottom: 0px;
        left: 0px;
        z-index: 2;
    }
</style>
