<!--
  frontend/packages/ui/src/components/embeds/home/HomeListingEmbedFullscreen.svelte

  Fullscreen view for a single Home listing embed (child of search results).
  Uses EntryWithMapTemplate for responsive map + detail card layout — same
  pattern as EventEmbedFullscreen and HealthAppointmentEmbedFullscreen.

  Shows an interactive map when the listing has latitude/longitude coordinates
  (geocoded by the backend search skill). Falls back to details-only layout
  when no coordinates are available.

  Layout:
  - Map background with detail card overlay (wide) or stacked (narrow)
  - Listing photo, price, address
  - Metadata: size, rooms, listing type, provider, available from, deposit
  - "Open on {provider}" CTA button
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  /**
   * Props for listing fullscreen view.
   * Receives raw embed data via `data` prop and extracts fields internally.
   */
  interface Props {
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    /** Close handler */
    onClose: () => void;
    /** Embed ID for sharing */
    embedId?: string;
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
    /** Whether to show the chat button (ultra-wide mode) */
    showChatButton?: boolean;
    /** Callback for chat button */
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

  /** Parse a number from unknown value (handles TOON string→number edge cases). */
  function asNumber(v: unknown): number | undefined {
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string') { const n = Number(v); if (Number.isFinite(n)) return n; }
    return undefined;
  }

  // Extract fields from data.decodedContent.
  // Must be $derived so it updates when navigating between results (prev/next).
  // Handles both direct fields and flat TOON format from _flatten_for_toon_tabular.
  let dc = $derived(data.decodedContent);
  let url = $derived(typeof dc.url === 'string' ? dc.url : '');
  let title = $derived(typeof dc.title === 'string' ? dc.title : undefined);
  let price_label = $derived(typeof dc.price_label === 'string' ? dc.price_label : undefined);
  let size_sqm = $derived(asNumber(dc.size_sqm));
  let rooms = $derived(asNumber(dc.rooms));
  let address = $derived(typeof dc.address === 'string' ? dc.address : undefined);
  let image_url = $derived(typeof dc.image_url === 'string' ? dc.image_url : undefined);
  let provider = $derived(typeof dc.provider === 'string' ? dc.provider : undefined);
  let listing_type = $derived(typeof dc.listing_type === 'string' ? dc.listing_type : undefined);
  let available_from = $derived(typeof dc.available_from === 'string' ? dc.available_from : undefined);
  let deposit = $derived(asNumber(dc.deposit));
  let furnished = $derived(typeof dc.furnished === 'boolean' ? dc.furnished : undefined);
  let latitude = $derived(asNumber(dc.latitude));
  let longitude = $derived(asNumber(dc.longitude));

  let imageError = $state(false);

  let displayTitle = $derived(title || 'Listing');

  /** Proxied header image URL */
  let headerImageUrl = $derived(
    image_url && !imageError
      ? proxyImage(image_url, MAX_WIDTH_HEADER_IMAGE)
      : null
  );

  /** Extract hostname for CTA button label */
  let hostname = $derived.by(() => {
    try {
      return new URL(url).hostname.replace('www.', '');
    } catch {
      return provider || 'listing';
    }
  });

  // Map data — only when listing has geocoded coordinates
  let mapCenter = $derived(
    latitude != null && longitude != null
      ? { lat: latitude, lon: longitude }
      : undefined
  );

  let mapMarkers = $derived(
    mapCenter
      ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: title || address }]
      : []
  );

  /** Format size with unit */
  let sizeDisplay = $derived(
    size_sqm ? `${size_sqm} m\u00B2` : undefined
  );

  /** Format rooms count */
  let roomsDisplay = $derived(
    rooms ? `${rooms} ${rooms === 1 ? 'room' : 'rooms'}` : undefined
  );

  /** Capitalize listing type */
  let typeDisplay = $derived(
    listing_type ? listing_type.charAt(0).toUpperCase() + listing_type.slice(1) : undefined
  );

  /** Format deposit with currency */
  let depositDisplay = $derived(
    deposit ? `${deposit.toLocaleString('de-DE')} EUR` : undefined
  );

  /** Furnished display */
  let furnishedDisplay = $derived(
    furnished !== undefined ? (furnished ? 'Yes' : 'No') : undefined
  );

  /** Open listing on original platform */
  function handleOpenOnPlatform() {
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }
</script>

<EntryWithMapTemplate
  appId="home"
  skillId="listing"
  embedHeaderTitle={displayTitle}
  embedHeaderSubtitle={price_label}
  skillIconName="home"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  {mapCenter}
  mapZoom={14}
  {mapMarkers}
>
  {#snippet embedHeaderCta()}
    <EmbedHeaderCtaButton label="Open on {hostname}" onclick={handleOpenOnPlatform} />
  {/snippet}

  {#snippet detailContent(_ctx)}
    <!-- Header Image -->
    {#if headerImageUrl}
      <img
        src={headerImageUrl}
        alt={displayTitle}
        class="listing-image"
        loading="lazy"
        crossorigin="anonymous"
        onerror={(e) => { imageError = true; handleImageError(e.currentTarget as HTMLImageElement); }}
      />
    {/if}

    <!-- Address -->
    {#if address}
      <div class="listing-section">
        <div class="section-label">Location</div>
        <div class="section-value">{address}</div>
      </div>
    {/if}

    <!-- Key details row: size, rooms, type -->
    <div class="listing-meta-row">
      {#if sizeDisplay}
        <span class="listing-meta-badge">{sizeDisplay}</span>
      {/if}
      {#if roomsDisplay}
        <span class="listing-meta-badge">{roomsDisplay}</span>
      {/if}
      {#if typeDisplay}
        <span class="listing-type-badge">{typeDisplay}</span>
      {/if}
      {#if provider}
        <span class="listing-source-badge">{provider}</span>
      {/if}
    </div>

    <!-- Additional details -->
    {#if available_from}
      <div class="listing-section">
        <div class="section-label">Available From</div>
        <div class="section-value">{available_from}</div>
      </div>
    {/if}

    {#if depositDisplay}
      <div class="listing-section">
        <div class="section-label">Deposit</div>
        <div class="section-value">{depositDisplay}</div>
      </div>
    {/if}

    {#if furnishedDisplay}
      <div class="listing-section">
        <div class="section-label">Furnished</div>
        <div class="section-value">{furnishedDisplay}</div>
      </div>
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
  .listing-image {
    width: 100%;
    height: 190px;
    object-fit: cover;
    border-radius: 12px;
  }

  .listing-meta-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  .listing-meta-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .listing-type-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: var(--color-app-home-start, #6b4c9a);
    color: #fff; /* intentional: always white on brand colour */
  }

  .listing-source-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 500;
    background: var(--color-grey-15);
    color: var(--color-font-secondary);
    border: 1px solid var(--color-grey-25);
  }

  .listing-section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .section-label {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-grey-60);
  }

  .section-value {
    font-size: 0.9375rem;
    color: var(--color-font-primary);
    line-height: 1.5;
  }
</style>
