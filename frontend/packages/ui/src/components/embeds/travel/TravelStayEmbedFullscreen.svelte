<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedFullscreen.svelte
  
  Fullscreen detail view for a single travel stay/accommodation result.
  Uses UnifiedEmbedFullscreen as base and shows property details.
  
  Layout:
  - Header: Property name, star rating, rating/reviews
  - Image (large thumbnail or first image)
  - Price details (per night + total)
  - Booking CTA button (links to Google Hotels)
  - Special badges (free cancellation, eco-certified)
  - Description (if available)
  - Amenities list
  - Check-in / Check-out times
  - Nearby places
  
  This component is rendered inside TravelStaysEmbedFullscreen as an overlay
  via ChildEmbedOverlay when a stay card is clicked.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /** Nearby place data */
  interface NearbyPlace {
    name?: string;
    transportations?: Array<{ type?: string; duration?: string }>;
  }
  
  /** Image data */
  interface StayImage {
    thumbnail?: string;
    original_image?: string;
  }
  
  /** Stay data passed from parent */
  interface StayData {
    type?: string;
    name?: string;
    description?: string;
    property_type?: string;
    link?: string;
    property_token?: string;
    gps_coordinates?: { latitude: number; longitude: number };
    hotel_class?: number;
    overall_rating?: number;
    reviews?: number;
    rate_per_night?: string;
    extracted_rate_per_night?: number;
    total_rate?: string;
    extracted_total_rate?: number;
    currency?: string;
    check_in_time?: string;
    check_out_time?: string;
    amenities?: string[];
    images?: StayImage[];
    thumbnail?: string;
    nearby_places?: NearbyPlace[];
    eco_certified?: boolean;
    free_cancellation?: boolean;
    hash?: string;
  }
  
  interface Props {
    /** Stay data from parent */
    stay: StayData;
    /** Close handler */
    onClose: () => void;
  }
  
  let {
    stay,
    onClose,
  }: Props = $props();
  
  // Property name
  let name = $derived(stay.name || 'Unknown Property');
  
  // Star rating display
  let stars = $derived(
    stay.hotel_class && stay.hotel_class >= 1 && stay.hotel_class <= 5
      ? '★'.repeat(stay.hotel_class)
      : ''
  );
  
  // Property type badge (e.g., "Hotel", "Apartment")
  let propertyType = $derived(stay.property_type || '');
  
  // Formatted rating
  let formattedRating = $derived(
    stay.overall_rating != null ? stay.overall_rating.toFixed(1) : ''
  );
  
  // Formatted review count
  let formattedReviews = $derived(
    stay.reviews != null ? stay.reviews.toLocaleString() : ''
  );
  
  // Currency
  let currency = $derived(stay.currency || 'EUR');
  
  // Price per night
  let pricePerNight = $derived(
    stay.extracted_rate_per_night != null
      ? Math.round(stay.extracted_rate_per_night)
      : null
  );
  
  // Total price
  let totalPrice = $derived(
    stay.extracted_total_rate != null
      ? Math.round(stay.extracted_total_rate)
      : null
  );
  
  // Main image URL (prefer original, fallback to thumbnail)
  let mainImage = $derived.by(() => {
    if (stay.images && stay.images.length > 0) {
      return stay.images[0].original_image || stay.images[0].thumbnail;
    }
    return stay.thumbnail;
  });
  
  // All images for gallery
  let allImages = $derived.by(() => {
    if (!stay.images || stay.images.length === 0) {
      return stay.thumbnail ? [stay.thumbnail] : [];
    }
    return stay.images
      .map(img => img.original_image || img.thumbnail)
      .filter((url): url is string => !!url);
  });
  
  // Current image index for gallery navigation
  let currentImageIndex = $state(0);
  
  // Current image URL
  let currentImage = $derived(
    allImages.length > 0 ? allImages[currentImageIndex] : undefined
  );
  
  /**
   * Navigate to next image in gallery
   */
  function nextImage() {
    if (allImages.length > 1) {
      currentImageIndex = (currentImageIndex + 1) % allImages.length;
    }
  }
  
  /**
   * Navigate to previous image in gallery
   */
  function prevImage() {
    if (allImages.length > 1) {
      currentImageIndex = (currentImageIndex - 1 + allImages.length) % allImages.length;
    }
  }
  
  // Booking URL (direct from stay data)
  let bookingUrl = $derived(stay.link || '');
  
  /**
   * Open the booking URL in a new tab
   */
  function handleBooking() {
    if (bookingUrl) {
      window.open(bookingUrl, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Amenities list
  let amenities = $derived(stay.amenities || []);
  
  // Nearby places
  let nearbyPlaces = $derived(stay.nearby_places || []);
  
  // Skill name for bottom bar
  let skillName = $derived($text('app_skills.travel.search_stays'));
</script>

<UnifiedEmbedFullscreen
  appId="travel"
  skillId="search_stays"
  title=""
  {onClose}
  skillIconName="search"
  status="finished"
  {skillName}
  showStatus={false}
>
  {#snippet content()}
    <div class="stay-fullscreen">
      <!-- Header: Name + Stars + Rating -->
      <div class="stay-header">
        <h1 class="stay-name">{name}</h1>
        
        {#if stars || propertyType}
          <div class="stay-sub-header">
            {#if stars}
              <span class="stay-stars">{stars}</span>
            {/if}
            {#if propertyType}
              <span class="property-type-badge">{propertyType}</span>
            {/if}
          </div>
        {/if}
        
        {#if formattedRating}
          <div class="stay-rating">
            <span class="rating-value">{formattedRating}</span>
            {#if formattedReviews}
              <span class="rating-reviews">({formattedReviews} reviews)</span>
            {/if}
          </div>
        {/if}
      </div>
      
      <!-- Image Gallery -->
      {#if currentImage}
        <div class="image-gallery">
          <img
            class="gallery-image"
            src={currentImage}
            alt={name}
            loading="lazy"
          />
          
          <!-- Gallery navigation (when multiple images) -->
          {#if allImages.length > 1}
            <button class="gallery-nav gallery-prev" onclick={prevImage} aria-label="Previous image">
              ‹
            </button>
            <button class="gallery-nav gallery-next" onclick={nextImage} aria-label="Next image">
              ›
            </button>
            <div class="gallery-counter">
              {currentImageIndex + 1} / {allImages.length}
            </div>
          {/if}
        </div>
      {/if}
      
      <!-- Price Section -->
      <div class="price-section">
        {#if pricePerNight != null}
          <div class="price-main">
            <span class="price-amount">{currency} {pricePerNight}</span>
            <span class="price-unit">/{$text('embeds.night')}</span>
          </div>
        {/if}
        {#if totalPrice != null}
          <div class="price-total">
            {currency} {totalPrice} {$text('embeds.total')}
          </div>
        {/if}
      </div>
      
      <!-- Booking CTA -->
      {#if bookingUrl}
        <button class="cta-button" onclick={handleBooking}>
          {$text('embeds.view_on_google_hotels')}
        </button>
      {/if}
      
      <!-- Special Badges -->
      {#if stay.free_cancellation || stay.eco_certified}
        <div class="badges-section">
          {#if stay.free_cancellation}
            <span class="badge badge-cancellation">{$text('embeds.free_cancellation')}</span>
          {/if}
          {#if stay.eco_certified}
            <span class="badge badge-eco">{$text('embeds.eco_certified')}</span>
          {/if}
        </div>
      {/if}
      
      <!-- Description -->
      {#if stay.description}
        <div class="description-section">
          <p>{stay.description}</p>
        </div>
      {/if}
      
      <!-- Amenities -->
      {#if amenities.length > 0}
        <div class="amenities-section">
          <div class="amenities-grid">
            {#each amenities as amenity}
              <span class="amenity-badge">{amenity}</span>
            {/each}
          </div>
        </div>
      {/if}
      
      <!-- Check-in / Check-out Times -->
      {#if stay.check_in_time || stay.check_out_time}
        <div class="check-times-section">
          {#if stay.check_in_time}
            <div class="check-time">
              <span class="check-label">{$text('embeds.check_in')}</span>
              <span class="check-value">{stay.check_in_time}</span>
            </div>
          {/if}
          {#if stay.check_out_time}
            <div class="check-time">
              <span class="check-label">{$text('embeds.check_out')}</span>
              <span class="check-value">{stay.check_out_time}</span>
            </div>
          {/if}
        </div>
      {/if}
      
      <!-- Nearby Places -->
      {#if nearbyPlaces.length > 0}
        <div class="nearby-section">
          <h3 class="section-title">{$text('embeds.nearby')}</h3>
          <div class="nearby-list">
            {#each nearbyPlaces as place}
              <div class="nearby-place">
                <span class="place-name">{place.name || 'Unknown'}</span>
                {#if place.transportations && place.transportations.length > 0}
                  <div class="place-transports">
                    {#each place.transportations as transport}
                      <span class="transport-info">
                        {transport.type}: {transport.duration}
                      </span>
                    {/each}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Stay Fullscreen Layout
     =========================================== */
  
  .stay-fullscreen {
    max-width: 600px;
    margin: 60px auto 120px;
    padding: 0 20px;
  }
  
  @container fullscreen (max-width: 500px) {
    .stay-fullscreen {
      margin-top: 70px;
      padding: 0 16px;
    }
  }
  
  /* ===========================================
     Header
     =========================================== */
  
  .stay-header {
    text-align: center;
    margin-bottom: 24px;
  }
  
  .stay-name {
    font-size: 24px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }
  
  @container fullscreen (max-width: 500px) {
    .stay-name {
      font-size: 20px;
    }
  }
  
  .stay-sub-header {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-top: 6px;
  }
  
  .stay-stars {
    font-size: 14px;
    color: #f5a623;
    letter-spacing: 1px;
  }
  
  .property-type-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 100px;
    background-color: var(--color-grey-20);
    font-size: 12px;
    font-weight: 500;
    color: var(--color-grey-80);
  }
  
  .stay-rating {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    margin-top: 8px;
    font-size: 16px;
  }
  
  .rating-value {
    font-weight: 700;
    color: var(--color-font-primary);
  }
  
  .rating-reviews {
    color: var(--color-font-secondary);
    font-size: 14px;
  }
  
  /* ===========================================
     Image Gallery
     =========================================== */
  
  .image-gallery {
    position: relative;
    width: 100%;
    border-radius: 16px;
    overflow: hidden;
    margin-bottom: 24px;
    background: var(--color-grey-15);
  }
  
  .gallery-image {
    width: 100%;
    height: 280px;
    object-fit: cover;
    display: block;
  }
  
  @container fullscreen (max-width: 500px) {
    .gallery-image {
      height: 200px;
    }
  }
  
  /* Gallery navigation arrows */
  .gallery-nav {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(0, 0, 0, 0.5);
    color: white;
    border: none;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    font-size: 20px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.15s ease;
    z-index: 2;
  }
  
  .gallery-nav:hover {
    background: rgba(0, 0, 0, 0.7);
  }
  
  .gallery-prev {
    left: 10px;
  }
  
  .gallery-next {
    right: 10px;
  }
  
  /* Image counter */
  .gallery-counter {
    position: absolute;
    bottom: 10px;
    right: 10px;
    background: rgba(0, 0, 0, 0.6);
    color: white;
    font-size: 12px;
    padding: 3px 10px;
    border-radius: 12px;
    z-index: 2;
  }
  
  /* ===========================================
     Price Section
     =========================================== */
  
  .price-section {
    text-align: center;
    margin-bottom: 16px;
  }
  
  .price-main {
    display: inline-flex;
    align-items: baseline;
    gap: 4px;
  }
  
  .price-amount {
    font-size: 28px;
    font-weight: 700;
    color: var(--color-font-primary);
  }
  
  @container fullscreen (max-width: 500px) {
    .price-amount {
      font-size: 24px;
    }
  }
  
  .price-unit {
    font-size: 16px;
    color: var(--color-font-secondary);
  }
  
  .price-total {
    font-size: 14px;
    color: var(--color-font-secondary);
    margin-top: 4px;
  }
  
  /* ===========================================
     Booking CTA Button
     =========================================== */
  
  .cta-button {
    display: block;
    width: 100%;
    max-width: 320px;
    margin: 0 auto 24px;
    background-color: var(--color-button-primary);
    color: white;
    border: none;
    border-radius: 20px;
    padding: 12px 30px;
    font-family: 'Lexend Deca', sans-serif;
    font-size: 15px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease-in-out;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.25));
    text-align: center;
  }
  
  .cta-button:hover {
    background-color: var(--color-button-primary-hover);
    scale: 1.02;
  }
  
  .cta-button:active {
    background-color: var(--color-button-primary-pressed);
    scale: 0.98;
    filter: none;
  }
  
  /* ===========================================
     Badges Section
     =========================================== */
  
  .badges-section {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
    margin-bottom: 24px;
  }
  
  .badge {
    font-size: 13px;
    padding: 4px 12px;
    border-radius: 100px;
    font-weight: 500;
    white-space: nowrap;
  }
  
  .badge-cancellation {
    background: rgba(76, 175, 80, 0.12);
    color: #4caf50;
  }
  
  .badge-eco {
    background: rgba(33, 150, 243, 0.12);
    color: #2196f3;
  }
  
  /* ===========================================
     Description
     =========================================== */
  
  .description-section {
    margin-bottom: 24px;
    padding: 16px;
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 12px;
  }
  
  .description-section p {
    font-size: 14px;
    color: var(--color-font-secondary);
    line-height: 1.5;
    margin: 0;
    word-break: break-word;
  }
  
  /* ===========================================
     Amenities
     =========================================== */
  
  .amenities-section {
    margin-bottom: 24px;
  }
  
  .amenities-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
  }
  
  .amenity-badge {
    font-size: 13px;
    padding: 4px 12px;
    border-radius: 100px;
    background: var(--color-grey-15);
    color: var(--color-font-secondary);
    white-space: nowrap;
  }
  
  /* ===========================================
     Check-in / Check-out
     =========================================== */
  
  .check-times-section {
    display: flex;
    gap: 24px;
    justify-content: center;
    margin-bottom: 24px;
    padding: 16px;
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 12px;
  }
  
  .check-time {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  
  .check-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--color-font-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .check-value {
    font-size: 15px;
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  /* ===========================================
     Nearby Places
     =========================================== */
  
  .nearby-section {
    margin-bottom: 24px;
  }
  
  .section-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-font-primary);
    margin: 0 0 12px;
    text-align: center;
  }
  
  .nearby-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .nearby-place {
    padding: 12px 16px;
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 12px;
  }
  
  .place-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-font-primary);
  }
  
  .place-transports {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 4px;
  }
  
  .transport-info {
    font-size: 12px;
    color: var(--color-font-secondary);
  }
</style>
