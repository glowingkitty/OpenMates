<!--
  frontend/packages/ui/src/components/embeds/home/HomeListingEmbedPreview.svelte

  Child listing preview card for Home Search results.
  Uses UnifiedEmbedPreview as the base card (unified with all other embed previews).
  Renders listing image on the right side when available (matching WebsiteEmbedPreview pattern).

  Shows:
  - Price label (prominent)
  - Title (2 lines, truncated)
  - Address line
  - Metadata: size (m²) + rooms + move-in date
  - Provider badge overlaid on image
  - Listing image on right side (or placeholder)

  Clicking the card calls onSelect() to open the fullscreen listing view.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';

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
    /** Move-in date (DD.MM.YYYY, WG-Gesucht only) */
    available_from?: string;
    /** Click handler to open fullscreen view */
    onSelect: () => void;
    /** Whether to use mobile layout */
    isMobile?: boolean;
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
    listing_type: _listingType,
    available_from,
    onSelect,
    isMobile = false
  }: Props = $props();

  let imageError = $state(false);

  let proxiedImageUrl = $derived(
    image_url && !imageError
      ? proxyImage(image_url, MAX_WIDTH_PREVIEW_THUMBNAIL)
      : null
  );

  let sizeDisplay = $derived(
    size_sqm ? `${size_sqm} m\u00B2` : undefined
  );

  let roomsDisplay = $derived(
    rooms ? `${rooms} ${rooms === 1 ? 'room' : 'rooms'}` : undefined
  );

  let availableDisplay = $derived(
    available_from ? `from ${available_from}` : undefined
  );

  let metadataItems = $derived(
    [sizeDisplay, roomsDisplay, availableDisplay].filter(Boolean)
  );

  function handleStop() {
    // Listing cards are not cancellable
  }
</script>

<UnifiedEmbedPreview
  id={embed_id}
  appId="home"
  skillId="search"
  skillIconName="search"
  status="finished"
  skillName={title || 'Listing'}
  {isMobile}
  onFullscreen={onSelect}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={!!proxiedImageUrl && !title && !price_label}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="listing-details" class:mobile={isMobileLayout}>
      <div class="listing-content-row">
        <!-- Text content (left side) -->
        <div class="listing-text">
          {#if price_label}
            <div class="listing-price">{price_label}</div>
          {/if}

          {#if title}
            <div class="listing-title">{title}</div>
          {/if}

          {#if address}
            <div class="listing-address">{address}</div>
          {/if}

          {#if metadataItems.length > 0}
            <div class="listing-metadata">
              {metadataItems.join(' \u00B7 ')}
            </div>
          {/if}
        </div>

        <!-- Image (right side) -->
        {#if proxiedImageUrl && !isMobileLayout}
          <div class="listing-preview-image">
            {#if provider}
              <span class="provider-badge">{provider}</span>
            {/if}
            <img
              src={proxiedImageUrl}
              alt={title || 'Listing'}
              loading="lazy"
              crossorigin="anonymous"
              onerror={(e) => {
                imageError = true;
                handleImageError(e.currentTarget as HTMLImageElement);
              }}
            />
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .listing-details {
    display: flex;
    flex-direction: column;
    height: 100%;
    width: 100%;
    justify-content: center;
  }

  .listing-details.mobile {
    justify-content: flex-start;
  }

  .listing-content-row {
    display: flex;
    align-items: stretch;
    flex: 1;
    min-height: 0;
    height: 100%;
    width: 100%;
  }

  .listing-text {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 0 1 55%;
    min-width: 0;
    align-self: center;
    padding: 4px 0;
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
    word-break: break-word;
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
    margin-top: var(--spacing-1);
  }

  /* Image on right side */
  .listing-preview-image {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 171px;
    transform: translateX(20px);
  }

  .listing-preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }

  .provider-badge {
    position: absolute;
    top: 8px;
    right: 28px;
    padding: 3px 8px;
    border-radius: var(--radius-3);
    background-color: rgba(0, 0, 0, 0.6);
    color: var(--color-grey-0);
    font-size: 0.6875rem;
    font-weight: 500;
    white-space: nowrap;
    z-index: var(--z-index-raised);
  }
</style>
