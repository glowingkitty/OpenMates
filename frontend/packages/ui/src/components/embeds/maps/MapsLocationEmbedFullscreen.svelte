<!--
  frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedFullscreen.svelte

  Fullscreen view for Maps Location skill embeds.
  Uses UnifiedEmbedFullscreen as base.

  Shows:
  - Interactive OpenStreetMap (Leaflet) map centered on the pin — or a static map image
    from S3 if one is available (the image is shown when available for a richer preview).
  - Location name prominently displayed (if provided)
  - Human-readable street address with optional "Nearby:" prefix for area/imprecise mode
  - "Open in Google Maps" button linking to the location
  - Consistent BasicInfosBar at the bottom (no status subtitle — matches preview card)
  - Top bar with share and minimize buttons

  The status subtitle ("Completed") is deliberately hidden via showStatus={false} to keep
  the bar clean — it matches the preview card which also sets showStatus={false}.
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /**
   * Props for maps location embed fullscreen
   */
  interface Props {
    /** Latitude of the location */
    lat?: number;
    /** Longitude of the location */
    lon?: number;
    /** Map zoom level */
    zoom?: number;
    /** Display name for the location */
    name?: string;
    /** Human-readable street address from reverse geocode */
    address?: string;
    /** Location type: 'precise_location' or 'area' */
    locationType?: string;
    /** URL of the static map image stored in S3 (optional — shown when available) */
    mapImageUrl?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Close handler */
    onClose: () => void;
    /** Optional embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button to restore chat visibility */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button to restore chat visibility */
    onShowChat?: () => void;
  }

  let {
    lat,
    lon,
    zoom = 15,
    name,
    address,
    locationType,
    mapImageUrl,
    status = 'finished',
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  // DOM ref for the Leaflet map container
  let mapContainer = $state<HTMLDivElement | null>(null);

  // Whether the static map image loaded successfully
  let imageError = $state(false);

  // Track mounted Leaflet map for cleanup
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let leafletMap: any = null;

  // Show "Nearby:" prefix when the pin was randomised (area/imprecise mode)
  let showNearbyLabel = $derived(locationType === 'area');

  // Whether to show static map image (takes priority over Leaflet when available)
  let hasImage = $derived(!!mapImageUrl && !imageError);

  // Google Maps URL for the "Open in Google Maps" button
  let googleMapsUrl = $derived(
    lat !== undefined && lon !== undefined
      ? `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`
      : null
  );

  // Skill name for the BasicInfosBar
  let skillName = $derived($text('embeds.maps_location'));

  /**
   * Open the location in Google Maps in a new tab
   */
  function handleOpenInGoogleMaps() {
    if (googleMapsUrl) {
      window.open(googleMapsUrl, '_blank', 'noopener,noreferrer');
    }
  }

  /**
   * Initialise a Leaflet map when we have valid coordinates and no static image.
   * Uses OpenStreetMap tiles (same pattern as MapsView and Maps.svelte inline preview).
   * The map is interactive (pan/zoom) so users can explore the area.
   */
  async function initLeafletMap() {
    if (!mapContainer || lat === undefined || lon === undefined) return;

    try {
      // Dynamically import Leaflet to avoid SSR issues
      const L = (await import('leaflet')).default;
      // Leaflet CSS must be imported so map tiles render correctly
      await import('leaflet/dist/leaflet.css');

      // Detect dark mode for tile filter (same logic as Maps.svelte)
      const isDarkMode =
        window.matchMedia('(prefers-color-scheme: dark)').matches ||
        getComputedStyle(document.documentElement)
          .getPropertyValue('--is-dark-mode')
          .trim() === 'true';

      leafletMap = L.map(mapContainer, {
        center: [lat, lon],
        zoom,
        zoomControl: true,
        attributionControl: true
      });

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        className: isDarkMode ? 'dark-tiles' : ''
      }).addTo(leafletMap);

      // Custom pin marker — same visual style as MapsView
      const customIcon = L.divIcon({
        className: 'custom-map-marker',
        html: '<div class="marker-icon"></div>',
        iconSize: [40, 40],
        iconAnchor: [20, 40]
      });

      L.marker([lat, lon], { icon: customIcon }).addTo(leafletMap);

      console.debug('[MapsLocationEmbedFullscreen] Leaflet map initialised at', lat, lon);
    } catch (err) {
      console.error('[MapsLocationEmbedFullscreen] Failed to init Leaflet map:', err);
    }
  }

  onMount(() => {
    // Only initialise Leaflet when there is no static image available.
    // If a static image exists it fills the top slot and no Leaflet map is shown.
    if (!hasImage) {
      initLeafletMap();
    }
  });

  onDestroy(() => {
    if (leafletMap) {
      try {
        leafletMap.remove();
      } catch {
        // ignore cleanup errors
      }
      leafletMap = null;
    }
  });
</script>

<UnifiedEmbedFullscreen
  appId="maps"
  skillId="location"
  title=""
  {onClose}
  currentEmbedId={embedId}
  skillIconName="pin"
  status="finished"
  {skillName}
  showStatus={false}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="location-fullscreen-content">
      <!-- Map section: static image OR interactive Leaflet map -->
      {#if hasImage}
        <!-- Static map image from S3 (generated by backend LocationSkill) -->
        <div class="map-image-container">
          <img
            src={mapImageUrl}
            alt={name || $text('embeds.maps_location')}
            class="map-fullscreen-image"
            onerror={() => { imageError = true; }}
          />
        </div>
      {:else if status === 'processing'}
        <!-- Map is still being generated -->
        <div class="map-placeholder">
          <div class="map-loading-text">{$text('embeds.maps_location.loading_map')}</div>
        </div>
      {:else if lat !== undefined && lon !== undefined}
        <!-- Interactive Leaflet map — shown when no static image is available -->
        <div class="leaflet-map-container" bind:this={mapContainer}></div>
      {:else}
        <!-- No coordinates at all — show pin icon placeholder -->
        <div class="map-placeholder no-image">
          <div class="map-icon-placeholder">
            <span class="location-icon-large"></span>
          </div>
        </div>
      {/if}

      <!-- Location details card -->
      <div class="location-details-card">
        <!-- Location name (if provided) -->
        {#if name}
          <h2 class="location-title">{name}</h2>
        {/if}

        <!-- Street address with optional "Nearby:" prefix -->
        {#if address}
          <div class="location-address-row">
            {#if showNearbyLabel}
              <span class="nearby-label">{$text('embeds.maps_location.nearby')}</span>
            {/if}
            <p class="location-address">{address}</p>
          </div>
        {/if}

        <!-- Open in Google Maps button -->
        {#if googleMapsUrl}
          <button
            class="open-maps-button"
            onclick={handleOpenInGoogleMaps}
          >
            {$text('embeds.maps_location.open_in_google_maps')}
          </button>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Fullscreen Content Layout
     =========================================== */

  .location-fullscreen-content {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow-y: auto;
  }

  /* ===========================================
     Static Map Image
     =========================================== */

  .map-image-container {
    width: 100%;
    flex-shrink: 0;
    /* Give the map image roughly half the available height on desktop */
    max-height: 55vh;
    overflow: hidden;
    background: var(--color-bg-secondary);
  }

  .map-fullscreen-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  /* ===========================================
     Interactive Leaflet Map
     =========================================== */

  .leaflet-map-container {
    width: 100%;
    height: 45vh;
    min-height: 220px;
    flex-shrink: 0;
    /* Create an isolated stacking context so Leaflet's internal z-indexes
       (leaflet-pane uses z-index 400+) do not escape this container and
       cover the UnifiedEmbedFullscreen top-bar buttons. */
    isolation: isolate;
  }

  /* Custom pin marker — same visual style as MapsView */
  :global(.leaflet-map-container .custom-map-marker) {
    background: none;
    border: none;
  }

  :global(.leaflet-map-container .marker-icon) {
    width: 40px;
    height: 40px;
    background-color: var(--color-primary, #6c63ff);
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* Dark tile filter for dark-mode map tiles */
  :global(.leaflet-map-container .dark-tiles) {
    filter: invert(1) hue-rotate(180deg) brightness(0.85) saturate(0.8);
  }

  /* ===========================================
     Placeholder (no coordinates / loading)
     =========================================== */

  .map-placeholder {
    width: 100%;
    height: 240px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-bg-secondary);
    border-bottom: 1px solid var(--color-border);
  }

  .map-placeholder.no-image {
    background: var(--color-bg-tertiary);
  }

  .map-loading-text {
    font-size: 14px;
    color: var(--color-font-secondary);
  }

  .map-icon-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 64px;
    height: 64px;
    background: var(--color-bg-secondary);
    border-radius: 50%;
  }

  .location-icon-large {
    display: block;
    width: 32px;
    height: 32px;
    background-color: var(--color-grey-50);
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  /* ===========================================
     Location Details Card
     =========================================== */

  .location-details-card {
    padding: 24px 24px 32px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    flex: 1;
  }

  /* Location name */
  .location-title {
    font-size: 24px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }

  /* Address row (optional "Nearby:" prefix + address text) */
  .location-address-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  /* "Nearby:" prefix — small, muted, uppercase */
  .nearby-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .location-address {
    font-size: 15px;
    color: var(--color-font-primary);
    line-height: 1.5;
    margin: 0;
    word-break: break-word;
  }

  /* Open in Google Maps button */
  .open-maps-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px 24px;
    background: var(--color-primary);
    color: #fff;
    border: none;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s ease;
    width: 100%;
    max-width: 320px;
    margin-top: 8px;
  }

  .open-maps-button:hover {
    opacity: 0.9;
  }

  .open-maps-button:active {
    opacity: 0.8;
    transform: scale(0.98);
  }

  .open-maps-button:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
</style>
