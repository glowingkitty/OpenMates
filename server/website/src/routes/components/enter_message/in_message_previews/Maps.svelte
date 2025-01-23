<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount } from 'svelte';

    export let src: string;
    export let filename: string;
    export let id: string;

    let mapPreview: string = '';
    let address: string = '';
    let coordinates: { lat: number; lon: number } | null = null;

    // Logger for debugging
    const logger = {
        debug: (...args: any[]) => console.log('[MapsPreview]', ...args),
        info: (...args: any[]) => console.info('[MapsPreview]', ...args)
    };

    onMount(async () => {
        try {
            // Parse coordinates from OpenStreetMap URL
            const url = new URL(src);
            const lat = url.searchParams.get('mlat');
            const lon = url.searchParams.get('mlon');
            const zoom = url.searchParams.get('zoom') || '16';

            if (!lat || !lon) {
                throw new Error('Invalid map URL');
            }

            coordinates = { lat: parseFloat(lat), lon: parseFloat(lon) };

            // Generate static map URL using OpenStreetMap
            const width = 600;
            const height = 300;
            const scale = window.devicePixelRatio || 1;
            
            // Create static map URL using OpenStreetMap tiles
            mapPreview = `https://staticmap.openstreetmap.de/staticmap.php?center=${lat},${lon}&zoom=${zoom}&size=${width}x${height}&markers=${lat},${lon},green-marker&scale=${scale}`;

            // Get address using reverse geocoding
            const response = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`);
            const data = await response.json();
            
            // Format address from response
            if (data.address) {
                const parts = [];
                if (data.address.road) parts.push(data.address.road);
                if (data.address.house_number) parts.push(data.address.house_number);
                if (data.address.postcode) parts.push(data.address.postcode);
                if (data.address.city) parts.push(data.address.city);
                address = parts.join(' ');
            }

            logger.debug('Map preview loaded:', { coordinates, address });
        } catch (error) {
            logger.debug('Error loading map preview:', error);
            mapPreview = '';
            address = 'Error loading location';
        }
    });
</script>

<InlinePreviewBase {id} type="maps" {src} {filename} height="200px">
    <div class="preview-container">
        {#if mapPreview}
            <div class="map-preview">
                <img 
                    src={mapPreview} 
                    alt="Location map"
                    class="map-image"
                />
            </div>
        {:else}
            <div class="loading-container">
                <div class="loading-spinner"></div>
            </div>
        {/if}
        <div class="info-bar">
            <div class="text-container">
                <span class="address">{address}</span>
                {#if coordinates}
                    <span class="coordinates">
                        {coordinates.lat.toFixed(6)}, {coordinates.lon.toFixed(6)}
                    </span>
                {/if}
            </div>
        </div>
    </div>
</InlinePreviewBase>

<style>
    .preview-container {
        position: relative;
        width: 100%;
        height: 100%;
        background-color: var(--color-grey-0);
        border-radius: 8px;
        overflow: hidden;
    }

    .map-preview {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        overflow: hidden;
    }

    .map-image {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .loading-container {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background-color: var(--color-grey-0);
    }

    .loading-spinner {
        width: 32px;
        height: 32px;
        border: 3px solid var(--color-grey-20);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    .info-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        border-radius: 30px;
        height: 60px;
        background-color: var(--color-grey-20);
        display: flex;
        align-items: center;
        padding-left: 70px;
        padding-right: 16px;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
        line-height: 1.3;
        overflow: hidden;
    }

    .address {
        font-size: 16px;
        color: var(--color-font-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .coordinates {
        font-size: 14px;
        color: var(--color-font-secondary);
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }
</style>
