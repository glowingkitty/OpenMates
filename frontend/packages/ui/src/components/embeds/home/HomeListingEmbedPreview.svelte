<!--
  frontend/packages/ui/src/components/embeds/home/HomeListingEmbedPreview.svelte

  Child listing preview card for Home Search results.
  Renders as a compact card in the SearchResultsTemplate grid.

  Shows:
  - Listing image (top, with fallback placeholder)
  - Title (1-2 lines, truncated)
  - Price label (prominent, colored)
  - Address line
  - Metadata: size (m2) + rooms + provider badge

  Clicking the card calls onSelect() to open the fullscreen listing view.
-->

<script lang="ts">
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';

  /**
   * Props for a single listing preview card.
   */
  interface Props {
    /** Child embed ID */
    embed_id: string;
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
    /** Direct link to listing on platform */
    url?: string;
    /** Provider name (ImmoScout24, Kleinanzeigen, WG-Gesucht) */
    provider?: string;
    /** Listing type (rent or buy) */
    listing_type?: string;
    /** Click handler to open fullscreen view */
    onSelect: () => void;
  }

  let {
    embed_id,
    title,
    price_label,
    size_sqm,
    rooms,
    address,
    image_url,
    provider,
    listing_type,
    onSelect
  }: Props = $props();

  let imageError = $state(false);

  /** Proxied image URL for the listing photo */
  let proxiedImageUrl = $derived(
    image_url && !imageError
      ? proxyImage(image_url, MAX_WIDTH_PREVIEW_THUMBNAIL)
      : null
  );

  /** Format size with unit */
  let sizeDisplay = $derived(
    size_sqm ? `${size_sqm} m\u00B2` : undefined
  );

  /** Format rooms count */
  let roomsDisplay = $derived(
    rooms ? `${rooms} ${rooms === 1 ? 'room' : 'rooms'}` : undefined
  );

  /** Build metadata line from available fields */
  let metadataItems = $derived(
    [sizeDisplay, roomsDisplay].filter(Boolean)
  );
</script>

<button
  class="listing-card"
  onclick={onSelect}
  type="button"
>
  <!-- Image area -->
  <div class="listing-image-container">
    {#if proxiedImageUrl}
      <img
        src={proxiedImageUrl}
        alt={title || 'Listing'}
        class="listing-image"
        loading="lazy"
        crossorigin="anonymous"
        onerror={(e) => {
          imageError = true;
          handleImageError(e.currentTarget as HTMLImageElement);
        }}
      />
    {:else}
      <div class="listing-image-placeholder">
        <div class="placeholder-icon clickable-icon icon_home"></div>
      </div>
    {/if}

    <!-- Provider badge overlay -->
    {#if provider}
      <span class="provider-badge">{provider}</span>
    {/if}
  </div>

  <!-- Content area -->
  <div class="listing-content">
    <!-- Price (prominent) -->
    {#if price_label}
      <div class="listing-price">{price_label}</div>
    {/if}

    <!-- Title -->
    {#if title}
      <div class="listing-title">{title}</div>
    {/if}

    <!-- Address -->
    {#if address}
      <div class="listing-address">{address}</div>
    {/if}

    <!-- Metadata line: size + rooms -->
    {#if metadataItems.length > 0}
      <div class="listing-metadata">
        {metadataItems.join(' \u00B7 ')}
      </div>
    {/if}
  </div>
</button>

<style>
  .listing-card {
    display: flex;
    flex-direction: column;
    border-radius: 16px;
    overflow: hidden;
    background-color: var(--color-grey-0);
    cursor: pointer;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    border: none;
    padding: 0;
    text-align: left;
    width: 100%;
    font-family: 'Lexend Deca', sans-serif;
  }

  .listing-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  }

  .listing-card:active {
    transform: translateY(0);
  }

  /* Image area */
  .listing-image-container {
    position: relative;
    width: 100%;
    height: 160px;
    overflow: hidden;
    background-color: var(--color-grey-20);
  }

  .listing-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .listing-image-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: var(--color-grey-20);
  }

  .placeholder-icon {
    width: 40px;
    height: 40px;
    opacity: 0.3;
  }

  /* Provider badge in top-right corner of image */
  .provider-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    padding: 3px 8px;
    border-radius: 8px;
    background-color: rgba(0, 0, 0, 0.6);
    color: var(--color-grey-0);
    font-size: 0.6875rem;
    font-weight: 500;
    white-space: nowrap;
  }

  /* Content area */
  .listing-content {
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .listing-price {
    font-size: 1rem;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.3;
  }

  .listing-title {
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .listing-address {
    font-size: 0.8125rem;
    color: var(--color-grey-70);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .listing-metadata {
    font-size: 0.75rem;
    color: var(--color-grey-60);
    line-height: 1.3;
    margin-top: 2px;
  }
</style>
