<!--
  frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedPreview.svelte

  Preview component for Maps Location skill embeds.
  Uses UnifiedEmbedPreview as base with skill-specific details content.

  When a user selects a location via the MapsView map picker, the backend
  LocationSkill generates a static map image and stores it in S3. This component
  displays that image (if available) along with the location name.

  Details content:
  - Has map image: shows static map image full-width (hasFullWidthImage=true)
  - No map image: shows location name + coordinates text

  Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  /**
   * Props for maps location embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Display name for the location (e.g. "Current location" or search result name) */
    name?: string;
    /** Human-readable street address from Nominatim reverse geocode or search result */
    address?: string;
    /**
     * Location type from MapsView: "precise_location" or "area".
     * When "area" the user had imprecise/privacy mode on — show a small "Nearby:" prefix label.
     */
    locationType?: string;
    /**
     * Category label for search results (e.g. "Railway", "Airport", "Hotel").
     * Empty string for manual/current-location pins.
     * Shown as a muted line beneath the place name in the text fallback layout.
     */
    placeType?: string;
    /** URL of the static map image stored in S3 */
    mapImageUrl?: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }

  let {
    id,
    name: nameProp,
    address: addressProp,
    locationType: locationTypeProp,
    placeType: placeTypeProp,
    mapImageUrl: mapImageUrlProp,
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state — updated by embed data events via onEmbedDataUpdated.
  let localName = $state<string>('');
  let localAddress = $state<string>('');
  let localLocationType = $state<string>('area');
  let localPlaceType = $state<string>('');
  let localMapImageUrl = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  let imageError = $state(false);

  // Sync local state from props on initial mount / prop changes
  $effect(() => {
    localName = nameProp ?? '';
    localAddress = addressProp ?? '';
    localLocationType = locationTypeProp ?? 'area';
    localPlaceType = placeTypeProp ?? '';
    localMapImageUrl = mapImageUrlProp;
    localStatus = statusProp ?? 'processing';
    localTaskId = taskIdProp;
  });

  // Expose as derived read-only aliases for clarity
  let name = $derived(localName);
  let address = $derived(localAddress);
  let locationType = $derived(localLocationType);
  let placeType = $derived(localPlaceType);
  let mapImageUrl = $derived(localMapImageUrl);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);

  /**
   * Handle embed data updates from UnifiedEmbedPreview.
   * Called when the server sends updated embed content (e.g. status change).
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[MapsLocationEmbedPreview] Received embed data update for ${id}`);

    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }

    const content = data.decodedContent;
    if (content) {
      if (content.name !== undefined) localName = (content.name as string) || '';
      if (content.address !== undefined) localAddress = (content.address as string) || '';
      if (content.location_type !== undefined) localLocationType = (content.location_type as string) || 'area';
      if (content.place_type !== undefined) localPlaceType = (content.place_type as string) || '';
      if (content.map_image_url) {
        localMapImageUrl = content.map_image_url as string;
        imageError = false; // Reset error state on new image
      }
    }
  }

  // Skill name from translations
  let skillName = $derived($text('embeds.maps_location'));

  // Icon shown inline in the content area next to the place name.
  // Transit/transport types use the travel icon; everything else uses the maps/pin icon.
  const TRANSIT_TYPES = new Set(['railway', 'airport', 'subway', 's-bahn', 'tram', 'bus', 'ferry']);
  let isTransit = $derived(placeType ? TRANSIT_TYPES.has(placeType.toLowerCase()) : false);
  // skillIconName is still passed to the BasicInfosBar (always pin for location skill)
  const skillIconName = 'pin';

  // Whether we have a map image to display full-width
  let hasImage = $derived(!!mapImageUrl && !imageError && status !== 'error');

  // Show "Nearby:" label only in area/imprecise mode — the pin was randomised so the
  // address is approximate and we want to signal that to the user.
  let showNearbyLabel = $derived(locationType === 'area');

  // Primary display name (e.g. "Berlin Hauptbahnhof").
  // `name` may be a two-line string from legacy locationIndicatorText — take only the first line.
  let primaryName = $derived(name ? name.split('\n')[0].trim() : '');


</script>

<UnifiedEmbedPreview
  {id}
  appId="maps"
  skillId="location"
  skillIconName={skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  hasFullWidthImage={hasImage}
  showStatus={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    {#if hasImage}
      <!-- Full-width static map image preview -->
      <div class="map-image-wrapper">
        <img
          src={mapImageUrl}
          alt={name || $text('embeds.maps_location')}
          class="map-preview-image"
          class:mobile={isMobileLayout}
          loading="lazy"
        />
        {#if name}
          <div class="map-location-name-overlay" class:mobile={isMobileLayout}>
            {name}
          </div>
        {/if}
      </div>
    {:else}
      <!-- Fallback text layout when no image is available -->
      <!-- Layout: [icon] Place Name (bold)
                         Railway (muted type)
                         Europaplatz 1, 10557 Berlin (address) -->
      <div class="location-details" class:mobile={isMobileLayout}>
        {#if showNearbyLabel}
          <div class="location-nearby-label">{$text('embeds.maps_location.nearby')}</div>
        {/if}
        <!-- Name row: inline icon + bold place name -->
        <div class="location-name-row">
          <!-- Inline place-type icon (travel for transit, maps pin for others) -->
          <div class="location-type-icon" class:transit={isTransit}></div>
          {#if primaryName}
            <div class="location-name">{primaryName}</div>
          {:else if address}
            <!-- No name yet: show address as the primary line -->
            <div class="location-name location-name--address">{address}</div>
          {/if}
        </div>
        {#if placeType}
          <!-- Category/type label (e.g. "Railway", "Airport") — muted -->
          <div class="location-place-type">{placeType}</div>
        {/if}
        {#if primaryName && address}
          <!-- Street address below type — only when we also have a name -->
          <div class="location-address">{address}</div>
        {/if}
        {#if status === 'processing'}
          <div class="location-loading">{$text('embeds.maps_location.loading_map')}</div>
        {/if}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Map Image Preview (full-width)
     =========================================== */

  .map-image-wrapper {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }

  .map-preview-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  /* Location name overlay on top of map image */
  .map-location-name-overlay {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 8px 12px;
    background: linear-gradient(to top, rgba(0, 0, 0, 0.55) 0%, transparent 100%);
    color: #fff;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.3;
    /* Truncate long names */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .map-location-name-overlay.mobile {
    font-size: 12px;
    padding: 6px 10px;
  }

  /* ===========================================
     Text Fallback Layout (no image)
     =========================================== */

  .location-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
    justify-content: center;
    padding: 8px;
  }

  .location-details.mobile {
    justify-content: flex-start;
  }

  /* "Nearby:" prefix label — small, muted, indicates imprecise/area mode */
  .location-nearby-label {
    font-size: 11px;
    font-weight: 500;
    color: var(--color-grey-60);
    line-height: 1.2;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 2px;
  }

  /* Name row: flex container holding the inline icon + bold place name */
  .location-name-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }

  /* Inline place-type icon — same mask technique as the search results panel */
  .location-type-icon {
    flex-shrink: 0;
    width: 18px;
    height: 18px;
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    /* Default: maps pin icon */
    background: var(--color-app-maps, #4CAF50);
    -webkit-mask-image: url('@openmates/ui/static/icons/maps.svg');
    mask-image: url('@openmates/ui/static/icons/maps.svg');
  }

  /* Transit locations (Railway, Airport, etc.): travel icon */
  .location-type-icon.transit {
    background: var(--color-app-travel, #29B6F6);
    -webkit-mask-image: url('@openmates/ui/static/icons/travel.svg');
    mask-image: url('@openmates/ui/static/icons/travel.svg');
  }

  /* Primary place name — bold, shown above the street address */
  .location-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    word-break: break-word;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }

  /* When name falls back to address text, use normal weight */
  .location-name--address {
    font-weight: 400;
  }

  .location-details.mobile .location-name {
    font-size: 13px;
  }

  /* Category/type label (e.g. "Railway", "Airport") — muted, shown below the place name */
  .location-place-type {
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-60);
    line-height: 1.3;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .location-details.mobile .location-place-type {
    font-size: 11px;
  }

  /* Street address — muted text below the name, can be multi-line */
  .location-address {
    font-size: 13px;
    color: var(--color-grey-70);
    line-height: 1.4;
    word-break: break-word;
  }

  .location-details.mobile .location-address {
    font-size: 12px;
  }

  .location-loading {
    font-size: 13px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }

  /* Pin skill icon is registered directly in BasicInfosBar.svelte — no :global() override needed here. */
</style>
