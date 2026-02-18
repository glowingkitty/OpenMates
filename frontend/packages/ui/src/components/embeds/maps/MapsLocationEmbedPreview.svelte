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
    /** Latitude of the location */
    lat?: number;
    /** Longitude of the location */
    lon?: number;
    /** Display name for the location */
    name?: string;
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
    lat: latProp,
    lon: lonProp,
    name: nameProp,
    mapImageUrl: mapImageUrlProp,
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state — updated by embed data events via onEmbedDataUpdated
  let localLat = $state<number | undefined>(undefined);
  let localLon = $state<number | undefined>(undefined);
  let localName = $state<string>('');
  let localMapImageUrl = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  let imageError = $state(false);

  // Sync local state from props on initial mount / prop changes
  $effect(() => {
    localLat = latProp;
    localLon = lonProp;
    localName = nameProp ?? '';
    localMapImageUrl = mapImageUrlProp;
    localStatus = statusProp ?? 'processing';
    localTaskId = taskIdProp;
  });

  // Expose as derived read-only aliases for clarity
  let lat = $derived(localLat);
  let lon = $derived(localLon);
  let name = $derived(localName);
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
      if (content.lat !== undefined) localLat = content.lat as number;
      if (content.lon !== undefined) localLon = content.lon as number;
      if (content.name !== undefined) localName = (content.name as string) || '';
      if (content.map_image_url) {
        localMapImageUrl = content.map_image_url as string;
        imageError = false; // Reset error state on new image
      }
    }
  }

  // Skill name from translations
  let skillName = $derived($text('embeds.maps_location'));

  // The skill icon uses the pin icon (location.svg does not exist)
  const skillIconName = 'pin';

  // Whether we have a map image to display full-width
  let hasImage = $derived(!!mapImageUrl && !imageError && status !== 'error');

  // Formatted coordinates for display when no image is available
  let coordsText = $derived(
    lat !== undefined && lon !== undefined
      ? `${lat.toFixed(6)}, ${lon.toFixed(6)}`
      : ''
  );
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
      <div class="location-details" class:mobile={isMobileLayout}>
        {#if name}
          <div class="location-name">{name}</div>
        {:else}
          <div class="location-name">{$text('embeds.maps_location')}</div>
        {/if}
        {#if coordsText}
          <div class="location-coords">{coordsText}</div>
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

  .location-name {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .location-details.mobile .location-name {
    font-size: 14px;
  }

  .location-coords {
    font-size: 12px;
    color: var(--color-grey-60);
    font-family: monospace;
    line-height: 1.3;
  }

  .location-loading {
    font-size: 13px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }

  /* ===========================================
     Skill Icon (location pin)
     =========================================== */

  :global(.unified-embed-preview .skill-icon[data-skill-icon="pin"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="pin"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
  }
</style>
