<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import PressAndHoldMenu from './PressAndHoldMenu.svelte';

    // Props
    export let url: string;

    const dispatch = createEventDispatcher();

    // Menu state
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;

    // Preview state
    let title = '';
    let description = '';
    let image = '';
    let siteName = '';
    let loading = true;
    let error = false;

    // Parse HTML string to extract metadata
    function extractMetadata(html: string) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');

        // Helper function to get meta content
        const getMeta = (property: string) => {
            const element = doc.querySelector(`meta[property="${property}"], meta[name="${property}"]`);
            return element?.getAttribute('content') || '';
        };

        try {
            // Extract metadata with fallbacks
            title = getMeta('og:title') || doc.title || new URL(url).hostname;
            description = getMeta('og:description') || getMeta('description') || '';
            image = getMeta('og:image') || '';
            siteName = getMeta('og:site_name') || new URL(url).hostname;

            // logger.debug('Extracted metadata:', { title, description, image, siteName });
        } catch (err) {
            // logger.error('Error parsing metadata:', err);
            error = true;
        }
    }

    onMount(async () => {
        try {
            // logger.debug('Fetching webpage content for:', url);
            // Use allorigins.win as a CORS proxy
            const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(url)}`;
            const response = await fetch(proxyUrl);
            
            if (!response.ok) {
                throw new Error('Failed to fetch webpage content');
            }

            const data = await response.json();
            extractMetadata(data.contents);
        } catch (err) {
            // logger.error('Error fetching webpage:', err);
            error = true;
        } finally {
            loading = false;
        }
    });

    // Handle mouse events
    function handleContextMenu(event: MouseEvent) {
        event.preventDefault();
        showMenu = true;
        menuX = event.clientX;
        menuY = event.clientY;
    }

    function handleClick(event: MouseEvent) {
        if (!showMenu) {
            window.open(url, '_blank');
        }
        showMenu = false;
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
    {#if loading}
        <div class="loading-state">
            <div class="spinner"></div>
        </div>
    {:else if error}
        <div class="error-state">
            <div class="icon_rounded web"></div>
            <div class="url-text">{url}</div>
        </div>
    {:else}
        <div class="content">
            {#if image}
                <div class="image-container">
                    <img src={image} alt="" class="preview-image" />
                </div>
            {/if}
            <div class="text-content">
                <div class="site-name">{siteName}</div>
                <div class="title">{title}</div>
                {#if description}
                    <div class="description">{description}</div>
                {/if}
            </div>
        </div>
    {/if}

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
        background-color: #F8F8F8;
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
        overflow: hidden;
    }

    .web-preview-container:hover {
        background-color: #F0F0F0;
    }

    .loading-state, .error-state {
        height: 60px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 16px;
    }

    .spinner {
        width: 24px;
        height: 24px;
        border: 3px solid #f3f3f3;
        border-top: 3px solid #3498db;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    .content {
        display: flex;
        flex-direction: column;
    }

    .image-container {
        width: 100%;
        height: 150px;
        overflow: hidden;
    }

    .preview-image {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .text-content {
        padding: 12px 16px;
    }

    .site-name {
        font-size: 12px;
        color: #666;
        margin-bottom: 4px;
    }

    .title {
        font-size: 14px;
        font-weight: 600;
        color: #333;
        margin-bottom: 4px;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }

    .description {
        font-size: 12px;
        color: #666;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }

    .url-text {
        font-size: 14px;
        color: #666;
        margin-left: 12px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .error-state {
        display: flex;
        align-items: center;
    }
</style>
