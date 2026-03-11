<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedFullscreen.svelte
  
  Fullscreen detail view for a single travel stay/accommodation result.
  Uses EntryWithMapTemplate for responsive map + detail card layout.
  
  Shows map when GPS coordinates are available from the stay data.
  
  Layout:
  - Map background with hotel location pin
  - Detail card with: name, stars, rating, image gallery, price, badges,
    description, amenities, check-in/out, nearby places
  - "View on Google Hotels" CTA
  
  See docs/architecture/embeds.md
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import { text } from '@repo/ui';
  
  interface NearbyPlace {
    name?: string;
    transportations?: Array<{ type?: string; duration?: string }>;
  }
  
  interface StayImage {
    thumbnail?: string;
    original_image?: string;
  }
  
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
    stay: StayData;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }
  
  let {
    stay,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  // Defensive: stay may be undefined during async component loading in dev preview
  type MaybeStay = StayData | undefined;
  
  let name = $derived((stay as MaybeStay)?.name || 'Unknown Property');
  let stars = $derived.by(() => {
    const s = stay as MaybeStay;
    return s?.hotel_class && s.hotel_class >= 1 && s.hotel_class <= 5
      ? '\u2605'.repeat(s.hotel_class) : '';
  });
  let propertyType = $derived((stay as MaybeStay)?.property_type || '');
  let formattedRating = $derived.by(() => { const s = stay as MaybeStay; return s?.overall_rating != null ? s.overall_rating.toFixed(1) : ''; });
  let formattedReviews = $derived.by(() => { const s = stay as MaybeStay; return s?.reviews != null ? s.reviews.toLocaleString() : ''; });
  let currency = $derived((stay as MaybeStay)?.currency || 'EUR');
  let pricePerNight = $derived.by(() => { const s = stay as MaybeStay; return s?.extracted_rate_per_night != null ? Math.round(s.extracted_rate_per_night) : null; });
  let totalPrice = $derived.by(() => { const s = stay as MaybeStay; return s?.extracted_total_rate != null ? Math.round(s.extracted_total_rate) : null; });
  let amenities = $derived((stay as MaybeStay)?.amenities || []);
  let nearbyPlaces = $derived((stay as MaybeStay)?.nearby_places || []);
  let bookingUrl = $derived((stay as MaybeStay)?.link || '');

  // Map data from GPS coordinates
  let mapCenter = $derived.by(() => {
    const s = stay as MaybeStay;
    const gps = s?.gps_coordinates;
    if (gps?.latitude != null && gps?.longitude != null) {
      return { lat: gps.latitude, lon: gps.longitude };
    }
    return undefined;
  });

  let mapMarkers = $derived(
    mapCenter ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: name }] : []
  );

  // Image gallery
  let allImages = $derived.by(() => {
    const s = stay as MaybeStay;
    if (!s?.images || s.images.length === 0) {
      return s?.thumbnail ? [s.thumbnail] : [];
    }
    return s.images
      .map(img => img.original_image || img.thumbnail)
      .filter((url): url is string => !!url);
  });
  
  let currentImageIndex = $state(0);
  let currentImage = $derived(allImages.length > 0 ? allImages[currentImageIndex] : undefined);
  
  function nextImage() {
    if (allImages.length > 1) currentImageIndex = (currentImageIndex + 1) % allImages.length;
  }
  
  function prevImage() {
    if (allImages.length > 1) currentImageIndex = (currentImageIndex - 1 + allImages.length) % allImages.length;
  }
  
  function handleBooking() {
    if (bookingUrl) window.open(bookingUrl, '_blank', 'noopener,noreferrer');
  }
</script>

{#if stay}
<EntryWithMapTemplate
  appId="travel"
  skillId="search_stays"
  {onClose}
  skillIconName="search"
  embedHeaderTitle={$text('app_skills.travel.search_stays')}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {mapCenter}
  mapZoom={15}
  {mapMarkers}
>
  {#snippet embedHeaderCta()}
    {#if bookingUrl}
      <button class="cta-button" onclick={handleBooking}>
        {$text('embeds.view_on_google_hotels')}
      </button>
    {/if}
  {/snippet}

  {#snippet detailContent()}
    <!-- Header: Name + Stars + Rating -->
    <div class="stay-header">
      <h1 class="stay-name">{name}</h1>
      {#if stars || propertyType}
        <div class="stay-sub-header">
          {#if stars}<span class="stay-stars">{stars}</span>{/if}
          {#if propertyType}<span class="property-type-badge">{propertyType}</span>{/if}
        </div>
      {/if}
      {#if formattedRating}
        <div class="stay-rating">
          <span class="rating-value">{formattedRating}</span>
          {#if formattedReviews}<span class="rating-reviews">({formattedReviews} reviews)</span>{/if}
        </div>
      {/if}
    </div>

    <!-- Image Gallery -->
    {#if currentImage}
      <div class="image-gallery">
        <img class="gallery-image" src={currentImage} alt={name} loading="lazy" />
        {#if allImages.length > 1}
          <button class="gallery-nav gallery-prev" onclick={prevImage} aria-label="Previous image">&#x2039;</button>
          <button class="gallery-nav gallery-next" onclick={nextImage} aria-label="Next image">&#x203a;</button>
          <div class="gallery-counter">{currentImageIndex + 1} / {allImages.length}</div>
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
        <div class="price-total">{currency} {totalPrice} {$text('embeds.total')}</div>
      {/if}
    </div>

    <!-- Badges -->
    {#if stay.free_cancellation || stay.eco_certified}
      <div class="badges-section">
        {#if stay.free_cancellation}<span class="badge badge-cancellation">{$text('embeds.free_cancellation')}</span>{/if}
        {#if stay.eco_certified}<span class="badge badge-eco">{$text('embeds.eco_certified')}</span>{/if}
      </div>
    {/if}

    <!-- Description -->
    {#if stay.description}
      <div class="description-section"><p>{stay.description}</p></div>
    {/if}

    <!-- Amenities -->
    {#if amenities.length > 0}
      <div class="amenities-grid">
        {#each amenities as amenity}
          <span class="amenity-badge">{amenity}</span>
        {/each}
      </div>
    {/if}

    <!-- Check-in / Check-out -->
    {#if stay.check_in_time || stay.check_out_time}
      <div class="check-times">
        {#if stay.check_in_time}
          <div class="check-time"><span class="check-label">{$text('embeds.check_in')}</span><span class="check-value">{stay.check_in_time}</span></div>
        {/if}
        {#if stay.check_out_time}
          <div class="check-time"><span class="check-label">{$text('embeds.check_out')}</span><span class="check-value">{stay.check_out_time}</span></div>
        {/if}
      </div>
    {/if}

    <!-- Nearby Places -->
    {#if nearbyPlaces.length > 0}
      <div class="nearby-section">
        <h3 class="section-title">{$text('embeds.nearby')}</h3>
        {#each nearbyPlaces as place}
          <div class="nearby-place">
            <span class="place-name">{place.name || 'Unknown'}</span>
            {#if place.transportations && place.transportations.length > 0}
              <div class="place-transports">
                {#each place.transportations as transport}
                  <span class="transport-info">{transport.type}: {transport.duration}</span>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {/snippet}

  {#snippet ctaContent()}
    {#if bookingUrl}
      <button class="booking-button" onclick={handleBooking}>
        {$text('embeds.view_on_google_hotels')}
      </button>
    {/if}
  {/snippet}
</EntryWithMapTemplate>
{/if}

<style>
  .stay-header { text-align: center; }
  .stay-name {
    font-size: 20px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }
  .stay-sub-header {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-top: 6px;
  }
  .stay-stars { font-size: 14px; color: #f5a623; letter-spacing: 1px; }
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
  .rating-value { font-weight: 700; color: var(--color-font-primary); }
  .rating-reviews { color: var(--color-font-secondary); font-size: 14px; }

  .image-gallery {
    position: relative;
    width: 100%;
    border-radius: 12px;
    overflow: hidden;
    background: var(--color-grey-15);
  }
  .gallery-image {
    width: 100%;
    height: 180px;
    object-fit: cover;
    display: block;
  }
  .gallery-nav {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(0, 0, 0, 0.5);
    color: white;
    border: none;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    font-size: 18px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2;
  }
  .gallery-prev { left: 8px; }
  .gallery-next { right: 8px; }
  .gallery-counter {
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: rgba(0, 0, 0, 0.6);
    color: white;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    z-index: 2;
  }

  .price-section { text-align: center; }
  .price-main { display: inline-flex; align-items: baseline; gap: 4px; }
  .price-amount { font-size: 24px; font-weight: 700; color: var(--color-font-primary); }
  .price-unit { font-size: 14px; color: var(--color-font-secondary); }
  .price-total { font-size: 13px; color: var(--color-font-secondary); margin-top: 4px; }

  .badges-section {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
  }
  .badge {
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 100px;
    font-weight: 500;
  }
  .badge-cancellation { background: rgba(76, 175, 80, 0.12); color: #4caf50; }
  .badge-eco { background: rgba(33, 150, 243, 0.12); color: #2196f3; }

  .description-section {
    padding: 12px;
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 10px;
  }
  .description-section p {
    font-size: 13px;
    color: var(--color-font-secondary);
    line-height: 1.5;
    margin: 0;
    word-break: break-word;
  }

  .amenities-grid { display: flex; flex-wrap: wrap; gap: 6px; }
  .amenity-badge {
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 100px;
    background-color: var(--color-grey-10);
    color: var(--color-grey-80);
    border: 1px solid var(--color-grey-20);
  }

  .check-times { display: flex; gap: 16px; flex-wrap: wrap; }
  .check-time { display: flex; flex-direction: column; gap: 2px; }
  .check-label { font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--color-grey-60); letter-spacing: 0.04em; }
  .check-value { font-size: 14px; color: var(--color-font-primary); }

  .nearby-section { display: flex; flex-direction: column; gap: 8px; }
  .section-title { font-size: 13px; font-weight: 600; color: var(--color-grey-60); text-transform: uppercase; letter-spacing: 0.04em; margin: 0; }
  .nearby-place { padding: 8px 0; border-bottom: 1px solid var(--color-grey-15); }
  .nearby-place:last-child { border-bottom: none; }
  .place-name { font-size: 14px; font-weight: 500; color: var(--color-font-primary); }
  .place-transports { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
  .transport-info { font-size: 12px; color: var(--color-font-secondary); }

  .cta-button, .booking-button {
    display: block;
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
    width: 100%;
  }
  .cta-button:hover, .booking-button:hover { background-color: var(--color-button-primary-hover); scale: 1.02; }
  .cta-button:active, .booking-button:active { background-color: var(--color-button-primary-pressed); scale: 0.98; filter: none; }
</style>
