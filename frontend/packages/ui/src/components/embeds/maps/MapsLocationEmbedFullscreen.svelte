<!--
  frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedFullscreen.svelte

  Fullscreen view for Maps Location skill embeds.
  Uses UnifiedEmbedFullscreen as base.

  Shows:
  - Large static map image (if available) filling most of the view
  - Location name prominently displayed
  - Latitude/longitude coordinates
  - "Open in Google Maps" button linking to the location
  - Consistent BasicInfosBar at the bottom (matches preview - "Location" + "Completed")
  - Top bar with share and minimize buttons

  The map image is a static Google Maps PNG stored in S3 (not client-encrypted).
  It is displayed directly via an <img> tag with the S3 URL.
-->

<script lang="ts">
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
    /** Type of location: 'precise_location' or 'area' */
    locationType?: string;
    /** URL of the static map image stored in S3 */
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
    name,
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

  // Whether the map image loaded successfully
  let imageError = $state(false);

  // Formatted coordinates string for display
  let coordsText = $derived(
    lat !== undefined && lon !== undefined
      ? `${lat.toFixed(6)}, ${lon.toFixed(6)}`
      : ''
  );

  // Whether to show map image section
  let hasImage = $derived(!!mapImageUrl && !imageError);

  // Google Maps URL for the "Open in Google Maps" button
  let googleMapsUrl = $derived(
    lat !== undefined && lon !== undefined
      ? `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`
      : null
  );

  /**
   * Open the location in Google Maps in a new tab
   */
  function handleOpenInGoogleMaps() {
    if (googleMapsUrl) {
      window.open(googleMapsUrl, '_blank', 'noopener,noreferrer');
    }
  }

  // Skill name for the BasicInfosBar
  let skillName = $derived($text('embeds.maps_location'));
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
  showStatus={true}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="location-fullscreen-content">
      <!-- Map image section -->
      {#if hasImage}
        <div class="map-image-container">
          <img
            src={mapImageUrl}
            alt={name || $text('embeds.maps_location')}
            class="map-fullscreen-image"
            onerror={() => { imageError = true; }}
          />
        </div>
      {:else if status === 'processing'}
        <div class="map-placeholder">
          <div class="map-loading-text">{$text('embeds.maps_location.loading_map')}</div>
        </div>
      {:else}
        <!-- No image available: show a simple coordinate display -->
        <div class="map-placeholder no-image">
          <div class="map-icon-placeholder">
            <span class="location-icon-large"></span>
          </div>
        </div>
      {/if}

      <!-- Location details card -->
      <div class="location-details-card">
        <!-- Location name -->
        <h2 class="location-title">
          {name || $text('embeds.maps_location')}
        </h2>

        <!-- Coordinates -->
        {#if coordsText}
          <div class="location-info-row">
            <span class="info-label">{$text('embeds.maps_location.coordinates')}</span>
            <span class="info-value coords-value">{coordsText}</span>
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
     Map Image
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

  /* Placeholder when no image is available or loading */
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
    gap: 16px;
    flex: 1;
  }

  /* Location title */
  .location-title {
    font-size: 24px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }

  /* Info row (label + value pairs) */
  .location-info-row {
    display: flex;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
  }

  .info-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    flex-shrink: 0;
  }

  .info-value {
    font-size: 15px;
    color: var(--color-font-primary);
    line-height: 1.4;
  }

  .coords-value {
    font-family: monospace;
    font-size: 14px;
    color: var(--color-grey-70);
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
