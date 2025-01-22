<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import type { Map, Marker } from 'leaflet';
    
    // Add import for Leaflet CSS in the script section
    import 'leaflet/dist/leaflet.css';
    
    const dispatch = createEventDispatcher();
    
    let mapContainer: HTMLElement;
    let map: Map | null = null;
    let marker: Marker | null = null;
    let L: any; // Will hold Leaflet instance
    let isPrecise = false; // Toggle for precise location
    let isLoading = false;
    let currentLocation: { lat: number; lon: number } | null = null;

    // Add logger for debugging
    const logger = {
        debug: (...args: any[]) => console.debug('[MapsView]', ...args),
        info: (...args: any[]) => console.info('[MapsView]', ...args)
    };

    onMount(async () => {
        await initializeMap();
    });

    onDestroy(() => {
        cleanupMap();
    });

    async function initializeMap() {
        // Clean up existing map if any
        cleanupMap();
        
        // Import Leaflet only on client-side
        L = (await import('leaflet')).default;
        
        map = L.map(mapContainer, {
            center: [20, 0],
            zoom: 2,
            zoomControl: true,
            attributionControl: false,
            maxBoundsViscosity: 1.0
        });

        // Add OpenStreetMap tile layer with error handling and retries
        const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            subdomains: ['a', 'b', 'c'],
            crossOrigin: true
        }).addTo(map);

        // Force map to update its container size
        setTimeout(() => {
            if (map) {
                map.invalidateSize();
                
                // If we have a current location, center on it
                if (currentLocation) {
                    map.setView([currentLocation.lat, currentLocation.lon], 16, {
                        animate: false
                    });
                    marker = L.marker([currentLocation.lat, currentLocation.lon]).addTo(map);
                }
            }
        }, 100);

        logger.debug('Map initialized');
    }

    function cleanupMap() {
        if (marker) {
            marker.remove();
            marker = null;
        }
        if (map) {
            map.remove();
            map = null;
        }
    }

    async function getCurrentLocation() {
        if (!navigator.geolocation) {
            logger.info('Geolocation not supported');
            return;
        }

        isLoading = true;

        try {
            const position = await new Promise<GeolocationPosition>((resolve, reject) => {
                navigator.geolocation.getCurrentPosition(
                    resolve,
                    reject,
                    {
                        enableHighAccuracy: isPrecise,
                        timeout: 10000,
                        maximumAge: 0
                    }
                );
            });

            const { latitude: lat, longitude: lon } = position.coords;
            currentLocation = { lat, lon };

            logger.debug('Got location:', { lat, lon, precise: isPrecise });

            // Update map view
            if (map) {
                map.setView([lat, lon], 16);

                // Add or update marker
                if (marker) {
                    marker.setLatLng([lat, lon]);
                } else {
                    marker = L.marker([lat, lon]).addTo(map);
                }
            }

            // Enable the select button
            isLoading = false;

        } catch (error) {
            logger.debug('Error getting location:', error);
            isLoading = false;
        }
    }

    function handleClose() {
        dispatch('close');
    }

    function handleSelect() {
        if (currentLocation) {
            dispatch('locationselected', currentLocation);
            dispatch('close');
        }
    }

    function togglePrecise() {
        isPrecise = !isPrecise;
        if (currentLocation) {
            getCurrentLocation(); // Refresh location with new accuracy setting
        }
    }
</script>

<svelte:head>
    <!-- Ensure Leaflet CSS is properly loaded -->
    <link 
        rel="stylesheet" 
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
        crossorigin=""
    />
</svelte:head>

<div class="maps-overlay" transition:slide={{ duration: 300, axis: 'y' }}>
    <div class="map-container" bind:this={mapContainer}></div>
    
    <div class="precise-toggle">
        <span>{$_('enter_message.location.precise.text')}</span>
        <button 
            class="toggle-button {isPrecise ? 'active' : ''}"
            on:click={togglePrecise}
            aria-label={$_('enter_message.location.toggle_precise.text')}
        >
            <div class="toggle-slider"></div>
        </button>
    </div>

    <div class="bottom-bar">
        <div class="controls">
            <button 
                class="clickable-icon icon_close" 
                on:click={handleClose}
                aria-label={$_('enter_message.location.close.text')}
            ></button>

            {#if currentLocation}
                <button 
                    class="select-button" 
                    on:click={handleSelect}
                    transition:slide={{ duration: 200 }}
                >
                    {$_('enter_message.location.select.text')}
                </button>
            {/if}

            <button 
                class="location-button {isLoading ? 'loading' : ''}"
                on:click={getCurrentLocation}
                disabled={isLoading}
                aria-label={$_('enter_message.location.get_location.text')}
            >
                <div class="clickable-icon icon_maps"></div>
            </button>
        </div>
    </div>
</div>

<style>
    .maps-overlay {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 400px;
        background: #fff;
        z-index: 1000;
        display: flex;
        flex-direction: column;
        border-radius: 24px;
        overflow: hidden;
    }

    .map-container {
        width: 100%;
        height: 100%;
        background: #f5f5f5;
        z-index: 1;
    }

    .bottom-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 53px;
        background: var(--color-grey-blue);
        border-radius: 24px;
        z-index: 2;
    }

    .controls {
        height: 100%;
        padding: 0 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .clickable-icon {
        width: 25px;
        height: 25px;
        color: var(--color-font-primary);
    }

    .location-button {
        background: none;
        border: none;
        padding: 8px;
        cursor: pointer;
        border-radius: 50%;
        transition: all 0.3s ease;
    }

    .location-button:hover {
        background: var(--color-grey-20);
    }

    .location-button.loading {
        animation: spin 1s linear infinite;
        pointer-events: none;
        opacity: 0.7;
    }

    .select-button {
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        background: var(--color-primary);
        color: white;
        border: none;
        padding: 8px 24px;
        border-radius: 20px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .select-button:hover {
        background: var(--color-primary-dark);
    }

    .precise-toggle {
        position: absolute;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        background: white;
        padding: 8px 16px;
        border-radius: 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        z-index: 2;
    }

    .toggle-button {
        width: 44px;
        height: 24px;
        background: var(--color-grey-20);
        border-radius: 12px;
        border: none;
        position: relative;
        cursor: pointer;
        transition: background-color 0.3s ease;
    }

    .toggle-button.active {
        background: var(--color-primary);
    }

    .toggle-slider {
        position: absolute;
        top: 2px;
        left: 2px;
        width: 20px;
        height: 20px;
        background: white;
        border-radius: 50%;
        transition: transform 0.3s ease;
    }

    .toggle-button.active .toggle-slider {
        transform: translateX(20px);
    }

    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

    /* Add Leaflet styles */
    :global(.leaflet-container) {
        width: 100%;
        height: 100%;
    }

    :global(.leaflet-control-attribution) {
        font-size: 10px;
        background: rgba(255, 255, 255, 0.8) !important;
        margin-bottom: 53px !important; /* Account for bottom bar */
    }

    /* Add specific styles for Leaflet tile loading */
    :global(.leaflet-tile-container) {
        opacity: 1 !important;
    }

    :global(.leaflet-tile-loaded) {
        opacity: 1 !important;
        visibility: visible !important;
    }

    :global(.leaflet-tile-loading) {
        opacity: 0.5;
    }
</style> 