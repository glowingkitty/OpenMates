<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { text } from '@repo/ui';
    import { locale } from 'svelte-i18n';
    import type { Map, Marker } from 'leaflet';
    import Toggle from '../Toggle.svelte';
    import 'leaflet/dist/leaflet.css';
    import { getLocaleFromNavigator } from 'svelte-i18n';
    import { get } from 'svelte/store';
    import { tooltip } from '../../actions/tooltip';

    const dispatch = createEventDispatcher();

    // ─── Props ───────────────────────────────────────────────────────────────
    interface Props {
        /** Whether imprecise (area) mode is the default. Controlled by privacy settings. */
        defaultImprecise?: boolean;
    }
    let { defaultImprecise = true }: Props = $props();
    
    let mapContainer: HTMLElement;
    let map: Map | null = null;
    let marker: Marker | null = null;
    let L: any; // Will hold Leaflet instance
    // Default to NOT precise (area mode) — matches privacy-first default.
    // Will be overridden by defaultImprecise prop from caller.
    let isPrecise = $state(false);
    let isLoading = $state(false);
    let currentLocation: { lat: number; lon: number } | null = null;

    // Add dark mode detection
    let isDarkMode = false;
    let mapStyle: 'light' | 'dark' = 'light';
    
    // Add new variable to track map center
    let mapCenter = $state<{ lat: number; lon: number } | null>(null);
    
    let tileLayer: any = null; // Add this variable to track tile layer

    // Add at the top of the script
    let customIcon: any = null;

    let isTransitionComplete = false;

    // Add new variable to track if location was obtained via geolocation
    let isCurrentLocation = false;

    // Add new variable to track if map movement was triggered by getting location
    let isGettingLocation = false;

    // Add new variable to track if map is moving
    let isMapMoving = $state(false);

    // Add new variable to control toggle visibility
    let showPreciseToggle = $state(false);

    // Add new variable to track accuracy circle
    let accuracyCircle: any = null;

    // Add new variable to track accuracy radius
    const ACCURACY_RADIUS = 500; // 500 meters radius for non-precise mode

    // Add new state variables
    let searchQuery = $state('');
    let searchResults = $state<any[]>([]);
    let isSearching = false;
    let showResults = $state(false);

    // Add these new functions and variables to the script section
    let searchMarkers: any[] = [];

    // Add new state variables to store selected location details
    let selectedLocationText: { mainLine: string; subLine: string } | null = null;
    let selectedFromSearch = false;
    let selectedZoomLevel: number | null = null;

    // Add a new variable to track if the map movement is from search selection
    let isMovingFromSearch = false;

    // Add this near the top with other state variables
    let locationIndicatorText = $state<string>('');

    // Add a new variable to track panel transition
    let isPanelTransitioning = false;

    // ─── Reverse geocode state ────────────────────────────────────────────────
    // Stores the resolved street address for the current map center.
    // Populated by reverseGeocode() after map movement stops.
    let resolvedAddress = $state<string>('');
    let reverseGeocodeController: AbortController | null = null;

    // Set initial precision state from prop (runs once after initial render)
    $effect(() => {
        isPrecise = !defaultImprecise;
    });

    // Helper function to capitalize first letter of each word
    function capitalize(str: string) {
        return str.split(' ').map(word => 
            word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
        ).join(' ');
    }

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
                isMovingFromSearch = false;  // Reset the flag when movement ends
                // Always update accuracy circle after movement if not in precise mode
                if (mapCenter && !isPrecise) {
                    updateAccuracyCircle([mapCenter.lat, mapCenter.lon]);
                }
                // Reverse geocode the current center to get a street address
                // Only when no search result was selected (search results carry their own address)
                if (mapCenter && !selectedFromSearch) {
                    reverseGeocode(mapCenter.lat, mapCenter.lon);
                }
            });
            
            mapRef.on('move', () => {
                const center = mapRef.getCenter();
                mapCenter = { lat: center.lat, lon: center.lng };
                
                // Show precise toggle when map is moved
                if (!showPreciseToggle) {
                    showPreciseToggle = true;
                }
                
                // Only reset location text if movement is not from search, getting location, or panel transition
                if (!isGettingLocation && !showResults && !isMovingFromSearch && !isPanelTransitioning) {
                    selectedLocationText = null;
                    selectedFromSearch = false;
                    selectedZoomLevel = null;
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

    // Update precision changes using Svelte 5 $effect
    $effect(() => {
        if (map && mapCenter) {
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
    });

    // Update handleSelect function
    function handleSelect() {
        if (mapCenter) {
            // Always store the precise location (for potential future use/display)
            const preciseLat = mapCenter.lat;
            const preciseLon = mapCenter.lon;

            // For the LLM context: use randomised location within accuracy circle in area mode
            // to protect the user's exact position, while still giving useful context
            const locationForLLM = isPrecise ?
                mapCenter :
                getRandomLocationInCircle(mapCenter, ACCURACY_RADIUS);

            // Resolve the best available address string:
            // - Search result: use the formatted result text (already two lines)
            // - Reverse geocode: use the resolved address
            // - Fallback: use the location indicator text
            const address = resolvedAddress ||
                (selectedLocationText
                    ? [selectedLocationText.mainLine, selectedLocationText.subLine].filter(Boolean).join(', ')
                    : locationIndicatorText);

            const previewData = {
                type: 'mapsEmbed',
                attrs: {
                    // Coordinates sent to LLM (may be randomised in area mode)
                    lat: locationForLLM.lat,
                    lon: locationForLLM.lon,
                    // Always store precise coords for the in-editor preview pin
                    preciseLat,
                    preciseLon,
                    zoom: selectedZoomLevel || 16,
                    // Display name shown in the embed card
                    name: locationIndicatorText || address,
                    // Full resolved street address for LLM context
                    address,
                    // Whether this is a precise pin or a generalised area
                    locationType: isPrecise ? 'precise_location' : 'area',
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

    // Update getCurrentLocale function
    function getCurrentLocale() {
        // Get current locale from svelte-i18n store
        return (get(locale) || getLocaleFromNavigator() || 'en').split('-')[0];
    }

    /**
     * Reverse geocode a lat/lon pair using Nominatim.
     * Called after map movement stops (moveend event).
     * Stores the human-readable address in resolvedAddress so it can be
     * included in the embed when the user taps "Select".
     *
     * Uses an AbortController to cancel any in-flight request when the map
     * moves again before the previous geocode completes.
     */
    async function reverseGeocode(lat: number, lon: number): Promise<void> {
        // Cancel any previous in-flight request
        if (reverseGeocodeController) {
            reverseGeocodeController.abort();
        }
        reverseGeocodeController = new AbortController();
        const signal = reverseGeocodeController.signal;

        try {
            const currentLocale = getCurrentLocale();
            const response = await fetch(
                `https://nominatim.openstreetmap.org/reverse?` +
                `format=json` +
                `&lat=${lat}` +
                `&lon=${lon}` +
                `&zoom=18` +
                `&addressdetails=1` +
                `&accept-language=${currentLocale}`,
                { signal }
            );

            if (!response.ok) return;
            const data = await response.json();

            // Build a human-readable address from the address components
            const addr = data.address || {};
            const parts: string[] = [];

            // Street + house number
            const road = addr.road || addr.pedestrian || addr.footway || addr.path || '';
            const houseNumber = addr.house_number || '';
            if (road && houseNumber) {
                parts.push(`${road} ${houseNumber}`);
            } else if (road) {
                parts.push(road);
            }

            // Postcode + city
            const postcode = addr.postcode || '';
            const city = addr.city || addr.town || addr.village || addr.municipality || addr.county || '';
            if (postcode && city) {
                parts.push(`${postcode} ${city}`);
            } else if (city) {
                parts.push(city);
            }

            // Country
            const country = addr.country || '';
            if (country) {
                parts.push(country);
            }

            resolvedAddress = parts.join(', ') || data.display_name || '';
            logger.debug('Reverse geocoded address:', resolvedAddress);

        } catch (error: any) {
            if (error.name === 'AbortError') {
                // Request was cancelled because map moved — normal behaviour
                return;
            }
            console.error('[MapsView] Reverse geocode error:', error);
        }
    }

    // Update debouncedSearch function
    const debouncedSearch = debounce(async (query: string) => {
        if (!query.trim()) {
            searchResults = [];
            showResults = false;
            removeSearchMarkers();
            return;
        }

        isSearching = true;
        try {
            // Get current locale
            const locale = getCurrentLocale();

            const response = await fetch(
                `https://nominatim.openstreetmap.org/search?` + 
                `format=json` +
                `&q=${encodeURIComponent(query)}` +
                `&limit=5` +
                `&addressdetails=1` +
                `&extratags=1` +
                `&namedetails=1` +
                `&accept-language=${locale}` // Add language parameter
            );
            const results = await response.json();

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

    // Update the formatSearchResult function
    function formatSearchResult(result: any) {
        const locale = getCurrentLocale();
        
        // Helper function to get localized name
        function getLocalizedName(namedetails: any) {
            if (!namedetails) return null;
            
            // Try to get name in current locale
            const localizedName = namedetails[`name:${locale}`];
            if (localizedName) return localizedName;
            
            // Fallback to international name if available
            if (namedetails.name) return namedetails.name;
            
            // Final fallback to default name
            return namedetails.name || null;
        }

        // Get the most appropriate name
        const localizedName = getLocalizedName(result.namedetails);
        const defaultName = result.name || result.display_name.split(',')[0];
        const name = localizedName || defaultName;

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

        return transitTypes;
    }

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

    // Update the handleSearchResultClick function
    function handleSearchResultClick(result: any) {
        if (map) {
            const { lat, lon } = result;
            
            // Reset current location flag when selecting from search
            isCurrentLocation = false;
            
            // Store the selected location text
            selectedLocationText = {
                mainLine: result.mainLine,
                subLine: result.subLine
            };
            selectedFromSearch = true;
            
            // Set zoom level based on result type
            const isAirport = result.metadata?.osmClass === 'aeroway' && 
                (result.metadata?.osmType === 'aerodrome' || result.metadata?.osmType === 'airport');
            selectedZoomLevel = isAirport ? 11 : 16;
            
            // Set flag before moving map
            isMovingFromSearch = true;
            map.setView([lat, lon], selectedZoomLevel);
            
            if (marker) {
                marker.setLatLng([lat, lon]);
                marker.setOpacity(isPrecise ? 1 : 0);
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

    // Update search results panel using Svelte 5 $effect
    $effect(() => {
        if (map && showResults !== undefined) {
            if (mapContainer) {
                isPanelTransitioning = true;  // Set transitioning state
                mapContainer.classList.toggle('with-results', showResults);
                // Trigger a resize event so the map adjusts its viewport
                setTimeout(() => {
                    map?.invalidateSize();
                    // Give extra time for the transition to complete
                    setTimeout(() => {
                        isPanelTransitioning = false;  // Reset transitioning state
                    }, 300);
                }, 300);
            }
        }
    });

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

    // Update marker visibility when search results are shown/hidden using $effect
    $effect(() => {
        if (marker && map) {
            if (showResults) {
                marker.setOpacity(0); // Always hide marker during search results
            } else {
                marker.setOpacity(isPrecise ? 1 : 0); // Normal visibility rules
            }
        }
    });

    // Update location indicator text using $effect
    $effect(() => {
        if (isCurrentLocation) {
            locationIndicatorText = isPrecise ? 
                $text('enter_message.location.current_location') : 
                $text('enter_message.location.current_area');
        } else if (selectedLocationText) {
            // Always use two lines when we have selectedLocationText
            locationIndicatorText = selectedLocationText.subLine ? 
                `${selectedLocationText.mainLine}\n${selectedLocationText.subLine}` : 
                selectedLocationText.mainLine;
        } else {
            locationIndicatorText = isPrecise ? 
                $text('enter_message.location.selected_location') : 
                $text('enter_message.location.selected_area');
        }
    });
</script>

<div 
    class="maps-overlay" 
    transition:slide={{ duration: 300, axis: 'y' }}
    onintroend={onTransitionEnd}
>
    {#if showPreciseToggle && !showResults}
        <div class="precise-toggle" transition:slide={{ duration: 300, axis: 'y' }}>
            <span>{@html $text('enter_message.location.precise')}</span>
            <Toggle 
                bind:checked={isPrecise}
                name="precise-location"
                ariaLabel={$text('enter_message.location.toggle_precise')}
            />
        </div>
    {/if}

    {#if mapCenter && !showResults}
        <div class="location-indicator" class:is-moving={isMapMoving}>
            <div class="location-text">
                {#each locationIndicatorText.split('\n') as line}
                    <span class="location-line">{line}</span>
                {/each}
            </div>
            <button 
                onclick={handleSelect}
                transition:slide={{ duration: 200 }}
                style="padding: 15px;"
            >
                {$text('enter_message.location.select')}
            </button>
        </div>
    {/if}
    
    <div class="map-container" bind:this={mapContainer}></div>

    <div class="bottom-bar">
        <div class="controls">
            <button 
                class="clickable-icon icon_close" 
                onclick={handleClose}
                aria-label={$text('enter_message.location.close')}
                use:tooltip
            ></button>

            <div class="search-container">
                <input
                    type="text"
                    bind:value={searchQuery}
                    oninput={() => debouncedSearch(searchQuery)}
                    placeholder={$text('enter_message.location.search_placeholder')}
                    class="search-input"
                />
            </div>

            <button 
                class="clickable-icon icon_location"
                onclick={getCurrentLocation}
                disabled={isLoading}
                aria-label={$text('enter_message.location.get_location')}
                use:tooltip
            >
            </button>
        </div>
    </div>

    {#if showResults && searchResults.length > 0}
        <div class="search-results-container" transition:slide={{ duration: 300 }}>
            <div class="search-results-header">
                <h3>{@html $text('enter_message.location.search_results')}</h3>
                <button 
                    class="clickable-icon icon_close" 
                    onclick={() => {
                        showResults = false;
                        searchQuery = '';
                        searchResults = [];
                        removeSearchMarkers();
                    }}
                    aria-label={$text('enter_message.location.close_search')}
                    use:tooltip
                ></button>
            </div>
            <div class="search-results">
                {#each searchResults as result}
                    <button 
                        class="search-result-item"
                        class:active={result.active}
                        onclick={() => handleSearchResultClick(result)}
                        onmouseenter={() => highlightSearchResult(result)}
                        onmouseleave={unhighlightSearchResults}
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
        /* Full-viewport modal so the user can focus entirely on the map.
           Uses fixed positioning so it escapes any overflow:hidden parent
           (e.g. .message-field) and covers the whole screen. */
        position: fixed;
        inset: 0;
        background: var(--color-grey-0);
        z-index: 9000;
        display: flex;
        flex-direction: column;
        border-radius: 0;
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
        -webkit-mask-image: url('@openmates/ui/static/icons/plus.svg');
        mask-image: url('@openmates/ui/static/icons/plus.svg');
    }

    :global(.leaflet-control-zoom-out::after) {
        -webkit-mask-image: url('@openmates/ui/static/icons/minus.svg');
        mask-image: url('@openmates/ui/static/icons/minus.svg');
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
        -webkit-mask-image: url('@openmates/ui/static/icons/maps.svg');
        mask-image: url('@openmates/ui/static/icons/maps.svg');
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
        bottom: 230px;
        height: auto;
        min-height: 53px;
        background: var(--color-grey-0);
        padding: 8px 16px;
        border-radius: 20px;
        display: flex;
        align-items: center;
        gap: 12px;
        z-index: 1003;
        color: var(--color-font-primary);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        pointer-events: auto;
        opacity: 1;
        transition: opacity 0.2s ease;
    }

    .location-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
        flex: 1;
        min-width: 0;
    }

    .location-line {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .location-line:first-child {
        font-size: 16px;
        font-weight: 500;
    }

    .location-line:last-child {
        font-size: 14px;
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
        margin: 0 10px;
        align-items: center;
    }

    .search-input {
        width: 100%;
        max-width: 400px;
        height: 36px;
        padding: 0 12px;
        border: 1px solid var(--color-grey-20);
        border-radius: 18px;
        background: var(--color-grey-0);
        color: var(--color-font-primary);
        font-size: 16px;
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
        -webkit-mask-image: url('@openmates/ui/static/icons/maps.svg');
        mask-image: url('@openmates/ui/static/icons/maps.svg');
    }

    .result-icon.icon-travel {
        background: var(--color-app-travel);
        -webkit-mask-image: url('@openmates/ui/static/icons/travel.svg');
        mask-image: url('@openmates/ui/static/icons/travel.svg');
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
        -webkit-mask-image: url('@openmates/ui/static/icons/maps.svg') !important;
        mask-image: url('@openmates/ui/static/icons/maps.svg') !important;
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

    /* 
       Media query for screens with a maximum width of 600px.
       This adjusts the padding, margin, and width of the search elements to ensure that
       the search bar doesn't consume too much horizontal space.
    */
    @media (max-width: 600px) {
        /* Keep minimal padding in the controls container */
        .controls {
            padding: 0 10px;
            gap: 8px; /* Add small gap between elements */
        }

        /* Reduce the width of the search container */
        .search-container {
            margin: 0;
        }

        /* Adjust the search input to fit within the container */
        .search-input {
            width: 100%;
            min-width: 120px; /* Ensure minimum usable width */
            padding: 0 12px;
        }

        /* Ensure icons maintain their original size */
        .clickable-icon {
            flex-shrink: 0; /* Prevent icons from shrinking */
        }
    }
</style> 
