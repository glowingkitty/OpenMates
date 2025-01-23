<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    import type { Map, Marker } from 'leaflet';
    import Toggle from '../Toggle.svelte';  // Add Toggle import
    import 'leaflet/dist/leaflet.css';
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
    
    // Add new variable to track map center
    let mapCenter: { lat: number; lon: number } | null = null;
    
    let tileLayer: any = null; // Add this variable to track tile layer

    // Add at the top of the script
    let customIcon: any = null;

    let isTransitionComplete = false;

    // Add new variable to track if location was obtained via geolocation
    let isCurrentLocation = false;

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
        logger.debug('Component destroyed');
        cleanupMap();
    });

    async function initializeMap() {
        // Wait for transition to complete
        if (!isTransitionComplete) {
            return;
        }

        logger.debug('Initializing map...');
        
        cleanupMap();
        
        L = (await import('leaflet')).default;
        checkDarkMode();
        
        customIcon = L.divIcon({
            className: 'custom-map-marker',
            html: '<div class="marker-icon"></div>',
            iconSize: [40, 40],
            iconAnchor: [20, 20]
        });
        
        map = L.map(mapContainer, {
            center: currentLocation ? [currentLocation.lat, currentLocation.lon] : [20, 0],
            zoom: currentLocation ? 16 : 2,
            zoomControl: false,
            attributionControl: true,
        });

        // Force map to recalculate size
        setTimeout(() => {
            map?.invalidateSize();
        }, 100);

        tileLayer = L.tileLayer(
            'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            {
                maxZoom: 19,
                subdomains: ['a', 'b', 'c'],
                crossOrigin: true,
                className: isDarkMode ? 'dark-tiles' : '',
                attribution: '© OSM'
            }
        ).addTo(map);

        if (currentLocation && map) {
            const mapRef = map;
            marker = L.marker([currentLocation.lat, currentLocation.lon], { icon: customIcon }).addTo(mapRef);
            mapRef.setView([currentLocation.lat, currentLocation.lon], 16);
        }

        if (map) {
            const mapRef = map;  // Store reference to avoid null check issues
            mapRef.on('move', () => {
                const center = mapRef.getCenter();
                mapCenter = { lat: center.lat, lon: center.lng };
                isCurrentLocation = false; // Reset when user moves the map
                
                if (marker) {
                    marker.setLatLng([center.lat, center.lng]);
                } else {
                    marker = L.marker([center.lat, center.lng], { icon: customIcon }).addTo(mapRef);
                }
            });
        }
    }

    function onTransitionEnd() {
        isTransitionComplete = true;
        initializeMap();
    }

    function cleanupMap() {
        logger.debug('Cleaning up map...');
        
        // Remove marker if it exists
        if (marker) {
            marker.remove();
            marker = null;
        }

        // Remove tile layer if it exists
        if (tileLayer) {
            tileLayer.remove();
            tileLayer = null;
        }

        // Remove map if it exists
        if (map) {
            map.off(); // Remove all event listeners
            map.remove();
            map = null;
        }

        // Reset state
        currentLocation = null;
        mapCenter = null;
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

            isCurrentLocation = true; // Set this to true when getting current location
            
            const { latitude: lat, longitude: lon } = position.coords;
            currentLocation = { lat, lon };
            mapCenter = currentLocation;

            logger.debug('Got location:', { lat, lon, precise: isPrecise });

            // Update map view
            if (map) {
                const mapRef = map;  // Store reference to avoid null check issues
                mapRef.setView([lat, lon], 16);

                // Add or update marker
                if (marker) {
                    marker.setLatLng([lat, lon]);
                } else {
                    marker = L.marker([lat, lon], { icon: customIcon }).addTo(mapRef);
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
        cleanupMap();
        dispatch('close');
    }

    function handleSelect() {
        if (mapCenter) {
            dispatch('locationselected', mapCenter);
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

<div 
    class="maps-overlay" 
    transition:slide={{ duration: 300, axis: 'y' }}
    on:introend={onTransitionEnd}
>
    <div class="precise-toggle">
        <span>{$_('enter_message.location.precise.text')}</span>
        <Toggle 
            bind:checked={isPrecise}
            name="precise-location"
            ariaLabel={$_('enter_message.location.toggle_precise.text')}
        />
    </div>

    <!-- Location indicator above the map -->
    {#if mapCenter}
        <div class="location-indicator">
            <span>{isCurrentLocation ? $_('enter_message.location.current_location.text') || 'Current location' : $_('enter_message.location.selected_location.text') || 'Selected location'}</span>
            <button 
                on:click={handleSelect}
                transition:slide={{ duration: 200 }}
            >
                {$_('enter_message.location.select.text') || 'Select'}
            </button>
        </div>
    {/if}
    
    <div class="map-container" bind:this={mapContainer}></div>

    <div class="bottom-bar">
        <div class="controls">
            <button 
                class="clickable-icon icon_close" 
                on:click={handleClose}
                aria-label={$_('enter_message.location.close.text')}
            ></button>

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

    /* Add custom marker styles */
    :global(.custom-map-marker) {
        background: transparent;
    }

    :global(.marker-icon) {
        width: 40px;
        height: 40px;
        background: var(--color-app-maps);
        -webkit-mask-image: url('/icons/maps.svg');
        mask-image: url('/icons/maps.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
    }

    /* Update location indicator styles */
    .location-indicator {
        position: absolute;
        left: 50%;
        transform: translate(-50%, -50%);
        bottom: 50%;
        height: 53px;
        background: var(--color-grey-0);
        padding: 0 16px;
        border-radius: 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        z-index: 1001;
        color: var(--color-font-primary);
        font-size: 14px;
        font-weight: 500;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        pointer-events: auto;
    }
</style> 