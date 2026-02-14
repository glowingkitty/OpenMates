<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedPreview.svelte
  
  Preview component for a single travel stay/accommodation result (child card).
  Uses UnifiedEmbedPreview as base and displays stay summary:
  - Thumbnail image (full-width)
  - Property name and star rating
  - Rating and review count
  - Amenity badges (max 3)
  - Price per night and total price
  
  Similar to TravelConnectionEmbedPreview but for accommodation results.
  This component is rendered inside TravelStaysEmbedFullscreen's grid.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Props for travel stay embed preview
   * Data comes from the parent fullscreen component which passes
   * individual stay result fields directly.
   */
  interface Props {
    /** Synthetic embed ID for this stay card */
    id: string;
    /** Property name */
    name?: string;
    /** Thumbnail URL */
    thumbnail?: string;
    /** Hotel class (1-5 stars) */
    hotelClass?: number;
    /** Overall rating (e.g., 4.3) */
    overallRating?: number;
    /** Number of reviews */
    reviews?: number;
    /** Currency code (e.g., 'EUR') */
    currency?: string;
    /** Extracted rate per night (numeric) */
    ratePerNight?: number;
    /** Extracted total rate (numeric) */
    totalRate?: number;
    /** Top amenities to display */
    amenities?: string[];
    /** Whether this is among the cheapest stays */
    isCheapest?: boolean;
    /** Eco-certified badge */
    ecoCertified?: boolean;
    /** Free cancellation badge */
    freeCancellation?: boolean;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    name,
    thumbnail,
    hotelClass,
    overallRating,
    reviews,
    currency = 'EUR',
    ratePerNight,
    totalRate,
    amenities = [],
    isCheapest = false,
    // ecoCertified and freeCancellation accepted but not shown in preview to keep it compact
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ecoCertified = false,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    freeCancellation = false,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Star rating display (e.g., "★★★★")
  let stars = $derived(
    hotelClass && hotelClass >= 1 && hotelClass <= 5
      ? '★'.repeat(hotelClass)
      : ''
  );
  
  // Formatted rating (e.g., "4.3")
  let formattedRating = $derived(
    overallRating != null ? overallRating.toFixed(1) : ''
  );
  
  // Formatted review count (e.g., "1,234")
  let formattedReviews = $derived(
    reviews != null ? reviews.toLocaleString() : ''
  );
  
  // Top amenities (max 3 for preview card)
  let topAmenities = $derived(amenities.slice(0, 3));
  
  // Display name for BasicInfosBar
  let displayName = $derived(name || 'Stay');
  
  // No-op stop handler (stays don't have cancellable tasks)
  async function handleStop() {
    // Not applicable for stay result cards
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="travel"
  skillId="search_stays"
  skillIconName="search"
  {status}
  skillName={displayName}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={true}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="stay-details" class:mobile={isMobileLayout} class:cheapest={isCheapest}>
      <!-- Thumbnail -->
      {#if thumbnail}
        <div class="stay-thumb">
          <img src={thumbnail} alt={name || 'Property'} loading="lazy" />
        </div>
      {:else}
        <div class="stay-thumb placeholder">
          <span class="placeholder-icon">🏨</span>
        </div>
      {/if}
      
      <!-- Info section below thumbnail -->
      <div class="stay-info">
        <!-- Name -->
        <div class="stay-name">{name || 'Unknown'}</div>
        
        <!-- Stars -->
        {#if stars}
          <div class="stay-stars">{stars}</div>
        {/if}
        
        <!-- Rating and reviews -->
        {#if formattedRating}
          <div class="stay-meta">
            <span class="rating">{formattedRating}</span>
            {#if formattedReviews}
              <span class="reviews">({formattedReviews})</span>
            {/if}
          </div>
        {/if}
        
        <!-- Amenities (compact badges) -->
        {#if topAmenities.length > 0}
          <div class="stay-amenities">
            {#each topAmenities as amenity}
              <span class="amenity">{amenity}</span>
            {/each}
          </div>
        {/if}
        
        <!-- Price -->
        <div class="stay-price">
          {#if ratePerNight != null}
            <span class="price-amount" class:cheapest-price={isCheapest}>
              {currency} {Math.round(ratePerNight)}
            </span>
            <span class="price-unit">/{$text('embeds.night')}</span>
          {/if}
          {#if totalRate != null}
            <span class="price-total">
              {currency} {Math.round(totalRate)} {$text('embeds.total')}
            </span>
          {/if}
        </div>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Stay Details Content
     =========================================== */
  
  .stay-details {
    display: flex;
    flex-direction: column;
    height: 100%;
    position: relative;
    overflow: hidden;
  }
  
  /* Cheapest highlight border (inset glow) */
  .stay-details.cheapest::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: 16px;
    box-shadow: inset 0 0 0 2px var(--color-primary);
    pointer-events: none;
    z-index: 1;
  }
  
  /* ===========================================
     Thumbnail
     =========================================== */
  
  .stay-thumb {
    width: 100%;
    height: 110px;
    overflow: hidden;
    background: var(--color-grey-15);
    flex-shrink: 0;
  }
  
  .stay-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  
  .stay-thumb.placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .placeholder-icon {
    font-size: 28px;
    opacity: 0.4;
  }
  
  /* ===========================================
     Info Section
     =========================================== */
  
  .stay-info {
    padding: 8px 12px 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-height: 0;
  }
  
  .stay-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .stay-stars {
    font-size: 10px;
    color: #f5a623;
    letter-spacing: 1px;
  }
  
  /* Rating and reviews */
  .stay-meta {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: 12px;
  }
  
  .rating {
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .reviews {
    color: var(--color-font-secondary);
  }
  
  /* Amenities */
  .stay-amenities {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
  }
  
  .amenity {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 8px;
    background: var(--color-grey-15);
    color: var(--color-font-secondary);
    white-space: nowrap;
  }
  
  /* Price */
  .stay-price {
    display: flex;
    align-items: baseline;
    gap: 3px;
    flex-wrap: wrap;
    margin-top: auto;
  }
  
  .price-amount {
    font-size: 14px;
    font-weight: 700;
    color: var(--color-font-primary);
  }
  
  .price-amount.cheapest-price {
    color: var(--color-success, #22c55e);
  }
  
  .price-unit {
    font-size: 11px;
    color: var(--color-font-secondary);
  }
  
  .price-total {
    font-size: 11px;
    color: var(--color-font-secondary);
    margin-left: auto;
  }
  
  /* ===========================================
     Mobile Adjustments
     =========================================== */
  
  .stay-details.mobile .stay-thumb {
    height: 90px;
  }
  
  .stay-details.mobile .stay-name {
    font-size: 12px;
  }
  
  .stay-details.mobile .price-amount {
    font-size: 13px;
  }
</style>
