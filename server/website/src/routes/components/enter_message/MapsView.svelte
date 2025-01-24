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
    let isPrecise = true; // Changed default to true
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

    // Add new variable to track if map movement was triggered by getting location
    let isGettingLocation = false;

    // Add new variable to track if map is moving
    let isMapMoving = false;

    // Add new variable to control toggle visibility
    let showPreciseToggle = false;

    // Add new variable to track accuracy circle
    let accuracyCircle: any = null;

    // Add new variable to track accuracy radius
    const ACCURACY_RADIUS = 500; // 500 meters radius for non-precise mode

    // Add new state variables
    let searchQuery = '';
    let searchResults: any[] = [];
    let isSearching = false;
    let showResults = false;

    // Add these new functions and variables to the script section
    let searchMarkers: any[] = [];

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
            zoomControl: false,  // Disable default zoom controls
            attributionControl: false  // Disable default attribution
        });

        // Create custom attribution control with higher z-index container
        const attributionControl = L.control.attribution({
            position: 'bottomright',
            prefix: false
        });

        // Add custom attribution
        attributionControl.addTo(map);

        // Force the attribution to be visible after a short delay
        setTimeout(() => {
            const attributionElement = mapContainer.querySelector('.leaflet-control-attribution');
            if (attributionElement) {
                (attributionElement as HTMLElement).style.display = 'block';
                (attributionElement as HTMLElement).style.zIndex = '9999';
            }
        }, 100);

        // Add custom zoom control to top-right corner
        L.control.zoom({
            position: 'topright'
        }).addTo(map);

        tileLayer = L.tileLayer(
            'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            {
                maxZoom: 19,
                subdomains: ['a', 'b', 'c'],
                crossOrigin: true,
                className: isDarkMode ? 'dark-tiles' : '',
                attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                updateWhenIdle: false,
                updateInterval: 150,
                keepBuffer: 4
            }
        ).addTo(map);

        if (currentLocation && map) {
            const mapRef = map;
            const zoomLevel = isPrecise ? 16 : 14;
            marker = L.marker([currentLocation.lat, currentLocation.lon], { 
                icon: customIcon,
                opacity: isPrecise ? 1 : 0 
            }).addTo(mapRef);
            mapRef.setView([currentLocation.lat, currentLocation.lon], zoomLevel);
            
            // Initialize accuracy circle if not in precise mode
            if (!isPrecise) {
                updateAccuracyCircle([currentLocation.lat, currentLocation.lon]);
            }
        }

        if (map) {
            const mapRef = map;
            mapRef.on('movestart', () => {
                isMapMoving = true;
            });
            
            mapRef.on('moveend', () => {
                isMapMoving = false;
                // Always update accuracy circle after movement if not in precise mode
                if (mapCenter && !isPrecise) {
                    updateAccuracyCircle([mapCenter.lat, mapCenter.lon]);
                }
            });
            
            mapRef.on('move', () => {
                const center = mapRef.getCenter();
                mapCenter = { lat: center.lat, lon: center.lng };
                
                // Show precise toggle when map is moved
                if (!showPreciseToggle) {
                    showPreciseToggle = true;
                }
                
                // Only reset isCurrentLocation if we're not getting location
                if (!isGettingLocation) {
                    isCurrentLocation = false;
                }
                
                if (marker) {
                    marker.setLatLng([center.lat, center.lng]);
                } else {
                    marker = L.marker([center.lat, center.lng], { 
                        icon: customIcon,
                        opacity: isPrecise ? 1 : 0 
                    }).addTo(mapRef);
                }

                // Update circle position during movement if it exists
                if (!isPrecise && accuracyCircle) {
                    accuracyCircle.setLatLng([center.lat, center.lng]);
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

        // Remove accuracy circle if it exists
        if (accuracyCircle) {
            accuracyCircle.remove();
            accuracyCircle = null;
        }

        searchQuery = '';
        searchResults = [];
        showResults = false;
    }

    // Function to get random location within circle
    function getRandomLocationInCircle(center: { lat: number, lon: number }, radiusMeters: number) {
        // Convert radius from meters to degrees (approximate)
        const radiusInDegrees = radiusMeters / 111320;
        
        // Generate random angle and radius
        const angle = Math.random() * 2 * Math.PI;
        const randomRadius = Math.sqrt(Math.random()) * radiusInDegrees;
        
        // Calculate offset
        const dx = randomRadius * Math.cos(angle);
        const dy = randomRadius * Math.sin(angle);
        
        return {
            lat: center.lat + dy,
            lon: center.lon + dx
        };
    }

    // Update the getCurrentLocation function
    async function getCurrentLocation() {
        if (!navigator.geolocation) {
            logger.info('Geolocation not supported');
            return;
        }

        isLoading = true;
        isGettingLocation = true;
        showPreciseToggle = true; // Show the toggle when getting location

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
            
            if (map) {
                const mapRef = map;
                
                await new Promise<void>(resolve => {
                    const onMoveEnd = () => {
                        mapRef.off('moveend', onMoveEnd);
                        resolve();
                    };
                    mapRef.on('moveend', onMoveEnd);
                    
                    if (!isPrecise) {
                        // For non-precise mode, fit to circle bounds without zoom restriction
                        const circleLatLng = L.latLng(lat, lon);
                        const bounds = circleLatLng.toBounds(ACCURACY_RADIUS);
                        mapRef.fitBounds(bounds, {
                            padding: [50, 50]
                        });
                    } else {
                        // For precise mode, just center with default zoom
                        mapRef.setView([lat, lon], 16);
                    }
                });

                mapCenter = { lat, lon };
                isCurrentLocation = true;

                // Update marker with appropriate opacity
                if (marker) {
                    marker.remove();
                }
                marker = L.marker([lat, lon], { 
                    icon: customIcon,
                    opacity: isPrecise ? 1 : 0 
                }).addTo(mapRef);

                // Update accuracy circle after setting the view
                updateAccuracyCircle([lat, lon]);
            }

            logger.debug('Got location:', { lat, lon, precise: isPrecise });
            
        } catch (error) {
            logger.debug('Error getting location:', error);
        } finally {
            isLoading = false;
            isGettingLocation = false;
        }
    }

    // Update the updateAccuracyCircle function
    function updateAccuracyCircle(center: [number, number]) {
        if (!map) return;

        // If circle doesn't exist and we're in non-precise mode, create it
        if (!accuracyCircle && !isPrecise) {
            accuracyCircle = L.circle(center, {
                radius: ACCURACY_RADIUS,
                fillColor: 'var(--color-primary-start)',
                fillOpacity: 0.2,
                weight: 2,
                opacity: 0.7,
                className: 'accuracy-circle'
            }).addTo(map);
        } 
        // If circle exists, just update its position
        else if (accuracyCircle) {
            accuracyCircle.setLatLng(center);
        }
    }

    // Update the reactive statement for precision changes
    $: if (map && mapCenter) {
        if (!isPrecise) {
            // Only create circle if it doesn't exist
            if (!accuracyCircle) {
                updateAccuracyCircle([mapCenter.lat, mapCenter.lon]);
            }
            // Hide marker completely in non-precise mode
            if (marker) {
                marker.setOpacity(0);
            }
        } else {
            // Remove circle when precision is enabled
            if (accuracyCircle) {
                accuracyCircle.remove();
                accuracyCircle = null;
            }
            // Show marker in precise mode
            if (marker) {
                marker.setOpacity(1);
            }
        }
    }

    // Update handleSelect function
    function handleSelect() {
        if (mapCenter) {
            const selectedLocation = isPrecise ? 
                mapCenter : 
                getRandomLocationInCircle(mapCenter, ACCURACY_RADIUS);

            // Create a preview-friendly format for the map
            const previewData = {
                type: 'customEmbed',
                attrs: {
                    type: 'maps',
                    src: `https://www.openstreetmap.org/?mlat=${selectedLocation.lat}&mlon=${selectedLocation.lon}&zoom=16`,
                    filename: `Location ${selectedLocation.lat.toFixed(6)}, ${selectedLocation.lon.toFixed(6)}`,
                    id: crypto.randomUUID()
                }
            };

            dispatch('locationselected', previewData);
            dispatch('close');
        }
    }

    function handleClose() {
        cleanupMap();
        dispatch('close');
    }

    // Create a debounced search function
    function debounce(func: Function, wait: number) {
        let timeout: ReturnType<typeof setTimeout>;
        
        return function executedFunction(...args: any[]) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    // Create the search function and assign the debounced version
    const debouncedSearch = debounce(async (query: string) => {
        if (!query.trim()) {
            searchResults = [];
            showResults = false;
            removeSearchMarkers();
            return;
        }

        isSearching = true;
        try {
            const response = await fetch(
                `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5`
            );
            const results = await response.json();
            
            searchResults = results.map((result: any) => ({
                name: result.display_name,
                lat: parseFloat(result.lat),
                lon: parseFloat(result.lon),
                type: result.class === 'railway' ? 'railway' : 
                      result.class === 'tourism' && result.type === 'hotel' ? 'hotel' : 
                      'default',
                active: false
            }));
            
            showResults = true;
            addSearchMarkersToMap();
        } catch (error) {
            logger.debug('Search error:', error);
            searchResults = [];
        } finally {
            isSearching = false;
        }
    }, 300);

    // Add function to handle search result selection
    function handleSearchResultClick(result: any) {
        if (map) {
            const { lat, lon } = result;
            map.setView([lat, lon], 16);
            if (marker) {
                marker.setLatLng([lat, lon]);
            }
            searchQuery = '';
            showResults = false;
        }
    }

    // Add inside script section
    $: if (map && showResults !== undefined) {
        if (mapContainer) {  // Add null check for mapContainer
            mapContainer.classList.toggle('with-results', showResults);
            // Trigger a resize event so the map adjusts its viewport
            setTimeout(() => {
                map?.invalidateSize();  // Add optional chaining
            }, 300);
        }
    }

    function getResultIconClass(result: any) {
        return result.type === 'railway' ? 'icon-travel' : 'icon-maps';
    }

    function addSearchMarkersToMap() {
        if (!map) return;
        
        removeSearchMarkers();

        searchMarkers = searchResults.map(result => {
            const markerIcon = L.divIcon({
                className: 'search-marker-icon',
                html: `<div class="marker-icon ${result.type === 'railway' ? 'travel' : 'maps'}"></div>`,
                iconSize: [40, 40],
                iconAnchor: [20, 20]
            });

            return L.marker([result.lat, result.lon], { 
                icon: markerIcon,
                opacity: 1
            }).addTo(map);
        });

        // Fit bounds to show all markers
        if (searchMarkers.length > 0) {
            const group = L.featureGroup(searchMarkers);
            map.fitBounds(group.getBounds(), { padding: [50, 50] });
        }
    }

    function removeSearchMarkers() {
        searchMarkers.forEach(marker => marker.remove());
        searchMarkers = [];
    }

    function highlightSearchResult(result: any) {
        searchResults = searchResults.map(r => ({
            ...r,
            active: r === result
        }));

        // Update marker opacities
        searchMarkers.forEach((marker, index) => {
            marker.setOpacity(searchResults[index] === result ? 1 : 0.5);
        });
    }

    function unhighlightSearchResults() {
        searchResults = searchResults.map(r => ({
            ...r,
            active: false
        }));

        // Reset all marker opacities
        searchMarkers.forEach(marker => marker.setOpacity(1));
    }
</script>

<div 
    class="maps-overlay" 
    transition:slide={{ duration: 300, axis: 'y' }}
    on:introend={onTransitionEnd}
>
    {#if showPreciseToggle}
        <div class="precise-toggle" transition:slide={{ duration: 300, axis: 'y' }}>
            <span>{$_('enter_message.location.precise.text')}</span>
            <Toggle 
                bind:checked={isPrecise}
                name="precise-location"
                ariaLabel={$_('enter_message.location.toggle_precise.text')}
            />
        </div>
    {/if}

    <!-- Update location indicator text -->
    {#if mapCenter}
        <div class="location-indicator" class:is-moving={isMapMoving}>
            <span>
                {#if isCurrentLocation}
                    {isPrecise ? 
                        ($_('enter_message.location.current_location.text') || 'Current location') : 
                        ($_('enter_message.location.current_area.text') || 'Current area')}
                {:else}
                    {isPrecise ? 
                        ($_('enter_message.location.selected_location.text') || 'Selected location') : 
                        ($_('enter_message.location.selected_area.text') || 'Selected area')}
                {/if}
            </span>
            <button 
                on:click={handleSelect}
                transition:slide={{ duration: 200 }}
                style="padding: 15px;"
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

            <div class="search-container">
                <input
                    type="text"
                    bind:value={searchQuery}
                    on:input={() => debouncedSearch(searchQuery)}
                    placeholder={$_('enter_message.location.search.placeholder') || "Search location..."}
                    class="search-input"
                />
                {#if searchQuery}
                    <button 
                        on:click={() => debouncedSearch(searchQuery)}
                        disabled={isSearching}
                    >
                        {$_('enter_message.location.search.button') || "Search"}
                    </button>
                {/if}
            </div>

            <button 
                class="clickable-icon icon_location"
                on:click={getCurrentLocation}
                disabled={isLoading}
                aria-label={$_('enter_message.location.get_location.text')}
            >
            </button>
        </div>
    </div>

    <!-- Add search results container -->
    {#if showResults && searchResults.length > 0}
        <div class="search-results-container" transition:slide={{ duration: 300 }}>
            <div class="search-results-header">
                <h3>{$_('enter_message.location.search_results.text') || 'Search Results'}</h3>
                <button 
                    class="clickable-icon icon_close" 
                    on:click={() => {
                        showResults = false;
                        searchQuery = '';
                        searchResults = [];
                        // Remove search result markers from map
                        removeSearchMarkers();
                    }}
                    aria-label={$_('enter_message.location.close_search.text')}
                ></button>
            </div>
            <div class="search-results">
                {#each searchResults as result}
                    <button 
                        class="search-result-item"
                        class:active={result.active}
                        on:click={() => handleSearchResultClick(result)}
                        on:mouseenter={() => highlightSearchResult(result)}
                        on:mouseleave={unhighlightSearchResults}
                    >
                        <div class="result-icon-container">
                            <div class={`result-icon ${getResultIconClass(result)}`}></div>
                        </div>
                        <div class="result-info">
                            <span class="result-name">{result.name}</span>
                            {#if result.type === 'hotel'}
                                <span class="result-type">Hotel</span>
                            {/if}
                        </div>
                    </button>
                {/each}
            </div>
        </div>
    {/if}
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
        position: absolute;
        top: 0;
        right: 0;
        width: 100%;
        height: calc(100% - 53px);
        transition: width 0.3s ease;
    }

    .map-container.with-results {
        width: 50%;
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
        top: 0;
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
        transition: transform 0.3s ease;
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

    /* Update attribution styles with more specific selectors */
    :global(.leaflet-container .leaflet-control-container .leaflet-bottom.leaflet-right .leaflet-control-attribution) {
        display: block !important;
        position: absolute !important;
        bottom: 65px !important;
        right: 10px !important;
        font-size: 10px !important;
        background: var(--color-grey-0) !important;
        color: var(--color-font-secondary) !important;
        padding: 4px 8px !important;
        border-radius: 8px !important;
        opacity: 0.8;
        z-index: 9999 !important;
        margin: 0 !important;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        pointer-events: auto !important;
        visibility: visible !important;
        white-space: nowrap !important;
        max-width: none !important;
    }

    :global(.leaflet-container .leaflet-control-container .leaflet-bottom.leaflet-right) {
        z-index: 9999 !important;
    }

    :global(.leaflet-container .leaflet-control-container .leaflet-bottom.leaflet-right .leaflet-control-attribution a) {
        color: var(--color-font-secondary) !important;
        text-decoration: none !important;
        font-size: 10px !important;
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
        transition: opacity 0.3s ease;
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
        opacity: 1;
        transition: opacity 0.2s ease;
    }

    /* Add moving state styles */
    .location-indicator.is-moving {
        opacity: 0;
        pointer-events: none;
    }

    /* Add styles for accuracy circle */
    :global(.accuracy-circle) {
        z-index: 400 !important; /* Ensure circle appears above tiles but below controls */
    }

    .search-container {
        flex: 1;
        display: flex;
        gap: 10px;
        margin: 0 15px;
        align-items: center;
    }

    .search-input {
        flex: 1;
        height: 36px;
        padding: 0 12px;
        border: 1px solid var(--color-grey-20);
        border-radius: 18px;
        background: var(--color-grey-0);
        color: var(--color-font-primary);
        font-size: 14px;
    }

    .search-input:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .search-results-container {
        position: absolute;
        top: 0;
        left: 0;
        width: 50%;
        height: calc(100% - 53px);
        background: var(--color-grey-0);
        z-index: 1000;
        border-right: 1px solid var(--color-grey-20);
    }

    .search-results-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .search-results-header h3 {
        margin: 0;
        font-size: 16px;
        font-weight: 500;
    }

    .search-results {
        padding: 10px;
        overflow-y: auto;
        height: calc(100% - 53px);
    }

    .search-result-item {
        width: 100%;
        padding: 12px;
        display: flex;
        align-items: center;
        gap: 12px;
        text-align: left;
        background: none;
        border: none;
        border-radius: 8px;
        color: var(--color-font-primary);
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .search-result-item:hover,
    .search-result-item.active {
        background: var(--color-grey-20);
    }

    .result-icon-container {
        width: 24px;
        height: 24px;
        flex-shrink: 0;
    }

    .result-icon {
        width: 100%;
        height: 100%;
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
    }

    .result-icon.icon-maps {
        background: var(--color-app-maps);
        -webkit-mask-image: url('/icons/maps.svg');
        mask-image: url('/icons/maps.svg');
    }

    .result-icon.icon-travel {
        background: var(--color-app-travel);
        -webkit-mask-image: url('/icons/travel.svg');
        mask-image: url('/icons/travel.svg');
    }

    .result-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .result-name {
        font-size: 14px;
    }

    .result-type {
        font-size: 12px;
        color: var(--color-font-secondary);
    }
</style> 