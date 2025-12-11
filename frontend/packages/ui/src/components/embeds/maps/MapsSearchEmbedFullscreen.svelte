<!--
  frontend/packages/ui/src/components/embeds/MapsSearchEmbedFullscreen.svelte
  
  Fullscreen view for Maps Search skill embeds.
  Uses UnifiedEmbedFullscreen as base and provides skill-specific content.
  
  Shows:
  - Search query and provider
  - Desktop: Results list on left, OpenStreetMap on right
  - Mobile: Map on top, scrollable results list below
  - Each place shows name, address, rating, and location
  - Clicking a place centers the map on it
  - Basic infos bar at the bottom
  - Top bar with open, copy, and minimize buttons
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import BasicInfosBar from '../BasicInfosBar.svelte';
  import { onMount, onDestroy } from 'svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import 'leaflet/dist/leaflet.css';
  import type { Map, Marker } from 'leaflet';
  
  /**
   * Place search result interface
   */
  interface PlaceSearchResult {
    displayName?: string;
    formattedAddress?: string;
    location?: {
      latitude?: number;
      longitude?: number;
    };
    rating?: number;
    userRatingCount?: number;
    websiteUri?: string;
    placeId?: string;
  }
  
  /**
   * Props for maps search embed fullscreen
   */
  interface Props {
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Google') */
    provider: string;
    /** Search results */
    results?: PlaceSearchResult[];
    /** Close handler */
    onClose: () => void;
  }
  
  let {
    query,
    provider,
    results = [],
    onClose
  }: Props = $props();
  
  // Determine if mobile layout
  let isMobile = $derived(
    typeof window !== 'undefined' && window.innerWidth <= 500
  );
  
  // Map state - use $state for reactivity
  let mapContainer = $state<HTMLDivElement | null>(null);
  let map = $state<Map | null>(null);
  let markers: Marker[] = [];
  let L: any; // Leaflet instance
  let customIcon: any = null;
  let selectedPlaceIndex = $state<number | null>(null);
  
  // Check dark mode
  let isDarkMode = $derived(() => {
    const systemDarkMode = typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const websiteDarkMode = typeof document !== 'undefined' && 
      getComputedStyle(document.documentElement).getPropertyValue('--is-dark-mode').trim() === 'true';
    return systemDarkMode || websiteDarkMode;
  });
  
  // Format the search query with provider name for title
  let displayTitle = $derived(`${query} via ${provider}`);
  
  // Handle opening search in Google Maps
  function handleOpenInProvider() {
    // Create Google Maps search URL
    const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
    window.open(mapsUrl, '_blank', 'noopener,noreferrer');
  }
  
  // Handle copy YAML of search results
  async function handleCopyYAML() {
    try {
      const yamlData = {
        query: query,
        provider: provider,
        results: results.map(r => ({
          name: r.displayName,
          address: r.formattedAddress,
          rating: r.rating,
          location: r.location
        }))
      };
      
      // Convert to YAML format
      let yaml = `query: "${query}"\n`;
      yaml += `provider: "${provider}"\n`;
      yaml += `results:\n`;
      
      results.forEach((result) => {
        yaml += `  - name: "${result.displayName || ''}"\n`;
        if (result.formattedAddress) {
          yaml += `    address: "${result.formattedAddress.replace(/"/g, '\\"')}"\n`;
        }
        if (result.rating !== undefined) {
          yaml += `    rating: ${result.rating}\n`;
        }
        if (result.location) {
          yaml += `    location:\n`;
          yaml += `      latitude: ${result.location.latitude}\n`;
          yaml += `      longitude: ${result.location.longitude}\n`;
        }
      });
      
      await navigator.clipboard.writeText(yaml);
      console.debug('[MapsSearchEmbedFullscreen] Copied YAML to clipboard');
    } catch (error) {
      console.error('[MapsSearchEmbedFullscreen] Failed to copy YAML:', error);
    }
  }
  
  // Handle opening place in Google Maps
  function handleOpenPlace(place: PlaceSearchResult) {
    if (place.location?.latitude && place.location?.longitude) {
      const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${place.location.latitude},${place.location.longitude}`;
      window.open(mapsUrl, '_blank', 'noopener,noreferrer');
    } else if (place.formattedAddress) {
      const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(place.formattedAddress)}`;
      window.open(mapsUrl, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle selecting a place (centers map on it)
  function handleSelectPlace(place: PlaceSearchResult, index: number) {
    selectedPlaceIndex = index;
    
    if (map && place.location?.latitude && place.location?.longitude) {
      const lat = place.location.latitude;
      const lng = place.location.longitude;
      
      // Center map on the selected place
      map.setView([lat, lng], 15, {
        animate: true,
        duration: 0.5
      });
      
      // Highlight the selected marker
      markers.forEach((marker, i) => {
        if (i === index) {
          marker.setOpacity(1);
          marker.setZIndexOffset(1000);
        } else {
          marker.setOpacity(0.7);
          marker.setZIndexOffset(0);
        }
      });
    }
  }
  
  // Initialize map
  onMount(async () => {
    if (!mapContainer || results.length === 0) return;
    
    try {
      // Dynamically import Leaflet
      L = (await import('leaflet')).default;
      
      // Create custom marker icon
      customIcon = L.divIcon({
        className: 'maps-search-marker',
        html: '<div class="marker-icon"></div>',
        iconSize: [32, 32],
        iconAnchor: [16, 32]
      });
      
      // Get all valid locations
      const validLocations = results
        .map((r, i) => ({ place: r, index: i }))
        .filter(({ place }) => place.location?.latitude && place.location?.longitude);
      
      if (validLocations.length === 0) return;
      
      // Calculate center and bounds
      const lats = validLocations.map(({ place }) => place.location!.latitude!);
      const lngs = validLocations.map(({ place }) => place.location!.longitude!);
      const centerLat = (Math.min(...lats) + Math.max(...lats)) / 2;
      const centerLng = (Math.min(...lngs) + Math.max(...lngs)) / 2;
      
      // Initialize map
      map = L.map(mapContainer!, {
        center: [centerLat, centerLng],
        zoom: 13,
        zoomControl: true,
        attributionControl: true
      });
      
      // Add OpenStreetMap tile layer
      const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        className: isDarkMode() ? 'dark-tiles' : ''
      }).addTo(map);
      
      // Add markers for each place
      validLocations.forEach(({ place, index }) => {
        const lat = place.location!.latitude!;
        const lng = place.location!.longitude!;
        
        const marker = L.marker([lat, lng], {
          icon: customIcon,
          opacity: 0.7
        }).addTo(map!);
        
        // Add popup with place name
        if (place.displayName) {
          marker.bindPopup(place.displayName);
        }
        
        // Add click handler to select place
        marker.on('click', () => {
          handleSelectPlace(place, index);
        });
        
        markers.push(marker);
      });
      
      // Fit map to show all markers
      if (validLocations.length > 1) {
        const bounds = L.latLngBounds(
          validLocations.map(({ place }) => [
            place.location!.latitude!,
            place.location!.longitude!
          ])
        );
        map.fitBounds(bounds, { padding: [50, 50] });
      }
      
      // Update tile layer when dark mode changes
      const updateTileLayer = () => {
        if (tileLayer && map) {
          tileLayer.setUrl('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png');
          if (isDarkMode()) {
            tileLayer.getContainer()?.classList.add('dark-tiles');
          } else {
            tileLayer.getContainer()?.classList.remove('dark-tiles');
          }
        }
      };
      
      // Watch for dark mode changes
      const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
      darkModeQuery.addEventListener('change', updateTileLayer);
      
    } catch (error) {
      console.error('[MapsSearchEmbedFullscreen] Error initializing map:', error);
    }
  });
  
  // Cleanup map on destroy
  onDestroy(() => {
    if (map) {
      map.remove();
      map = null;
    }
    markers = [];
  });
</script>

<UnifiedEmbedFullscreen
  appId="maps"
  skillId="search"
  title={displayTitle}
  {onClose}
  onOpen={handleOpenInProvider}
  onCopy={handleCopyYAML}
>
  {#snippet content()}
    {#if results.length === 0}
      <div class="no-results">
        <p>No search results available.</p>
      </div>
    {:else}
      <!-- Desktop: Side-by-side layout (list left, map right) -->
      <!-- Mobile: Stacked layout (map top, list bottom) -->
      <div class="maps-search-container" class:mobile={isMobile}>
        <!-- Results list -->
        <div class="results-list-container" class:mobile={isMobile}>
          <div class="results-list" class:mobile={isMobile}>
            {#each results as place, index}
              <div 
                class="place-item" 
                class:selected={selectedPlaceIndex === index}
                role="button" 
                tabindex="0" 
                onclick={() => handleSelectPlace(place, index)}
                onkeydown={(e) => e.key === 'Enter' && handleSelectPlace(place, index)}
              >
                <div class="place-header">
                  <h3 class="place-name">{place.displayName || 'Unknown Place'}</h3>
                  {#if place.rating !== undefined}
                    <div class="place-rating">
                      <span class="rating-value">{place.rating.toFixed(1)}</span>
                      {#if place.userRatingCount !== undefined}
                        <span class="rating-count">({place.userRatingCount})</span>
                      {/if}
                    </div>
                  {/if}
                </div>
                {#if place.formattedAddress}
                  <p class="place-address">{place.formattedAddress}</p>
                {/if}
                {#if place.location}
                  <p class="place-location">
                    📍 {place.location.latitude?.toFixed(6)}, {place.location.longitude?.toFixed(6)}
                  </p>
                {/if}
                <button 
                  class="open-place-button"
                  onclick={(e) => {
                    e.stopPropagation();
                    handleOpenPlace(place);
                  }}
                  onkeydown={(e) => {
                    if (e.key === 'Enter') {
                      e.stopPropagation();
                      handleOpenPlace(place);
                    }
                  }}
                >
                  Open in Google Maps
                </button>
              </div>
            {/each}
          </div>
        </div>
        
        <!-- Map container -->
        <div class="map-container" class:mobile={isMobile} bind:this={mapContainer}>
          {#if !map}
            <div class="map-loading">Loading map...</div>
          {/if}
        </div>
      </div>
    {/if}
  {/snippet}
  
  {#snippet bottomBar()}
    <div class="bottom-bar-wrapper">
      <BasicInfosBar
        appId="maps"
        skillId="search"
        skillIconName="search"
        status="finished"
        skillName={query}
        showStatus={false}
        {isMobile}
      />
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* No results message */
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
  }
  
  /* Main container */
  .maps-search-container {
    display: flex;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
  
  /* Desktop: Side-by-side layout */
  .maps-search-container:not(.mobile) {
    flex-direction: row;
  }
  
  /* Mobile: Stacked layout */
  .maps-search-container.mobile {
    flex-direction: column;
    overflow-y: auto;
  }
  
  /* Results list container */
  .results-list-container {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--color-bg-primary);
  }
  
  /* Desktop: Fixed width on left */
  .results-list-container:not(.mobile) {
    width: 400px;
    min-width: 400px;
    border-right: 1px solid var(--color-border);
  }
  
  /* Mobile: Full width, scrollable */
  .results-list-container.mobile {
    width: 100%;
    flex-shrink: 0;
  }
  
  /* Results list */
  .results-list {
    overflow-y: auto;
    padding: 16px;
    height: 100%;
  }
  
  /* Mobile: Results list padding */
  .results-list.mobile {
    padding: 12px;
  }
  
  /* Map container */
  .map-container {
    flex: 1;
    position: relative;
    background: var(--color-bg-secondary);
  }
  
  /* Desktop: Map takes remaining space */
  .map-container:not(.mobile) {
    min-width: 0; /* Allow flex shrinking */
  }
  
  /* Mobile: Fixed height map at top */
  .map-container.mobile {
    width: 100%;
    height: 300px;
    flex-shrink: 0;
    border-bottom: 1px solid var(--color-border);
  }
  
  /* Map loading indicator */
  .map-loading {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: var(--color-font-secondary);
    font-size: 14px;
  }
  
  /* Leaflet map styles */
  :global(.maps-search-container .leaflet-container) {
    width: 100%;
    height: 100%;
    z-index: 0;
  }
  
  :global(.maps-search-container .leaflet-control-attribution) {
    font-size: 10px;
    background: rgba(255, 255, 255, 0.8);
    padding: 2px 4px;
  }
  
  :global(.maps-search-container .leaflet-control-zoom) {
    border: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  }
  
  :global(.maps-search-container .leaflet-control-zoom a) {
    background: var(--color-bg-primary);
    color: var(--color-font-primary);
    border: 1px solid var(--color-border);
  }
  
  :global(.maps-search-container .leaflet-control-zoom a:hover) {
    background: var(--color-bg-secondary);
  }
  
  /* Custom marker styles */
  :global(.maps-search-marker) {
    background: transparent;
    border: none;
  }
  
  :global(.maps-search-marker .marker-icon) {
    width: 32px;
    height: 32px;
    background: var(--color-primary);
    border-radius: 50% 50% 50% 0;
    transform: rotate(-45deg);
    border: 3px solid white;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  }
  
  :global(.maps-search-marker .marker-icon::after) {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) rotate(45deg);
    width: 8px;
    height: 8px;
    background: white;
    border-radius: 50%;
  }
  
  /* Place item */
  .place-item {
    background: var(--color-bg-secondary);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
    cursor: pointer;
    transition: all 0.2s ease;
    border: 2px solid transparent;
  }
  
  .place-item:hover {
    background: var(--color-bg-tertiary);
    border-color: var(--color-border);
  }
  
  .place-item.selected {
    background: var(--color-bg-tertiary);
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb, 0, 123, 255), 0.2);
  }
  
  .place-item:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
  
  /* Place header */
  .place-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 8px;
  }
  
  .place-name {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-grey-100);
    margin: 0;
    flex: 1;
  }
  
  .place-rating {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    color: var(--color-grey-70);
    flex-shrink: 0;
  }
  
  .rating-value {
    font-weight: 600;
    color: var(--color-grey-100);
  }
  
  .rating-count {
    color: var(--color-grey-70);
  }
  
  /* Place address */
  .place-address {
    font-size: 14px;
    color: var(--color-grey-70);
    margin: 4px 0;
    line-height: 1.4;
  }
  
  /* Place location */
  .place-location {
    font-size: 12px;
    color: var(--color-grey-60);
    margin: 4px 0 8px 0;
    font-family: monospace;
  }
  
  /* Open place button */
  .open-place-button {
    margin-top: 8px;
    padding: 8px 16px;
    background: var(--color-primary);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s ease;
    width: 100%;
  }
  
  .open-place-button:hover {
    background: var(--color-primary-dark, var(--color-primary));
    opacity: 0.9;
  }
  
  .open-place-button:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
  
  /* Mobile adjustments */
  .results-list.mobile .place-item {
    padding: 12px;
    margin-bottom: 8px;
  }
  
  .results-list.mobile .place-name {
    font-size: 16px;
  }
  
  .results-list.mobile .place-header {
    flex-direction: column;
    gap: 8px;
  }
  
  /* Scrollbar styling */
  .results-list::-webkit-scrollbar {
    width: 8px;
  }
  
  .results-list::-webkit-scrollbar-track {
    background: var(--color-bg-primary);
  }
  
  .results-list::-webkit-scrollbar-thumb {
    background: var(--color-border);
    border-radius: 4px;
  }
  
  .results-list::-webkit-scrollbar-thumb:hover {
    background: var(--color-grey-60);
  }
</style>
