<!--
  frontend/packages/ui/src/components/embeds/maps/MapLocationEmbedPreview.svelte

  Preview card for a single maps-place result shown inside MapsSearchEmbedFullscreen's
  result list. Based on UnifiedEmbedPreview.

  Displays:
  - Place name (bold)
  - Rating with star and review count
  - Formatted address (muted)
  - Category/type badge if available

  This component is rendered inside MapsSearchEmbedFullscreen's left-panel list.
  Clicking it opens MapLocationEmbedFullscreen (via onFullscreen callback).

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

  /**
   * Props for a single place result preview card.
   * Data comes from the parent search fullscreen which passes
   * individual place result fields directly.
   */
  interface Props {
    /** Synthetic embed ID for this place card */
    id: string;
    /** Place display name */
    displayName?: string;
    /** Formatted address */
    formattedAddress?: string;
    /** Rating (0–5) */
    rating?: number;
    /** Number of user ratings */
    userRatingCount?: number;
    /** Place category/type (e.g. "Coffee Shop") */
    placeType?: string;
    /** Place photo URL (Google Places photo/media URL) */
    imageUrl?: string;
    /** Whether this is the currently selected/highlighted place */
    isSelected?: boolean;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler to open fullscreen location details */
    onFullscreen: () => void;
  }

  let {
    id,
    displayName,
    formattedAddress,
    rating,
    userRatingCount,
    placeType,
    imageUrl,
    isSelected = false,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let skillName = $derived($text('embeds.maps_location'));

  /** Format rating to 1 decimal, capped to avoid floating point noise */
  let ratingText = $derived(
    rating != null ? rating.toFixed(1) : null
  );

  let proxiedImageUrl = $derived(
    imageUrl ? proxyImage(imageUrl, MAX_WIDTH_PREVIEW_THUMBNAIL) : ''
  );
</script>

<UnifiedEmbedPreview
  {id}
  appId="maps"
  skillId="location"
  skillIconName="pin"
  {status}
  {skillName}
  {isMobile}
  {onFullscreen}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="place-card" class:mobile={isMobileLayout} class:selected={isSelected}>
      {#if proxiedImageUrl}
        <img class="place-image" src={proxiedImageUrl} alt={displayName || $text('embeds.maps_location')} loading="lazy" />
      {/if}

      <!-- Place name -->
      <div class="place-name">{displayName || $text('embeds.maps_location')}</div>

      <!-- Rating row -->
      {#if ratingText != null}
        <div class="place-rating">
          <span class="rating-star">★</span>
          <span class="rating-value">{ratingText}</span>
          {#if userRatingCount != null}
            <span class="rating-count">({userRatingCount.toLocaleString()})</span>
          {/if}
        </div>
      {/if}

      <!-- Type badge -->
      {#if placeType}
        <div class="place-type">{placeType}</div>
      {/if}

      <!-- Address -->
      {#if formattedAddress}
        <div class="place-address">{formattedAddress}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .place-card {
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 12px 16px 8px;
    height: 100%;
    justify-content: center;
  }

  .place-image {
    width: 100%;
    height: 72px;
    object-fit: cover;
    border-radius: 10px;
    margin-bottom: 4px;
  }

  .place-card.mobile {
    padding: 8px 10px 6px;
    justify-content: flex-start;
  }

  /* Selected highlight ring — shown via parent border-color change */
  .place-card.selected .place-name {
    color: var(--color-primary);
  }

  .place-name {
    font-size: 0.9375rem; /* 15px */
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    /* Two-line clamp */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .place-card.mobile .place-name {
    font-size: 0.875rem; /* 14px */
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }

  .place-rating {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: 0.8125rem; /* 13px */
    line-height: 1.2;
  }

  .rating-star {
    color: #f5a623; /* intentional: brand star color, not theme-dependent */
    font-size: 0.75rem;
  }

  .rating-value {
    font-weight: 600;
    color: var(--color-grey-100);
  }

  .rating-count {
    color: var(--color-grey-60);
  }

  .place-type {
    font-size: 0.75rem; /* 12px */
    font-weight: 500;
    color: var(--color-grey-60);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .place-address {
    font-size: 0.75rem; /* 12px */
    color: var(--color-grey-70);
    line-height: 1.4;
    /* One-line clamp */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .place-card.mobile .place-address {
    -webkit-line-clamp: 2;
    line-clamp: 2;
    white-space: normal;
    display: -webkit-box;
    -webkit-box-orient: vertical;
  }
</style>
