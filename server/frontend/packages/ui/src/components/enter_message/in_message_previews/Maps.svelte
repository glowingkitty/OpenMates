<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount } from 'svelte';
    import 'leaflet/dist/leaflet.css';
    import { _, getLocaleFromNavigator, locale } from 'svelte-i18n';
    import { get } from 'svelte/store';

    export let id: string;
    export let lat: number;
    export let lon: number;
    export let zoom: number;
    export let name: string;

    let mapContainer: HTMLDivElement;
    // Initialize address with name or a default value
    let address: string = name || 'Loading location...';
    let coordinates: { lat: number; lon: number } | null = null;
    let L: any;
    let customIcon: any = null;
    let lastGeocodedLocation: string | null = null;

    // Logger for debugging
    const logger = {
        debug: (...args: any[]) => console.log('[MapsPreview]', ...args),
        info: (...args: any[]) => console.info('[MapsPreview]', ...args)
    };

    // Add function to get current locale
    function getCurrentLocale() {
        return (get(locale) || getLocaleFromNavigator() || 'en').split('-')[0];
    }

    // Function to format address consistently across components
    function formatAddress(data: any): string {
        const locale = getCurrentLocale();
        
        // Helper function to get localized name
        function getLocalizedName(obj: any, key: string) {
            if (!obj) return null;
            
            // Try locale-specific name first
            const localizedKey = `${key}:${locale}`;
            if (obj[localizedKey]) return obj[localizedKey];
            
            // Fallback to default name
            return obj[key] || null;
        }

        if (!data.address) {
            return coordinates ? 
                `${coordinates.lat.toFixed(6)}, ${coordinates.lon.toFixed(6)}` : 
                'Unknown location';
        }

        const line1Parts = [];
        const line2Parts = [];
        
        // First line: Street name and number
        if (data.address.road) {
            line1Parts.push(getLocalizedName(data.address, 'road') || data.address.road);
            if (data.address.house_number) line1Parts.push(data.address.house_number);
        } else if (data.address.city) {
            line1Parts.push(getLocalizedName(data.address, 'city') || data.address.city || 
                           getLocalizedName(data.address, 'town') || data.address.town);
        } else if (data.address.country) {
            line1Parts.push(getLocalizedName(data.address, 'country') || data.address.country);
        }
        
        // Second line: Always try to include city/region and country
        if (data.address.postcode) line2Parts.push(data.address.postcode);
        if (data.address.city && !line1Parts.includes(data.address.city)) {
            line2Parts.push(getLocalizedName(data.address, 'city') || data.address.city || 
                           getLocalizedName(data.address, 'town') || data.address.town);
        }
        if (data.address.state && data.address.state !== data.address.city) {
            line2Parts.push(getLocalizedName(data.address, 'state') || data.address.state);
        }
        if (data.address.country && !line1Parts.includes(data.address.country)) {
            line1Parts.push(getLocalizedName(data.address, 'country') || data.address.country);
        }
        
        // If we have no second line but have coordinates, use them
        if (line2Parts.length === 0 && coordinates) {
            line2Parts.push(`${coordinates.lat.toFixed(6)}, ${coordinates.lon.toFixed(6)}`);
        }

        return line2Parts.length > 0 ? 
            `${line1Parts.join(' ')}\n${line2Parts.join(', ')}` : 
            line1Parts.join(' ');
    }

    async function updateAddress(lat: number, lon: number, forceUpdate: boolean = false) {
        const locationKey = `${lat},${lon}`;
        
        if (!forceUpdate && lastGeocodedLocation === locationKey) {
            return;
        }

        try {
            const locale = getCurrentLocale();
            
            const response = await fetch(
                `https://nominatim.openstreetmap.org/reverse?` +
                `lat=${lat}&lon=${lon}` +
                `&format=json` +
                `&accept-language=${locale}`,
                {
                    headers: {
                        'User-Agent': 'OpenMates/1.0'
                    }
                }
            );
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            address = formatAddress(data);
            lastGeocodedLocation = locationKey;
            
            logger.debug('Updated address:', { address, data, locale });
        } catch (error) {
            logger.debug('Error getting address:', error);
            address = coordinates ? 
                `${coordinates.lat.toFixed(6)}, ${coordinates.lon.toFixed(6)}` : 
                'Error loading location';
        }
    }

    onMount(async () => {
        try {
            if (typeof lat !== 'number' || typeof lon !== 'number') {
                throw new Error('Invalid map coordinates');
            }

            coordinates = { lat, lon };
            // Set address to name or coordinates if name is not provided
            address = name || `${lat.toFixed(6)}, ${lon.toFixed(6)}`;

            L = (await import('leaflet')).default;
            
            // Create custom icon
            customIcon = L.divIcon({
                className: 'custom-map-marker',
                html: '<div class="marker-icon"></div>',
                iconSize: [40, 40],
                iconAnchor: [20, 40]
            });
            
            // Check if dark mode is active
            const isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches || 
                getComputedStyle(document.documentElement).getPropertyValue('--is-dark-mode').trim() === 'true';
            
            const map = L.map(mapContainer, {
                center: [coordinates.lat, coordinates.lon],
                zoom: zoom,
                zoomControl: false,
                dragging: false,
                touchZoom: false,
                scrollWheelZoom: false,
                doubleClickZoom: false,
                attributionControl: false
            });

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '',
                className: isDarkMode ? 'dark-tiles' : ''
            }).addTo(map);

            L.marker([coordinates.lat, coordinates.lon], {
                icon: customIcon
            }).addTo(map);

            // Add zoom end event listener to update address only when zoom changes significantly
            map.on('zoomend', async () => {
                const center = map.getCenter();
                await updateAddress(center.lat, center.lng);
            });

        } catch (error) {
            logger.debug('Error loading map preview:', error);
            address = 'Error loading location';
        }
    });
</script>

<InlinePreviewBase {id} type="maps" height="200px">
    <div class="preview-container">
        <div class="map-preview" bind:this={mapContainer}></div>
        <div class="info-bar">
            <div class="icon_rounded maps"></div>
            <div class="text-container">
                {#each address.split('\n') as line}
                    <span class="address-line">{line}</span>
                {/each}
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
        gap: 2px;
    }

    .address-line {
        font-size: 16px;
        color: var(--color-font-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .address-line:nth-child(2) {
        font-size: 14px;
        color: var(--color-font-primary);
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

    /* Hide all attribution elements */
    :global(.leaflet-control-attribution) {
        display: none !important;
    }

    /* Dark mode map styles */
    :global(.dark-tiles) {
        filter: invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%) !important;
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

    /* Add these new styles */
    :global(.maps-embed-container) {
        margin: 8px 0;
        display: block;
        width: 100%;
    }

    :global(.ProseMirror) .preview-container {
        pointer-events: all;
    }
</style>
