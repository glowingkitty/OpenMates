<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import type { Map, Marker } from 'leaflet';
    import Toggle from '../Toggle.svelte';  // Add Toggle import
    
    const dispatch = createEventDispatcher();
    
    let mapContainer: HTMLElement;
    let map: Map | null = null;
    let marker: Marker | null = null;
    let L: any; // Will hold Leaflet instance
    let isPrecise = false; // Toggle for precise location
    let isLoading = false;
    let currentLocation: { lat: number; lon: number } | null = null;

    // Add dark mode detection
    let isDarkMode = false;
    let mapStyle: 'light' | 'dark' = 'light';
    
    // Function to check if dark mode is active
    function checkDarkMode() {
        // Check if system is in dark mode
        const systemDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
        // Get website dark mode setting - assuming it's stored in CSS variable
        const websiteDarkMode = getComputedStyle(document.documentElement)
            .getPropertyValue('--is-dark-mode')
            .trim() === 'true';
            
        isDarkMode = systemDarkMode || websiteDarkMode;
        mapStyle = isDarkMode ? 'dark' : 'light';
        
        logger.debug('Dark mode status:', { isDarkMode, mapStyle });
    }

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
        
        // Check dark mode before initializing map
        checkDarkMode();
        
        map = L.map(mapContainer, {
            center: [20, 0],
            zoom: 2,
            zoomControl: false,
            attributionControl: true,
            maxBoundsViscosity: 1.0
        });

        // Update tile layer with proper attribution
        const tileLayer = L.tileLayer(
            'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            {
                maxZoom: 19,
                subdomains: ['a', 'b', 'c'],
                crossOrigin: true,
                className: isDarkMode ? 'dark-tiles' : '',
                attribution: '© OSM'
            }
        ).addTo(map);

        // Watch for dark mode changes
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        mediaQuery.addEventListener('change', () => {
            checkDarkMode();
            if (map) {
                // Update tile layer class instead of changing URL
                const tiles = document.querySelectorAll('.leaflet-tile');
                tiles.forEach(tile => {
                    if (isDarkMode) {
                        tile.classList.add('dark-tiles');
                    } else {
                        tile.classList.remove('dark-tiles');
                    }
                });
            }
        });

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

        // Add zoom control to the right side
        L.control.zoom({
            position: 'topright'
        }).addTo(map);

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

<div class="maps-overlay" transition:slide={{ duration: 300, axis: 'y' }}>
    <div class="precise-toggle">
        <span>{$_('enter_message.location.precise.text')}</span>
        <Toggle 
            bind:checked={isPrecise}
            name="precise-location"
            ariaLabel={$_('enter_message.location.toggle_precise.text')}
        />
    </div>
    
    <div class="map-container" bind:this={mapContainer}></div>

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
                class="clickable-icon icon_location"
                on:click={getCurrentLocation}
                disabled={isLoading}
                aria-label={$_('enter_message.location.get_location.text')}
            >
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
        background: var(--color-grey-0);
        z-index: 1000;
        display: flex;
        flex-direction: column;
        border-radius: 24px;
        overflow: hidden;
    }

    .map-container {
        width: 100%;
        height: 100%;
        background: var(--color-grey-0);
        z-index: 1;
        overflow: hidden;
        border-radius: 24px;
    }

    .bottom-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 53px;
        background: var(--color-grey-0);
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

    .precise-toggle {
        position: absolute;
        top: 0px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--color-grey-0);
        padding: 8px 16px;
        border-radius: 0 0 20px 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        z-index: 1001;
        color: var(--color-font-primary);
    }

    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

    /* Add Leaflet styles */
    :global(.leaflet-container) {
        width: 100%;
        height: 100%;
        background: var(--color-grey-0) !important;
    }

    :global(.leaflet-control-attribution) {
        font-size: 9px !important;
        background: var(--color-grey-0) !important;
        color: var(--color-font-secondary) !important;
        margin-bottom: 60px !important;
        padding: 2px 6px !important;
        border-radius: 8px 0 0 8px !important;
        opacity: 0.7;
        transition: opacity 0.2s ease;
    }

    :global(.leaflet-control-attribution:hover) {
        opacity: 0.9;
    }

    :global(.leaflet-control-attribution a) {
        color: var(--color-font-secondary) !important;
        text-decoration: none !important;
        font-size: 9px !important;
    }

    :global(.leaflet-control-attribution a:hover) {
        text-decoration: underline !important;
    }

    :global(.leaflet-control-zoom a) {
        background: var(--color-grey-0) !important;
        color: var(--color-font-primary) !important;
        border-color: var(--color-grey-0) !important;
    }

    :global(.leaflet-control-zoom a:hover) {
        background: var(--color-grey-0) !important;
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

    /* Dark mode map styles */
    :global(.dark-tiles) {
        filter: invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%) !important;
    }

    /* Improve map controls visibility in dark mode */
    :global(.leaflet-control-zoom) {
        margin: 6px !important;
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
        right: 0 !important;
    }

    /* Update Leaflet zoom control styles */
    :global(.leaflet-control-zoom-in),
    :global(.leaflet-control-zoom-out) {
        width: 57px !important;
        height: 57px !important;
        background: var(--color-grey-0) !important;
        border: none !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 0 !important; /* Hide the default + and - characters */
        position: relative !important;
    }

    /* Use existing clickable-icon classes */
    :global(.leaflet-control-zoom-in::after),
    :global(.leaflet-control-zoom-out::after) {
        content: '';
        width: 20px;
        height: 20px;
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        background: var(--color-primary);
        vertical-align: middle;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        mask-size: contain;
    }

    :global(.leaflet-control-zoom-in::after) {
        -webkit-mask-image: url('/icons/plus.svg');
        mask-image: url('/icons/plus.svg');
    }

    :global(.leaflet-control-zoom-out::after) {
        -webkit-mask-image: url('/icons/minus.svg');
        mask-image: url('/icons/minus.svg');
    }

    :global(.leaflet-control-zoom-in) {
        border-radius: 39px 39px 0 0 !important;
    }

    :global(.leaflet-control-zoom-out) {
        border-radius: 0 0 39px 39px !important;
    }

    :global(.leaflet-control-zoom a:hover) {
        background: var(--color-grey-10) !important;
    }

    /* Remove default Leaflet zoom control borders */
    :global(.leaflet-bar),
    :global(.leaflet-bar a) {
        border: none !important;
    }

    /* Add transition for smoother dark mode switching */
    :global(.leaflet-tile) {
        transition: filter 0.3s ease;
    }
</style> 