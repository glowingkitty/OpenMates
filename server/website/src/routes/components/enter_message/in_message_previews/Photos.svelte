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
            // For blob URLs, check type only once
            if (url.protocol === 'blob:') {
                fetch(src)
                    .then(response => response.blob())
                    .then(blob => {
                        // Keep original type, don't force jpg
                        imageType = blob.type.startsWith('image/jpeg') ? 'jpg' : 'other';
                    })
                    .catch(error => {
                        console.error('Error determining image type:', error);
                    });
            } else {
                // For regular URLs, check extension
                const extension = url.pathname.split('.').pop()?.toLowerCase() || '';
                imageType = ['jpg', 'jpeg'].includes(extension) ? 'jpg' : 'other';
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
    function handleDelete(event: Event) {
        event.stopPropagation();  // Prevent click from bubbling up
        dispatch('delete');
        showMenu = false;
    }
    
    function handleDownload(event: Event) {
        event.stopPropagation();  // Prevent click from bubbling up
        const link = document.createElement('a');
        link.href = src;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showMenu = false;
    }
    
    function handleView(event: Event) {
        event.stopPropagation();  // Prevent click from bubbling up
        window.open(src, '_blank');
        showMenu = false;
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

    function handleKeyDown(event: KeyboardEvent) {
        // Trigger menu on Enter or Space
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            showMenu = true;
            // Position menu in the center of the container
            const element = event.currentTarget as HTMLElement;
            const rect = element.getBoundingClientRect();
            menuX = rect.left + rect.width / 2;
            menuY = rect.top + rect.height / 2;
        }
    }
</script>

<div 
    class="photo-preview-container"
    role="button"
    tabindex="0"
    on:click={handleClick}
    on:keydown={handleKeyDown}
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
        cursor: pointer;
    }

    .checkerboard-background {
        width: 100%;
        height: 100%;
        background-image: linear-gradient(45deg, var(--color-grey-20) 25%, transparent 25%),
                          linear-gradient(-45deg, var(--color-grey-20) 25%, transparent 25%),
                          linear-gradient(45deg, transparent 75%, var(--color-grey-20) 75%),
                          linear-gradient(-45deg, transparent 75%, var(--color-grey-20) 75%);
        background-size: 20px 20px;
        background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
        background-color: var(--color-grey-0);
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
</style>
