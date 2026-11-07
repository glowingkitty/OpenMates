<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedFullscreen.svelte
  
  Fullscreen detail view for a single travel stay/accommodation result.
  Uses ResultEmbedFullscreen for responsive map + detail card layout.
  
  Shows map when GPS coordinates are available from the stay data.
  
  Layout:
  - Map background with hotel location pin
  - Detail card with: name, stars, rating, image gallery, price, badges,
    description, amenities, check-in/out, nearby places
  - "View on Google Hotels" CTA
  
  See docs/architecture/embeds.md
-->

<script lang="ts">
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from "../../../types/authoredResult";
  import { getContext } from "svelte";
  import { travelStayFacts, travelStayCoordinates } from './travelStayFacts';
  import EmbedChevron from '../EmbedChevron.svelte';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import MarkdownContent from '../MarkdownContent.svelte';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import { text } from '@repo/ui';
  import { authStore } from '../../../stores/authStore';
  import { savedEmbedIds, loadEmbedSaved, toggleEmbedSaved, getEmbedIdFromContentRef } from '../../../services/savedEmbedService';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

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
    gps_coordinates?: { latitude?: number; longitude?: number };
    hotel_class?: number;
    overall_rating?: number;
    reviews?: number;
    rate_per_night?: string;
    extracted_rate_per_night?: number;
    total_rate?: string;
    extracted_total_rate?: number;
    currency?: string;
    check_in?: string;
    check_out?: string;
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
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    /** Embed ID forwarded to UnifiedEmbedFullscreen for the share handler */
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();
  const authoredContext = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);
  let isAuthored = $derived(Boolean(authoredContext?.authoring || data?.decodedContent?.authoring));

  // Build the stay object from data.decodedContent
  let dc = $derived(authoredContext?.presentationContent ?? authoredContext?.content ?? data.decodedContent);
  let authoredTitle = $derived(isAuthored && typeof dc?.title === "string" ? dc.title.trim() : "");

  let suppliedFacts = $derived(travelStayFacts(dc));

  let stay: StayData = $derived.by(() => {
    return {
    type: typeof dc.type === 'string' ? dc.type : undefined,
    name: typeof dc.name === 'string' ? dc.name : undefined,
    description: typeof dc.description === 'string' ? dc.description : undefined,
    property_type: typeof dc.property_type === 'string' ? dc.property_type : undefined,
    link: isAuthored ? suppliedFacts.sourceUrl : typeof dc.link === 'string' ? dc.link : undefined,
    property_token: typeof dc.property_token === 'string' ? dc.property_token : undefined,
    gps_coordinates: travelStayCoordinates(dc),
    hotel_class: typeof dc.hotel_class === 'number' ? dc.hotel_class : undefined,
    overall_rating: typeof dc.overall_rating === 'number' ? dc.overall_rating : undefined,
    reviews: typeof dc.reviews === 'number' ? dc.reviews : undefined,
    rate_per_night: typeof dc.rate_per_night === 'string' ? dc.rate_per_night : undefined,
    extracted_rate_per_night: typeof dc.extracted_rate_per_night === 'number' ? dc.extracted_rate_per_night : isAuthored ? suppliedFacts.nightlyRate.amount : undefined,
    total_rate: typeof dc.total_rate === 'string' ? dc.total_rate : undefined,
    extracted_total_rate: typeof dc.extracted_total_rate === 'number' ? dc.extracted_total_rate : isAuthored ? suppliedFacts.totalRate.amount : undefined,
    currency: typeof dc.currency === 'string' ? dc.currency : undefined,
    check_in: suppliedFacts.checkIn,
    check_out: suppliedFacts.checkOut,
    check_in_time: typeof dc.check_in_time === 'string' ? dc.check_in_time : undefined,
    check_out_time: typeof dc.check_out_time === 'string' ? dc.check_out_time : undefined,
    amenities: Array.isArray(dc.amenities) ? dc.amenities as string[] : undefined,
    images: Array.isArray(dc.images) ? dc.images as StayImage[] : undefined,
    thumbnail: typeof dc.thumbnail === 'string' ? dc.thumbnail : undefined,
    nearby_places: Array.isArray(dc.nearby_places) ? dc.nearby_places as NearbyPlace[] : undefined,
    eco_certified: typeof dc.eco_certified === 'boolean' ? dc.eco_certified : undefined,
    free_cancellation: typeof dc.free_cancellation === 'boolean' ? dc.free_cancellation : undefined,
    hash: typeof dc.hash === 'string' ? dc.hash : undefined,
    };
  });

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
  let currency = $derived((stay as MaybeStay)?.currency || (isAuthored ? '' : 'EUR'));
  let nightlyCurrency = $derived(isAuthored ? suppliedFacts.nightlyRate.currency || '' : currency);
  let totalCurrency = $derived(isAuthored ? suppliedFacts.totalRate.currency || '' : currency);
  let pricePerNight = $derived.by(() => { const s = stay as MaybeStay; return s?.extracted_rate_per_night != null ? (isAuthored ? s.extracted_rate_per_night : Math.round(s.extracted_rate_per_night)) : null; });
  let totalPrice = $derived.by(() => { const s = stay as MaybeStay; return s?.extracted_total_rate != null ? (isAuthored ? s.extracted_total_rate : Math.round(s.extracted_total_rate)) : null; });
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

  // Image gallery — all external URLs must be proxied for privacy
  let allImages = $derived.by(() => {
    const s = stay as MaybeStay;
    if (!s?.images || s.images.length === 0) {
      return s?.thumbnail ? [proxyImage(s.thumbnail, MAX_WIDTH_HEADER_IMAGE)] : [];
    }
    return s.images
      .map(img => img.original_image || img.thumbnail)
      .filter((url): url is string => !!url)
      .map(url => proxyImage(url, MAX_WIDTH_HEADER_IMAGE));
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


  // Save / Saved: encrypted `saved` flag on the embed itself (no memory entry).
  const savedTargetId = $derived(embedId || data.focusChildEmbedId || getEmbedIdFromContentRef(data.attrs?.contentRef));
  let isSaved = $derived($savedEmbedIds.has(savedTargetId));
  $effect(() => { if (savedTargetId) void loadEmbedSaved(savedTargetId); });

  function handleToggleSaved() {
    if (savedTargetId) void toggleEmbedSaved(savedTargetId);
  }

</script>

{#if stay}
  {#snippet resultMedia()}
    <!-- Image Gallery -->
    {#if currentImage}
      <div class="image-gallery" data-testid="stay-gallery">
        <img class="gallery-image" src={currentImage} alt={name} loading="lazy" />
        {#if allImages.length > 1}
          <button type="button" class="gallery-nav gallery-prev" onclick={prevImage} aria-label="Previous image"><EmbedChevron direction="previous" /></button>
          <button type="button" class="gallery-nav gallery-next" onclick={nextImage} aria-label="Next image"><EmbedChevron direction="next" /></button>
          <div class="gallery-counter" data-testid="stay-gallery-counter">{currentImageIndex + 1} / {allImages.length}</div>
        {/if}
      </div>
    {/if}

  {/snippet}
<ResultEmbedFullscreen
  media={currentImage ? resultMedia : undefined}
  result={stay as unknown as Record<string, unknown>}
  appId="travel"
  skillId="search_stays"
  {onClose}
  skillIconName="search"
  embedHeaderTitle={authoredTitle || name}
  embedHeaderSubtitle={authoredTitle ? [name, propertyType].filter(Boolean).join(" · ") || undefined : propertyType || undefined}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {mapCenter}
  mapZoom={15}
  {mapMarkers}
  currentEmbedId={embedId}
>
  {#snippet embedHeaderCta()}
    <div class="embed-header-cta-group">
      {#if $authStore.isAuthenticated}
        <EmbedHeaderCtaButton label={$text(isSaved ? 'embeds.saved_item' : 'embeds.save_item')} variant="secondary" iconName="heart" iconOnly pressed={isSaved} onclick={handleToggleSaved} testId="save-embed-cta" />
      {/if}
      {#if bookingUrl}
        <EmbedHeaderCtaButton label={isAuthored ? $text('embeds.authoring.open_source') : $text('embeds.open_on_provider').replace('{provider}', 'Google Hotels')} onclick={handleBooking} testId="external-provider-cta" />
      {/if}
    </div>
  {/snippet}

  {#snippet summary()}
    {#if pricePerNight != null}<ResultEmbedInfo icon="euro" label="Price per night" value={`${nightlyCurrency} ${pricePerNight}`} caption="per night">{totalPrice != null ? `${totalCurrency} ${totalPrice} total` : 'Total price is not supplied.'}</ResultEmbedInfo>{/if}
    {#if formattedRating}<ResultEmbedInfo icon="star" label="Guest rating" value={formattedRating}>{formattedReviews ? `${formattedReviews} reviews` : 'Review count not supplied.'}</ResultEmbedInfo>{/if}
    {#if stars}<ResultEmbedInfo icon="hotel" label="Hotel class" value={stars}>{propertyType || name}</ResultEmbedInfo>{/if}
  {/snippet}

  {#snippet detailContent()}
    <!-- Header: Name + Stars + Rating -->
    <div class="stay-header">
      <h1 class="stay-name" data-testid="stay-name">{name}</h1>
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

    <!-- Price Section -->
    <div class="price-section">
      {#if pricePerNight != null}
        <div class="price-main">
          <span class="price-amount">{nightlyCurrency} {pricePerNight}</span>
          <span class="price-unit">/{$text('embeds.night')}</span>
        </div>
      {/if}
      {#if totalPrice != null}
        <div class="price-total">{totalCurrency} {totalPrice} {$text('embeds.total')}</div>
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
      <div class="description-section">
        <MarkdownContent content={stay.description} />
      </div>
    {/if}

    <!-- Amenities -->
    {#if amenities.length > 0}
      <div class="amenities-grid">
        {#each amenities as amenity}
          <ResultEmbedInfo icon="check" label={amenity} state="yes">{amenity}</ResultEmbedInfo>
        {/each}
      </div>
    {/if}

    <!-- Check-in / Check-out -->
    {#if stay.check_in || stay.check_out || stay.check_in_time || stay.check_out_time}
      <div class="check-times">
        {#if stay.check_in || stay.check_in_time}
          <div class="check-time"><span class="check-label">{$text('embeds.check_in')}</span><span class="check-value">{[stay.check_in, stay.check_in_time].filter(Boolean).join(' · ')}</span></div>
        {/if}
        {#if stay.check_out || stay.check_out_time}
          <div class="check-time"><span class="check-label">{$text('embeds.check_out')}</span><span class="check-value">{[stay.check_out, stay.check_out_time].filter(Boolean).join(' · ')}</span></div>
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


</ResultEmbedFullscreen>
{/if}

<style>
  .stay-header { text-align: center; }
  .stay-name {
    font-size: var(--font-size-h3);
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
    gap: var(--spacing-4);
    margin-top: var(--spacing-3);
  }
  .stay-stars { font-size: var(--font-size-small); color: #f5a623; letter-spacing: 1px; }
  .property-type-badge {
    display: inline-block;
    padding: var(--spacing-1) var(--spacing-5);
    border-radius: 100px;
    background-color: var(--color-grey-20);
    font-size: var(--font-size-xxs);
    font-weight: 500;
    color: var(--color-grey-80);
  }
  .stay-rating {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    margin-top: var(--spacing-4);
    font-size: var(--font-size-p);
  }
  .rating-value { font-weight: 700; color: var(--color-font-primary); }
  .rating-reviews { color: var(--color-font-secondary); font-size: 14px; }

  .image-gallery {
    position: relative;
    width: 100%;
    height: var(--result-media-height);
    border-radius: var(--radius-5);
    overflow: hidden;
    background: var(--color-grey-90);
  }
  :global([data-theme="dark"]) .image-gallery { background: var(--color-grey-30); }
  .gallery-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
  }
  .gallery-nav {
    all: unset;
    box-sizing: border-box;
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 36px;
    height: 44px;
    display: grid;
    place-items: center;
    cursor: pointer;
    color: var(--color-font-button);
    z-index: var(--z-index-raised-2);
  }
  .gallery-nav:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .gallery-prev { left: 8px; }
  .gallery-next { right: 8px; }
  .gallery-counter {
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: rgba(0, 0, 0, 0.6);
    color: white;
    font-size: var(--font-size-tiny);
    padding: var(--spacing-1) var(--spacing-4);
    border-radius: var(--radius-4);
    z-index: var(--z-index-raised-2);
  }

  .price-section { text-align: center; }
  .price-main { display: inline-flex; align-items: baseline; gap: var(--spacing-2); }
  .price-amount { font-size: 24px; font-weight: 700; color: var(--color-font-primary); }
  .price-unit { font-size: 14px; color: var(--color-font-secondary); }
  .price-total { font-size: 13px; color: var(--color-font-secondary); margin-top: 4px; }

  .badges-section {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
    justify-content: center;
  }
  .badge {
    font-size: var(--font-size-xxs);
    padding: var(--spacing-2) var(--spacing-5);
    border-radius: 100px;
    font-weight: 500;
  }
  .badge-cancellation { background: color-mix(in srgb, var(--color-success) 12%, transparent); color: var(--color-success); }
  .badge-eco { background: color-mix(in srgb, var(--color-app-travel) 12%, transparent); color: var(--color-app-travel); }

  .description-section {
    padding: var(--spacing-6);
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: var(--radius-4);
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
    line-height: 1.5;
  }
  /* Override MarkdownContent defaults to match description-section visual style */
  .description-section :global(.markdown-content) {
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
    line-height: 1.5;
  }

  .amenities-grid { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }

  .check-times { display: flex; gap: var(--spacing-8); flex-wrap: wrap; }
  .check-time { display: flex; flex-direction: column; gap: var(--spacing-1); }
  .check-label { font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--color-grey-60); letter-spacing: 0.04em; }
  .check-value { font-size: 14px; color: var(--color-font-primary); }

  .nearby-section { display: flex; flex-direction: column; gap: var(--spacing-4); }
  .section-title { font-size: 13px; font-weight: 600; color: var(--color-grey-60); text-transform: uppercase; letter-spacing: 0.04em; margin: 0; }
  .nearby-place { padding: 8px 0; border-bottom: 1px solid var(--color-grey-20); }
  .nearby-place:last-child { border-bottom: none; }
  .place-name { font-size: 14px; font-weight: 500; color: var(--color-font-primary); }
  .place-transports { display: flex; flex-wrap: wrap; gap: var(--spacing-4); margin-top: 4px; }
  .transport-info { font-size: 12px; color: var(--color-font-secondary); }


</style>
