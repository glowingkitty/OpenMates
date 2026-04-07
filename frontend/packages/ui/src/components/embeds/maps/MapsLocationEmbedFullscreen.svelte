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
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    /** Raw embed data containing decodedContent and attrs */
    data: EmbedFullscreenRawData;
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
    data,
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

  // Extract fields from data.decodedContent with attrs fallback
  let dc = $derived(data.decodedContent);
  let attrs = $derived(data.attrs ?? {});
  let lat = $derived(typeof dc.lat === 'number' ? dc.lat : (typeof attrs.lat === 'number' ? attrs.lat : undefined));
  let lon = $derived(typeof dc.lon === 'number' ? dc.lon : (typeof attrs.lon === 'number' ? attrs.lon : undefined));
  let zoom = $derived(typeof dc.zoom === 'number' ? dc.zoom : 15);
  let name = $derived(typeof dc.name === 'string' ? dc.name : undefined);
  let address = $derived(typeof dc.address === 'string' ? dc.address : undefined);
  let locationType = $derived(typeof dc.location_type === 'string' ? dc.location_type : undefined);
  let mapImageUrl = $derived(typeof dc.map_image_url === 'string' ? dc.map_image_url : undefined);

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
  embedHeaderTitle={$text('common.location')}
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
  {#snippet detailContent(_ctx)}
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

  {#snippet embedHeaderCta()}
    {#if googleMapsUrl}
      <EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', 'Google Maps')} onclick={handleOpenInGoogleMaps} />
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
  .location-title {
    font-size: var(--font-size-h2-mobile);
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }

  .location-address-row {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
  }

  .nearby-label {
    font-size: var(--font-size-tiny);
    font-weight: 600;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .location-address {
    font-size: null;
    color: var(--color-font-primary);
    line-height: 1.5;
    margin: 0;
    word-break: break-word;
  }


</style>
