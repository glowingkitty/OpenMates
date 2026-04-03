<!--
  frontend/packages/ui/src/components/embeds/home/HomeListingEmbedFullscreen.svelte

  Fullscreen view for a single Home listing embed (child of search results).
  Uses UnifiedEmbedFullscreen as base and provides listing-specific content.

  Layout:
  - Large header image (listing photo)
  - Title + price (prominent)
  - Address
  - Metadata grid: size, rooms, listing type, provider
  - "Open on {provider}" CTA button

  Bottom bar shows home gradient icon + truncated title.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
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

  // Extract fields from data.decodedContent
  let dc = $derived(data.decodedContent);
  let url = $derived(typeof dc.url === 'string' ? dc.url : '');
  let title = $derived(typeof dc.title === 'string' ? dc.title : undefined);
  let price_label = $derived(typeof dc.price_label === 'string' ? dc.price_label : undefined);
  let size_sqm = $derived(typeof dc.size_sqm === 'number' ? dc.size_sqm : undefined);
  let rooms = $derived(typeof dc.rooms === 'number' ? dc.rooms : undefined);
  let address = $derived(typeof dc.address === 'string' ? dc.address : undefined);
  let image_url = $derived(typeof dc.image_url === 'string' ? dc.image_url : undefined);
  let provider = $derived(typeof dc.provider === 'string' ? dc.provider : undefined);
  let listing_type = $derived(typeof dc.listing_type === 'string' ? dc.listing_type : undefined);
  let available_from = $derived(typeof dc.available_from === 'string' ? dc.available_from : undefined);
  let deposit = $derived(typeof dc.deposit === 'number' ? dc.deposit : undefined);
  let furnished = $derived(typeof dc.furnished === 'boolean' ? dc.furnished : undefined);

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

<UnifiedEmbedFullscreen
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
>
  {#snippet embedHeaderCta()}
    <EmbedHeaderCtaButton label="Open on {hostname}" onclick={handleOpenOnPlatform} />
  {/snippet}

  <!-- eslint-disable-next-line @typescript-eslint/no-unused-vars -->
  {#snippet content(_)}
    <div class="listing-fullscreen-content">
      <!-- Header Image -->
      {#if headerImageUrl}
        <div class="header-image-container">
          <img
            src={headerImageUrl}
            alt={displayTitle}
            class="header-image"
            loading="lazy"
            crossorigin="anonymous"
            onerror={(e) => { imageError = true; handleImageError(e.currentTarget as HTMLImageElement); }}
          />
        </div>
      {/if}

      <!-- Address -->
      {#if address}
        <p class="listing-address">{address}</p>
      {/if}

      <!-- Metadata Grid -->
      <div class="metadata-grid">
        {#if sizeDisplay}
          <div class="metadata-item">
            <span class="metadata-label">Size</span>
            <span class="metadata-value">{sizeDisplay}</span>
          </div>
        {/if}

        {#if roomsDisplay}
          <div class="metadata-item">
            <span class="metadata-label">Rooms</span>
            <span class="metadata-value">{roomsDisplay}</span>
          </div>
        {/if}

        {#if typeDisplay}
          <div class="metadata-item">
            <span class="metadata-label">Type</span>
            <span class="metadata-value">{typeDisplay}</span>
          </div>
        {/if}

        {#if provider}
          <div class="metadata-item">
            <span class="metadata-label">Source</span>
            <span class="metadata-value">{provider}</span>
          </div>
        {/if}

        {#if available_from}
          <div class="metadata-item">
            <span class="metadata-label">Available</span>
            <span class="metadata-value">{available_from}</span>
          </div>
        {/if}

        {#if depositDisplay}
          <div class="metadata-item">
            <span class="metadata-label">Deposit</span>
            <span class="metadata-value">{depositDisplay}</span>
          </div>
        {/if}

        {#if furnishedDisplay}
          <div class="metadata-item">
            <span class="metadata-label">Furnished</span>
            <span class="metadata-value">{furnishedDisplay}</span>
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .listing-fullscreen-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px 40px 40px;
    max-width: 600px;
    margin: 0 auto;
    width: 100%;
    box-sizing: border-box;
  }

  /* Header Image */
  .header-image-container {
    width: 100%;
    max-width: 511px;
    border-radius: 30px;
    overflow: hidden;
    margin-bottom: 24px;
    background-color: var(--color-grey-30);
  }

  .header-image {
    width: 100%;
    height: auto;
    min-height: 168px;
    max-height: 300px;
    display: block;
    object-fit: cover;
  }

  /* Address */
  .listing-address {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 1rem;
    font-weight: 500;
    color: var(--color-grey-70);
    line-height: 1.5;
    width: 100%;
    max-width: 500px;
    margin: 0 0 24px 0;
    word-break: break-word;
  }

  /* Metadata Grid */
  .metadata-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    width: 100%;
    max-width: 500px;
  }

  .metadata-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 16px;
    background-color: var(--color-grey-0);
    border-radius: 16px;
  }

  .metadata-label {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--color-grey-60);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .metadata-value {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 1rem;
    font-weight: 600;
    color: var(--color-grey-100);
  }

  /* Responsive */
  @container fullscreen (max-width: 600px) {
    .listing-fullscreen-content {
      padding: 20px 20px 30px;
    }

    .header-image-container {
      border-radius: 20px;
    }

    .metadata-grid {
      gap: 10px;
    }

    .metadata-item {
      padding: 12px;
      border-radius: 12px;
    }
  }

  @container fullscreen (max-width: 400px) {
    .listing-fullscreen-content {
      padding: 16px 16px 24px;
    }

    .header-image {
      min-height: 120px;
      max-height: 200px;
    }

    .metadata-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
