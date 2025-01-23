<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount } from 'svelte';
    import 'leaflet/dist/leaflet.css';

    export let src: string;
    export let filename: string;
    export let id: string;

    let mapContainer: HTMLDivElement;
    let address: string = '';
    let coordinates: { lat: number; lon: number } | null = null;
    let L: any;

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

            // Initialize map first to show something immediately
            L = (await import('leaflet')).default;
            
            const map = L.map(mapContainer, {
                center: [coordinates.lat, coordinates.lon],
                zoom: parseInt(zoom),
                zoomControl: false,
                dragging: false,
                touchZoom: false,
                scrollWheelZoom: false,
                doubleClickZoom: false
            });

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);

            // Add marker
            L.marker([coordinates.lat, coordinates.lon]).addTo(map);

            try {
                // Get address using reverse geocoding with proper headers
                const response = await fetch(
                    `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
                    {
                        headers: {
                            'User-Agent': 'OpenMates/1.0', // Replace with your app name
                            'Accept-Language': 'en' // Request English results
                        }
                    }
                );
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                
                // Format address from response
                if (data.address) {
                    // Create two lines for the address
                    const line1Parts = [];
                    const line2Parts = [];
                    
                    // First line: Try street name and number, fallback to city or country
                    if (data.address.road) {
                        line1Parts.push(data.address.road);
                        if (data.address.house_number) line1Parts.push(data.address.house_number);
                    } else if (data.address.city) {
                        line1Parts.push(data.address.city);
                    } else if (data.address.country) {
                        line1Parts.push(data.address.country);
                        // If only country is available, show coordinates in second line
                        if (!data.address.city && !data.address.road) {
                            line2Parts.push(`${coordinates.lat.toFixed(6)}, ${coordinates.lon.toFixed(6)}`);
                        }
                    } else {
                        // Last resort: use coordinates
                        line1Parts.push(`${coordinates.lat.toFixed(6)}, ${coordinates.lon.toFixed(6)}`);
                    }
                    
                    // Second line: ZIP code and city (only if city wasn't used in first line)
                    if (line2Parts.length === 0 && line1Parts[0] !== data.address.city) {
                        if (data.address.postcode) line2Parts.push(data.address.postcode);
                        if (data.address.city) line2Parts.push(data.address.city);
                    }
                    
                    // If second line would be empty but we have a country, show it there
                    if (line2Parts.length === 0 && data.address.country && line1Parts[0] !== data.address.country) {
                        line2Parts.push(data.address.country);
                    }
                    
                    // Combine into two separate strings
                    const line1 = line1Parts.join(' ');
                    const line2 = line2Parts.join(' ');
                    
                    // Store both lines in address (using newline character)
                    address = line2 ? `${line1}\n${line2}` : line1;
                } else {
                    // If no address data at all, use coordinates
                    address = `${coordinates.lat.toFixed(6)}, ${coordinates.lon.toFixed(6)}`;
                }

            } catch (geocodeError) {
                logger.debug('Error getting address:', geocodeError);
                // Fallback to showing just coordinates if geocoding fails
                address = `${coordinates.lat.toFixed(6)}, ${coordinates.lon.toFixed(6)}`;
            }

            logger.debug('Map preview loaded:', { coordinates, address });
        } catch (error) {
            logger.debug('Error loading map preview:', error);
            address = 'Error loading location';
        }
    });
</script>

<InlinePreviewBase {id} type="maps" {src} {filename} height="200px">
    <div class="preview-container">
        <div class="map-preview" bind:this={mapContainer}></div>
        <div class="info-bar">
            <div class="icon_rounded maps"></div>
            <div class="text-container">
                <span class="address">{address}</span>
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
        z-index: 1000;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
        line-height: 1.3;
        overflow: hidden;
        padding: 4px 0;
    }

    .address {
        font-size: 16px;
        color: var(--color-font-primary);
        white-space: pre-line;
        overflow: hidden;
        text-overflow: ellipsis;
        max-height: 100%;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    /* Add these styles for the Leaflet map */
    :global(.leaflet-container) {
        width: 100%;
        height: 100%;
        background: var(--color-grey-0);
    }

    :global(.leaflet-control-attribution) {
        font-size: 8px;
    }
</style>
