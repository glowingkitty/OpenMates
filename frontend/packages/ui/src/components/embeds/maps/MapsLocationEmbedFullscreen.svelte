<!--
  frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedFullscreen.svelte

  Fullscreen view for Maps Location skill embeds.
  Uses EntryWithMapTemplate for responsive map + detail card layout.

  Shows:
  - Interactive OpenStreetMap map centered on the pin (or static map image)
  - Location name prominently displayed
  - Human-readable address with optional "Nearby:" prefix for area mode
  - "Open in Google Maps" CTA button

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { copyToClipboard } from '../../../utils/clipboardUtils';

  interface Props {
    lat?: number;
    lon?: number;
    zoom?: number;
    name?: string;
    address?: string;
    locationType?: string;
    mapImageUrl?: string;
    status?: 'processing' | 'finished' | 'error';
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
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
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  let showNearbyLabel = $derived(locationType === 'area');
  let showShare = $derived(!!embedId);

  let googleMapsUrl = $derived(
    lat !== undefined && lon !== undefined
      ? `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`
      : null
  );

  let osmUrl = $derived(
    lat !== undefined && lon !== undefined
      ? `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}&zoom=${zoom}`
      : null
  );

  let mapCenter = $derived(
    lat !== undefined && lon !== undefined
      ? { lat, lon }
      : undefined
  );

  let mapMarkers = $derived(
    mapCenter ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: name }] : []
  );

  function handleOpenInGoogleMaps() {
    if (googleMapsUrl) {
      window.open(googleMapsUrl, '_blank', 'noopener,noreferrer');
    }
  }

  async function handleCopyOsmUrl() {
    if (!osmUrl) return;
    try {
      const clipResult = await copyToClipboard(osmUrl);
      if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      notificationStore.success($text('embeds.copied_to_clipboard'), 3000);
    } catch (err) {
      console.error('[MapsLocationEmbedFullscreen] Failed to copy OSM URL:', err);
      notificationStore.error($text('embeds.copy_failed'), 4000);
    }
  }
</script>

<EntryWithMapTemplate
  appId="maps"
  skillId="location"
  {onClose}
  currentEmbedId={embedId}
  skillIconName="pin"
  embedHeaderTitle={$text('embeds.maps_location')}
  {showShare}
  onCopy={osmUrl ? handleCopyOsmUrl : undefined}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  {mapCenter}
  mapZoom={zoom}
  {mapMarkers}
  staticMapImageUrl={mapImageUrl}
>
  {#snippet detailContent()}
    {#if name}
      <h2 class="location-title">{name}</h2>
    {/if}

    {#if address}
      <div class="location-address-row">
        {#if showNearbyLabel}
          <span class="nearby-label">{$text('embeds.maps_location.nearby')}</span>
        {/if}
        <p class="location-address">{address}</p>
      </div>
    {/if}
  {/snippet}

  {#snippet ctaContent()}
    {#if googleMapsUrl}
      <button class="open-maps-button" onclick={handleOpenInGoogleMaps}>
        {$text('embeds.maps_location.open_in_google_maps')}
      </button>
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
  .location-title {
    font-size: 24px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }

  .location-address-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

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

  .open-maps-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
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
  }

  .open-maps-button:hover {
    opacity: 0.9;
  }

  .open-maps-button:active {
    opacity: 0.8;
    transform: scale(0.98);
  }
</style>
