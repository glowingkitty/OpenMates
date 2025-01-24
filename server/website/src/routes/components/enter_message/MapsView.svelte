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
                
                // Only update center marker if search results are not shown
                if (!showResults) {
                    if (marker) {
                        marker.setLatLng([center.lat, center.lng]);
                    } else {
                        marker = L.marker([center.lat, center.lng], { 
                            icon: customIcon,
                            opacity: isPrecise ? 1 : 0 
                        }).addTo(mapRef);
                    }
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

    // Update the formatSearchResult function
    function formatSearchResult(result: any) {
        // Helper function to capitalize first letter of each word
        const capitalize = (str: string) => {
            return str.split(' ').map(word => 
                word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
            ).join(' ');
        };

        // Handle airports
        if (result.class === 'aeroway' && 
            (result.type === 'aerodrome' || result.type === 'airport')) {
            
            // Get airport name and IATA code
            const airportName = result.namedetails?.name || 
                               result.name || 
                               result.display_name.split(',')[0];
            const iataCode = result.extratags?.['iata'] || '';
            
            logger.debug('Formatting airport result:', {
                name: airportName,
                iata: iataCode,
                rawResult: result
            });

            return {
                mainLine: capitalize(airportName) + (iataCode ? ` (${iataCode})` : ''),
                subLine: 'Airport' // Simplified second line for airports
            };
        }
        
        // Handle railway stations
        if (result.class === 'railway' && result.type === 'station') {
            // Use official name without modifications
            const stationName = result.namedetails?.name || 
                               result.name || 
                               result.display_name.split(',')[0];
            
            // Get city name
            const city = result.address?.city || 
                        result.address?.town || 
                        result.address?.village || 
                        result.address?.municipality || 
                        '';
            
            return {
                mainLine: capitalize(stationName),
                subLine: capitalize(city)
            };
        }
        
        // Handle places (amenities, shops, etc.)
        else if (result.class === 'amenity' || 
                 result.class === 'shop' || 
                 result.class === 'tourism' ||
                 result.class === 'leisure') {
            
            // Get the place name
            const placeName = result.namedetails?.name || 
                             result.name || 
                             result.address?.amenity ||
                             result.address?.shop ||
                             result.address?.tourism ||
                             result.address?.leisure ||
                             '';
                             
            // Construct the address line
            const streetNumber = result.address?.house_number || '';
            const street = result.address?.road || 
                          result.address?.pedestrian || 
                          result.address?.footway || 
                          result.address?.path || 
                          '';
            
            // Combine street and number in the correct order based on address format
            const addressLine = street && streetNumber ? 
                `${street} ${streetNumber}` : 
                street || streetNumber;
                
            logger.debug('Formatting place result:', {
                name: placeName,
                address: addressLine,
                rawAddress: result.address
            });

            return {
                mainLine: capitalize(placeName),
                subLine: capitalize(addressLine)
            };
        }
        
        // Handle other locations (default case)
        else {
            const name = result.namedetails?.name || 
                        result.name || 
                        result.display_name.split(',')[0];
                        
            // Look for address components
            const street = result.address?.road || 
                          result.address?.pedestrian || 
                          result.address?.footway || 
                          result.address?.path;
            const houseNumber = result.address?.house_number;
            const postalCode = result.address?.postcode;
            const city = result.address?.city || 
                        result.address?.town || 
                        result.address?.village || 
                        result.address?.municipality;

            // Construct subline based on available information
            let subLine = '';
            if (street && houseNumber) {
                subLine = `${street} ${houseNumber}`;
            } else if (street) {
                subLine = street;
            }
            if (city) {
                subLine = subLine ? `${subLine}, ${city}` : city;
            }
            if (postalCode && city) {
                subLine = `${postalCode} ${subLine}`;
            }

            return {
                mainLine: capitalize(name),
                subLine: capitalize(subLine)
            };
        }
    }

    // Add helper function to determine transit types
    function getTransitTypes(result: any) {
        const tags = result.extratags || {};
        
        // Initialize transit types object with airport
        const transitTypes = {
            subway: false,
            suburban: false,
            rail: false,
            lightrail: false,
            bus: false,
            ferry: false,
            airport: false  // Add airport type
        };

        // Check for airports
        if (result.class === 'aeroway' && 
            (result.type === 'aerodrome' || result.type === 'airport')) {
            transitTypes.airport = true;
        }

        // Helper function to check if any tag matches any of the terms
        const hasTag = (tagNames: string[], values: string[]) => {
            return tagNames.some(tag => {
                const tagValue = (tags[tag] || '').toLowerCase();
                return values.some(value => tagValue.includes(value));
            });
        };

        // Check if this is any kind of public transport facility
        if (result.class === 'railway' || 
            result.class === 'public_transport' || 
            tags['public_transport'] ||
            tags['railway']) {

            // Check for subway/metro
            if (hasTag(
                ['railway', 'station', 'public_transport'],
                ['subway', 'metro', 'underground']
            )) {
                transitTypes.subway = true;
            }

            // Check for suburban/regional rail
            if (hasTag(
                ['railway', 'service', 'station'],
                ['suburban', 'regional', 'commuter']
            )) {
                transitTypes.suburban = true;
            }

            // Check for light rail/tram
            if (hasTag(
                ['railway', 'station', 'public_transport'],
                ['tram', 'light_rail']
            )) {
                transitTypes.lightrail = true;
            }

            // Check for mainline rail
            if (result.class === 'railway' && 
                (tags['railway'] === 'station' || 
                 tags['public_transport'] === 'station')) {
                // Additional check to ensure it's actually a train station
                if (tags['train'] === 'yes' || 
                    tags['usage'] === 'main' || 
                    tags['station'] === 'rail' ||
                    (!transitTypes.subway && !transitTypes.lightrail)) {
                    transitTypes.rail = true;
                }
            }

            // Check for bus stations/stops
            if (tags['highway'] === 'bus_stop' || 
                tags['bus'] === 'yes' ||
                (tags['public_transport'] === 'platform' && tags['bus'] === 'yes')) {
                transitTypes.bus = true;
            }

            // Check for ferry terminals
            if (tags['amenity'] === 'ferry_terminal' ||
                tags['ferry'] === 'yes') {
                transitTypes.ferry = true;
            }
        }

        logger.debug('Transit types detected:', {
            name: result.namedetails?.name || result.name,
            transitTypes,
            rawTags: {
                class: result.class,
                type: result.type,
                aeroway: tags['aeroway'],
                publicTransport: tags['public_transport'],
                railway: tags['railway'],
                station: tags['station'],
                usage: tags['usage'],
                train: tags['train']
            }
        });
        
        return transitTypes;
    }

    // Modify the debouncedSearch function to request address details
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
                `https://nominatim.openstreetmap.org/search?` + 
                `format=json` +
                `&q=${encodeURIComponent(query)}` +
                `&limit=5` +
                `&addressdetails=1` +  // Request detailed address information
                `&extratags=1` +       // Get additional tags like opening hours, website, etc.
                `&namedetails=1`       // Get names in different languages
            );
            const results = await response.json();
            
            logger.debug('Search results with details:', results);
            
            // Format and assign a unique ID to each search result
            searchResults = results.map((result: any) => {
                const formattedResult = formatSearchResult(result);
                const transitTypes = getTransitTypes(result);
                
                // Format transit types for display
                const transitServices = [];
                if (transitTypes.rail) transitServices.push('Railway');
                if (transitTypes.subway) transitServices.push('Subway');
                if (transitTypes.suburban) transitServices.push('S-Bahn');
                if (transitTypes.lightrail) transitServices.push('Tram');
                if (transitTypes.bus) transitServices.push('Bus');
                if (transitTypes.ferry) transitServices.push('Ferry');

                // For stations, only show transit types
                const subLine = result.class === 'railway' ? 
                    transitServices.join(', ') : 
                    formattedResult.subLine;

                return {
                    id: crypto.randomUUID(),
                    mainLine: formattedResult.mainLine,
                    subLine: subLine,
                    lat: parseFloat(result.lat),
                    lon: parseFloat(result.lon),
                    type: result.class === 'railway' ? 'railway' : 
                          result.class === 'tourism' && result.type === 'hotel' ? 'hotel' : 
                          'default',
                    active: false,
                    metadata: {
                        osmClass: result.class,
                        osmType: result.type,
                        importance: result.importance,
                        extraTags: result.extratags || {},
                        transitTypes: transitTypes
                    }
                };
            });
            
            showResults = true;
            addSearchMarkersToMap();
        } catch (error) {
            logger.debug('Search error:', error);
            searchResults = [];
        } finally {
            isSearching = false;
        }
    }, 300);

    // Update the getResultIconClass function
    function getResultIconClass(result: any) {
        // Check for airport first
        if (result.metadata?.osmClass === 'aeroway' && 
            (result.metadata?.osmType === 'aerodrome' || result.metadata?.osmType === 'airport')) {
            return 'icon-travel';
        }
        // Then check for railway
        if (result.type === 'railway') {
            return 'icon-travel';
        }
        return 'icon-maps';
    }

    // Update the addSearchMarkersToMap function
    function addSearchMarkersToMap() {
        if (!map) return;
        
        removeSearchMarkers();

        searchMarkers = searchResults.map(result => {
            // Check if result is an airport
            const isAirport = result.metadata?.osmClass === 'aeroway' && 
                (result.metadata?.osmType === 'aerodrome' || result.metadata?.osmType === 'airport');
            
            const isTransport = result.type === 'railway' || isAirport;
            
            const markerIcon = L.divIcon({
                className: `search-marker-icon ${isAirport ? 'airport' : isTransport ? 'railway' : 'default'}`,
                html: `<div class="marker-icon"></div>`,
                iconSize: [40, 40],
                iconAnchor: [20, 20]
            });

            const marker = L.marker([result.lat, result.lon], { 
                icon: markerIcon,
                opacity: 1
            }).addTo(map);

            marker.associatedResultId = result.id;
            return marker;
        });

        // Fit bounds to show all markers with appropriate zoom
        if (searchMarkers.length > 0) {
            const group = L.featureGroup(searchMarkers);
            const bounds = group.getBounds();
            
            // Check if all results are airports
            const allAirports = searchResults.every(result => 
                result.metadata?.osmClass === 'aeroway' && 
                (result.metadata?.osmType === 'aerodrome' || result.metadata?.osmType === 'airport')
            );

            // If all results are airports, use a more zoomed out view
            if (allAirports) {
                const center = bounds.getCenter();
                map.setView(center, 11); // Use zoom level 11 for airports
            } else {
                map.fitBounds(bounds, { padding: [50, 50] });
            }
        }
    }

    // Update the highlightSearchResult function to adjust opacity based on associated result ID
    function highlightSearchResult(result: any) {
        
        searchResults = searchResults.map(r => ({
            ...r,
            active: r.id === result.id // Update active state based on ID
        }));

        // Update only search result markers based on association
        searchMarkers.forEach(marker => {
            if (marker.associatedResultId === result.id) {
                marker.setOpacity(1); // Highlight hovered marker
            } else {
                marker.setOpacity(0.5); // Dim other markers
            }
        });

        // Ensure center marker stays hidden during search
        if (marker && showResults) {
            marker.setOpacity(0);
        }
    }

    // Update the handleSearchResultClick function to reset marker opacities
    function handleSearchResultClick(result: any) {
        if (map) {
            const { lat, lon } = result;
            map.setView([lat, lon], 16);
            
            if (marker) {
                marker.setLatLng([lat, lon]);
                marker.setOpacity(isPrecise ? 1 : 0); // Restore normal visibility
            } else {
                marker = L.marker([lat, lon], { 
                    icon: customIcon,
                    opacity: isPrecise ? 1 : 0 
                }).addTo(map);
            }
            
            mapCenter = { lat, lon };
            searchQuery = '';
            showResults = false;
            removeSearchMarkers();
        }

        // Reset all search markers to full opacity when a result is selected
        searchMarkers.forEach(marker => {
            marker.setOpacity(0.5);
        });
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

    function removeSearchMarkers() {
        searchMarkers.forEach(marker => marker.remove());
        searchMarkers = [];
    }

    function unhighlightSearchResults() {
        searchResults = searchResults.map(r => ({
            ...r,
            active: false
        }));

        // Reset only search result markers
        searchMarkers.forEach(marker => marker.setOpacity(1));

        // Ensure center marker stays hidden during search
        if (marker && showResults) {
            marker.setOpacity(0);
        }
    }

    // Update marker visibility when search results are shown/hidden
    $: if (marker && map) {
        if (showResults) {
            marker.setOpacity(0); // Always hide marker during search results
        } else {
            marker.setOpacity(isPrecise ? 1 : 0); // Normal visibility rules
        }
    }
</script>

<div 
    class="maps-overlay" 
    transition:slide={{ duration: 300, axis: 'y' }}
    on:introend={onTransitionEnd}
>
    {#if showPreciseToggle && !showResults}
        <div class="precise-toggle" transition:slide={{ duration: 300, axis: 'y' }}>
            <span>{$_('enter_message.location.precise.text')}</span>
            <Toggle 
                bind:checked={isPrecise}
                name="precise-location"
                ariaLabel={$_('enter_message.location.toggle_precise.text')}
            />
        </div>
    {/if}

    {#if mapCenter && !showResults}
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
                    placeholder={$_('enter_message.location.search_placeholder.text') || "Search location..."}
                    class="search-input"
                />
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
                            <span class="result-name">{result.mainLine}</span>
                            {#if result.subLine}
                                <span class="result-location">{result.subLine}</span>
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
        z-index: 1;
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
        z-index: 1003;
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
        bottom: 5px !important;
        right: 5px !important;
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
        bottom: 230px; /* Move it to 60% from bottom instead of 75% + 20px */
        height: 53px;
        background: var(--color-grey-0);
        padding: 0 16px;
        border-radius: 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        z-index: 1003;
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
        justify-content: center;
        margin: 0 15px;
        align-items: center;
    }

    .search-input {
        width: 80%;
        max-width: 400px;
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
        height: calc(100% - 80px);
        background: var(--color-grey-0);
        z-index: 2;
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
        overflow-x: hidden;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }

    .search-results:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .search-results::-webkit-scrollbar {
        width: 8px;
    }

    .search-results::-webkit-scrollbar-track {
        background: transparent;
    }

    .search-results::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid transparent;
        transition: background-color 0.2s ease;
    }

    .search-results:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .search-results::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }

    .search-result-item {
        width: 100%;
        height: auto; /* Remove fixed height */
        min-height: 48px;
        padding: 12px;
        display: flex;
        align-items: flex-start;
        gap: 12px;
        text-align: left;
        background: none;
        border: none;
        border-radius: 8px;
        color: var(--color-font-primary);
        cursor: pointer;
        transition: all 0.2s ease;
        white-space: normal;
        word-wrap: break-word;
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
        flex: 1;
        min-width: 0;
        height: auto; /* Allow content to determine height */
    }

    .result-name {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-font-primary);
        line-height: 1.4;
    }

    .result-location {
        font-size: 12px;
        color: var(--color-font-secondary);
        line-height: 1.4;
    }

    .result-type {
        font-size: 12px;
        color: var(--color-font-secondary);
    }

    /* Update marker styles to ensure they appear above the map but below UI */
    :global(.leaflet-marker-pane) {
        z-index: 600 !important;
    }

    :global(.custom-map-marker),
    :global(.search-marker-icon) {
        z-index: 600 !important;
    }

    :global(.search-marker-icon .marker-icon) {
        width: 40px;
        height: 40px;
        -webkit-mask-image: url('/icons/maps.svg') !important;
        mask-image: url('/icons/maps.svg') !important;
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
    }

    :global(.search-marker-icon.default .marker-icon) {
        background: var(--color-app-maps) !important;
    }

    :global(.search-marker-icon.railway .marker-icon) {
        background: var(--color-app-travel) !important;
    }

    :global(.search-marker-icon.airport .marker-icon) {
        background: var(--color-app-travel) !important;
    }

    /* Update UI element z-indices to ensure they stay on top */
    .precise-toggle {
        z-index: 1003;
    }

    .location-indicator {
        z-index: 1003;
    }

    .bottom-bar {
        z-index: 1003;
    }

    /* Update search results styles for better text wrapping */
    .search-results {
        padding: 10px;
        overflow-y: auto;
        height: calc(100% - 53px);
        overflow-x: hidden;
    }

    .search-result-item {
        width: 100%;
        height: auto; /* Remove fixed height */
        min-height: 48px;
        padding: 12px;
        display: flex;
        align-items: flex-start;
        gap: 12px;
        text-align: left;
        background: none;
        border: none;
        border-radius: 8px;
        color: var(--color-font-primary);
        cursor: pointer;
        transition: all 0.2s ease;
        white-space: normal;
        word-wrap: break-word;
    }

    .result-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
        flex: 1;
        min-width: 0;
        height: auto; /* Allow content to determine height */
    }

    .result-name {
        font-size: 14px;
        white-space: pre-wrap;
        word-break: break-word;
        overflow-wrap: break-word;
        line-height: 1.4; /* Add line height for better readability */
    }
</style> 