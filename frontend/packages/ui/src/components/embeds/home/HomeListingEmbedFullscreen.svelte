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
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';

  /**
   * Props for listing fullscreen view.
   */
  interface Props {
    /** Direct link to listing on platform */
    url: string;
    /** Listing title */
    title?: string;
    /** Human-readable price (e.g. "850 EUR/month") */
    price_label?: string;
    /** Living area in square meters */
    size_sqm?: number;
    /** Number of rooms */
    rooms?: number;
    /** Address (city + district/street) */
    address?: string;
    /** First listing image URL */
    image_url?: string;
    /** Provider name (ImmoScout24, Kleinanzeigen, WG-Gesucht) */
    provider?: string;
    /** Listing type (rent or buy) */
    listing_type?: string;
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
    url,
    title,
    price_label,
    size_sqm,
    rooms,
    address,
    image_url,
    provider,
    listing_type,
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
    <button class="cta-button" onclick={handleOpenOnPlatform}>
      Open on {hostname}
    </button>
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

  /* CTA Button */
  .cta-button {
    background-color: var(--color-button-primary);
    color: white;
    border: none;
    border-radius: 15px;
    padding: 12px 24px;
    font-family: 'Lexend Deca', sans-serif;
    font-size: 1rem;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.15s;
    min-width: 200px;
  }

  .cta-button:hover {
    background-color: var(--color-button-primary-hover);
    transform: translateY(-1px);
  }

  .cta-button:active {
    background-color: var(--color-button-primary-pressed);
    transform: translateY(0);
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

    .cta-button {
      padding: 10px 20px;
      min-width: 160px;
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
