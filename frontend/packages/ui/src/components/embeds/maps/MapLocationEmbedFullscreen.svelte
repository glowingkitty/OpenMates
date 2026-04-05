<!--
  frontend/packages/ui/src/components/embeds/maps/MapLocationEmbedFullscreen.svelte

  Fullscreen view for a single maps-place result (child embed of a Maps Search).
  Based on EntryWithMapTemplate — shows interactive map background with a
  detail card on the left (wide viewports) or stacked below map (narrow).

  Displays:
  - Interactive OpenStreetMap map centered on the place
  - Place name prominently
  - Rating with star + review count
  - Formatted address
  - Website link (if available)
  - "Open in Google Maps" CTA button

  This component is opened from the list in MapsSearchEmbedFullscreen when
  a MapLocationEmbedPreview card is clicked.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    /** Embed ID for sharing */
    embedId?: string;
    /** Close handler */
    onClose: () => void;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Direction of navigation */
    navigateDirection?: 'previous' | 'next';
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  // Extract fields from data.decodedContent
  let dc = $derived(data.decodedContent);
  let rawLocation = $derived(dc.location as Record<string, unknown> | undefined);
  let displayName = $derived(typeof dc.displayName === 'string' ? dc.displayName : (typeof dc.name === 'string' ? dc.name : undefined));
  let formattedAddress = $derived(typeof dc.formattedAddress === 'string' ? dc.formattedAddress : (typeof dc.formatted_address === 'string' ? dc.formatted_address : undefined));
  let lat = $derived((rawLocation && typeof rawLocation.latitude === 'number') ? rawLocation.latitude : (typeof dc.lat === 'number' ? dc.lat : undefined));
  let lon = $derived((rawLocation && typeof rawLocation.longitude === 'number') ? rawLocation.longitude : (typeof dc.lon === 'number' ? dc.lon : undefined));
  let zoom = $derived(typeof dc.zoom === 'number' ? dc.zoom : 15);
  let rating = $derived(typeof dc.rating === 'number' ? dc.rating : undefined);
  let userRatingCount = $derived(typeof dc.userRatingCount === 'number' ? dc.userRatingCount : undefined);
  let placeType = $derived(typeof dc.place_type === 'string' ? dc.place_type : undefined);
  let imageUrl = $derived(typeof dc.imageUrl === 'string' ? dc.imageUrl : undefined);
  let websiteUri = $derived(typeof dc.websiteUri === 'string' ? dc.websiteUri : undefined);
  let placeId = $derived(typeof dc.placeId === 'string' ? dc.placeId : undefined);

  let showShare = $derived(!!embedId);

  let googleMapsUrl = $derived.by(() => {
    if (placeId) {
      return `https://www.google.com/maps/place/?q=place_id:${placeId}`;
    }
    if (lat !== undefined && lon !== undefined) {
      return `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
    }
    if (formattedAddress) {
      return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(formattedAddress)}`;
    }
    return null;
  });

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
    mapCenter ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: displayName }] : []
  );

  let ratingText = $derived(
    rating != null ? rating.toFixed(1) : null
  );

  let proxiedImageUrl = $derived(
    imageUrl ? proxyImage(imageUrl, MAX_WIDTH_HEADER_IMAGE) : ''
  );

  function handleOpenInGoogleMaps() {
    if (googleMapsUrl) window.open(googleMapsUrl, '_blank', 'noopener,noreferrer');
  }

  function handleOpenWebsite() {
    if (websiteUri) window.open(websiteUri, '_blank', 'noopener,noreferrer');
  }

  async function handleCopyOsmUrl() {
    if (!osmUrl) return;
    try {
      const clipResult = await copyToClipboard(osmUrl);
      if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      notificationStore.success($text('embeds.copied_to_clipboard'), 3000);
    } catch (err) {
      console.error('[MapLocationEmbedFullscreen] Failed to copy OSM URL:', err);
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
  embedHeaderTitle={displayName || $text('common.location')}
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
>
  {#snippet detailContent(_ctx)}
    {#if proxiedImageUrl}
      <img class="place-image" src={proxiedImageUrl} alt={displayName || $text('common.location')} loading="lazy" />
    {/if}

    {#if displayName}
      <h2 class="place-title">{displayName}</h2>
    {/if}

    {#if ratingText != null}
      <div class="place-rating">
        <span class="rating-star">★</span>
        <span class="rating-value">{ratingText}</span>
        {#if userRatingCount != null}
          <span class="rating-count">
            {userRatingCount.toLocaleString()} {$text('embeds.reviews')}
          </span>
        {/if}
      </div>
    {/if}

    {#if placeType}
      <div class="place-type">{placeType}</div>
    {/if}

    {#if formattedAddress}
      <p class="place-address">{formattedAddress}</p>
    {/if}

    {#if websiteUri}
      <button class="website-link" onclick={handleOpenWebsite}>
        {websiteUri.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}
      </button>
    {/if}
  {/snippet}

  {#snippet embedHeaderCta()}
    {#if googleMapsUrl}
      <EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', 'Google Maps')} onclick={handleOpenInGoogleMaps} />
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
  .place-image {
    width: 100%;
    height: 160px;
    object-fit: cover;
    border-radius: var(--radius-5);
  }

  .place-title {
    font-size: 1.5rem; /* 24px */
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }

  .place-rating {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 0.9375rem; /* 15px */
    line-height: 1.3;
  }

  .rating-star {
    color: #f5a623; /* intentional: brand star color, same as MapLocationEmbedPreview */
    font-size: 1rem;
  }

  .rating-value {
    font-weight: 700;
    color: var(--color-font-primary);
  }

  .rating-count {
    color: var(--color-font-secondary);
    font-size: 0.875rem; /* 14px */
  }

  .place-type {
    font-size: 0.8125rem; /* 13px */
    font-weight: 500;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    line-height: 1.2;
  }

  .place-address {
    font-size: 0.9375rem; /* 15px */
    color: var(--color-font-primary);
    line-height: 1.5;
    margin: 0;
    word-break: break-word;
  }

  .website-link {
    background: none;
    border: none;
    padding: 0;
    font-size: 0.875rem; /* 14px */
    color: var(--color-primary);
    text-decoration: underline;
    cursor: pointer;
    text-align: left;
    word-break: break-all;
    line-height: 1.4;
  }

  .website-link:hover {
    opacity: 0.8;
  }


</style>
