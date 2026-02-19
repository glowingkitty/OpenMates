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
  let localMapImageUrl = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  let imageError = $state(false);

  // Sync local state from props on initial mount / prop changes
  $effect(() => {
    localName = nameProp ?? '';
    localAddress = addressProp ?? '';
    localLocationType = locationTypeProp ?? 'area';
    localMapImageUrl = mapImageUrlProp;
    localStatus = statusProp ?? 'processing';
    localTaskId = taskIdProp;
  });

  // Expose as derived read-only aliases for clarity
  let name = $derived(localName);
  let address = $derived(localAddress);
  let locationType = $derived(localLocationType);
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

  // Show "Nearby:" label only in area/imprecise mode — the pin was randomised so the
  // address is approximate and we want to signal that to the user.
  let showNearbyLabel = $derived(locationType === 'area');

  // Secondary line: the resolved street address (shown when no map image is available).
  let secondaryText = $derived(address || '');

  // Primary display name for the text fallback layout.
  // `name` may be a two-line string like "Berlin Hauptbahnhof\nBerlin" (from locationIndicatorText).
  // Take only the first line as the prominent place name to avoid duplication with secondaryText.
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
      <!-- Shows the place name prominently (e.g. "Berlin Hauptbahnhof") followed by the
           street address. For area/imprecise mode we prefix with a small "Nearby:" label. -->
      <div class="location-details" class:mobile={isMobileLayout}>
        {#if showNearbyLabel}
          <!-- Small "Nearby:" label shown when the user had imprecise/privacy mode on -->
          <div class="location-nearby-label">{$text('embeds.maps_location.nearby')}</div>
        {/if}
        {#if primaryName}
          <!-- Primary place name (station, POI, or location title) in bold -->
          <div class="location-name">{primaryName}</div>
        {/if}
        {#if secondaryText}
          <!-- Full street address in muted text below the name (multi-line) -->
          <div class="location-address">{secondaryText}</div>
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
  }

  .location-details.mobile .location-name {
    font-size: 13px;
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
