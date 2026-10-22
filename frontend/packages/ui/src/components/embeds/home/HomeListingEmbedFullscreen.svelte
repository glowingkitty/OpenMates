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
  import { text } from '../../../i18n/translations';
  import { homeListingContent, homeNumber, homeObject, homeImages, homeBoolean, homeApproximate, homeMapGeometry, homeMapLabel, homeEvidence } from './homeListingData';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { authStore } from '../../../stores/authStore';
  import { appSettingsMemoriesStore } from '../../../stores/appSettingsMemoriesStore';
  import { findSavedEmbedMemoryEntry, forgetEmbedMemory, getEmbedIdFromContentRef, promptToSaveEmbedMemory, saveEmbedMemory } from '../../../services/savedEmbedMemoryService';
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

  // Extract fields from data.decodedContent.
  // Must be $derived so it updates when navigating between results (prev/next).
  // Handles both direct fields and flat TOON format from _flatten_for_toon_tabular.
  let dc = $derived(homeListingContent(data.decodedContent));
  let url = $derived(typeof dc.url === 'string' ? dc.url : '');
  let title = $derived(typeof dc.title === 'string' ? dc.title : undefined);
  let price_label = $derived(typeof dc.price_label === 'string' ? dc.price_label : undefined);
  let size_sqm = $derived(homeNumber(dc.size_sqm));
  let rooms = $derived(homeNumber(dc.rooms));
  let address = $derived(typeof dc.address === 'string' ? dc.address : undefined);
  let image_url = $derived(typeof dc.image_url === 'string' ? dc.image_url : undefined);
  let provider = $derived(typeof dc.provider === 'string' ? dc.provider : undefined);
  let listing_type = $derived(typeof dc.listing_type === 'string' ? dc.listing_type : undefined);
  let available_from = $derived(typeof dc.available_from === 'string' ? dc.available_from : undefined);
  let latitude = $derived(homeNumber(dc.latitude));
  let longitude = $derived(homeNumber(dc.longitude));

  let imageIndex = $state(0);
  let failedImages = $state<string[]>([]);
  let images = $derived(homeImages(dc.image_urls, image_url));
  let activeImage = $derived(images[imageIndex]);
  let displayTitle = $derived(title || $text('home_listing.listing'));
  let approximate = $derived(homeApproximate(dc));
  let amenities = $derived(homeObject(dc.amenities));
  let evidence = $derived(homeObject(dc.match_evidence));
  let visual = $derived(homeObject(dc.visual_assessment));
  let neighborhood = $derived(homeObject(dc.neighborhood));
  let matchAmenities = $derived(Object.entries(homeObject(evidence.amenities)));
  let photoFeatures = $derived(Object.entries(homeObject(visual.features)));
  let neighborhoodCategories = $derived(Object.entries(homeObject(neighborhood.features)));
  function featureLabel(key: string): string {
    return [...amenityKeys, 'water', 'park', 'transit', 'groceries', 'school'].includes(key) ? $text(`home_listing.${key}`) : key.replaceAll('_', ' ');
  }
  const readableStatuses = ['confirmed', 'possible', 'conflicting', 'unknown', 'unavailable', 'unconfirmed', 'partial', 'evaluated', 'visible', 'not_visible', 'uncertain', 'present', 'absent', 'no_features_returned', 'not_checked', 'ok'];
  function statusLabel(value: unknown): string {
    return typeof value === 'string' && readableStatuses.includes(value) ? $text(`home_listing.status_${value}`) : $text('home_listing.unknown');
  }
  function yesNo(value: unknown): string {
    return homeBoolean(value) === true ? $text('home_listing.yes') : homeBoolean(value) === false ? $text('home_listing.no') : $text('home_listing.unknown');
  }
  function neighborhoodPlaces(value: unknown): Record<string, unknown>[] {
    return (Array.isArray(value) ? value : []).map(homeObject);
  }
  function checkedDate(value: unknown): string {
    return typeof value === 'string' && !Number.isNaN(Date.parse(value)) ? value.slice(0, 10) : $text('home_listing.unknown');
  }
  function distanceValue(place: Record<string, unknown>): number | undefined {
    const distance = homeNumber(place.distance_m);
    return !approximate && ['shoreline_geometry', 'feature_geometry', 'representative_point'].includes(String(place.distance_method)) && place.location_precision === 'building' && distance !== undefined && distance >= 0 ? distance : undefined;
  }
  function distanceLabel(place: Record<string, unknown>, category: string): string {
    if (distanceValue(place) === undefined) return $text(category === 'water' ? 'home_listing.shoreline_unknown' : 'home_listing.distance_unknown');
    if (place.distance_method === 'shoreline_geometry' && category === 'water') return $text('home_listing.shoreline_distance');
    return $text(place.distance_method === 'representative_point' ? 'home_listing.point_distance' : 'home_listing.geometry_distance');
  }
  function walkingMinutes(place: Record<string, unknown>): number | undefined {
    const minutes = homeNumber(place.walk_minutes);
    return !approximate && place.location_precision === 'building' && place.walk_status === 'routed' && minutes !== undefined && minutes >= 0 ? minutes : undefined;
  }
  function amenityValue(key: string): boolean | undefined { return homeBoolean(dc[key]) ?? homeBoolean(amenities[key]); }
  const amenityKeys = ['balcony', 'furnished', 'elevator', 'garden', 'terrace', 'parking', 'pets_allowed'];
  const detailKeys = ['price', 'price_type', 'cold_rent_eur', 'warm_rent_eur', 'utilities_eur', 'heating_costs_eur', 'floor', 'available_from', 'available_to', 'deposit'];
  $effect(() => { void dc; imageIndex = 0; failedImages = []; });
  function navigateImage(offset: number) { imageIndex = (imageIndex + offset + images.length) % images.length; }
  function galleryKey(event: KeyboardEvent) {
    if (event.key === 'ArrowRight') { event.preventDefault(); navigateImage(1); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); navigateImage(-1); }
    if (event.key === 'Home') { event.preventDefault(); imageIndex = 0; }
    if (event.key === 'End') { event.preventDefault(); imageIndex = images.length - 1; }
  }
  /** Extract hostname for CTA button label */
  let hostname = $derived.by(() => {
    try {
      return new URL(url).hostname.replace('www.', '');
    } catch {
      return provider || 'listing';
    }
  });

  let geometry = $derived(homeMapGeometry(dc));
  let mapCenter = $derived(geometry ? {lat: geometry.lat, lon: geometry.lon} : undefined);
  let mapMarkers = $derived(geometry ? [{...geometry, homeLocation: true,
    testId: geometry.radiusM ? 'home-location-area' : 'home-location-pin',
    label: `${title || address || ''} · ${homeMapLabel(geometry, $text)}`} ] : []);
  let locationArea = $derived(homeObject(homeObject(dc.location).area));

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
    promptToSaveEmbedMemory(buildSaveConfig());
  }

  function parseAvailableFromDate(value: string | undefined): string | null {
    if (!value) return null;
    const germanDateMatch = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
    if (germanDateMatch) {
      const [, day, month, year] = germanDateMatch;
      return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}T09:00:00`;
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }

  function buildSaveConfig() {
    const saveTitle = displayTitle || 'Listing';
    return {
      kind: 'home_listing' as const,
      appId: 'home',
      itemType: 'saved_listings',
      itemKey: `saved_listings.${url || saveTitle}`,
      title: saveTitle,
      reminderDateTime: parseAvailableFromDate(available_from),
      reminderPromptTitle: saveTitle,
      itemValue: {
        embed_id: embedId || data.focusChildEmbedId || getEmbedIdFromContentRef(data.attrs?.contentRef),
        title: saveTitle,
        url,
        provider: provider || hostname,
        price_label: price_label || '',
        address: address || '',
        available_from: available_from || '',
        notes: [sizeDisplay, roomsDisplay, typeDisplay].filter(Boolean).join(' · '),
      },
    };
  }

  let saveConfig = $derived(buildSaveConfig());
  let savedMemoryEntry = $derived(findSavedEmbedMemoryEntry($appSettingsMemoriesStore, saveConfig));

  function handleToggleSavedListing() {
    if (savedMemoryEntry) {
      forgetEmbedMemory(saveConfig);
      return;
    }
    saveEmbedMemory(saveConfig);
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
  mapZoom={dc.location_precision === 'city' ? 10 : dc.location_precision === 'district' ? 12 : 14}
  {mapMarkers}
>
  {#snippet embedHeaderCta()}
    <div class="embed-header-cta-group">
      {#if $authStore.isAuthenticated}
        <EmbedHeaderCtaButton label={savedMemoryEntry ? 'Forget' : 'Add memory'} variant={savedMemoryEntry ? 'destructive' : 'secondary'} onclick={handleToggleSavedListing} testId="save-embed-cta" />
      {/if}
      {#if url}
        <EmbedHeaderCtaButton label="Open on {hostname}" onclick={handleOpenOnPlatform} testId="external-provider-cta" />
      {/if}
    </div>
  {/snippet}

  {#snippet detailContent(_ctx)}
    <section class="gallery" aria-label={$text('home_listing.photos')} data-testid="home-gallery">
      {#if images.length}
        <div class="gallery-stage">
          {#if failedImages.includes(activeImage)}
            <p role="status">{$text('home_listing.photo_unavailable')}</p>
          {:else}
            <img src={proxyImage(activeImage, MAX_WIDTH_HEADER_IMAGE)} alt={`${displayTitle} — ${imageIndex + 1} / ${images.length}`} class="listing-image" data-testid="home-gallery-image" onerror={(event) => { failedImages = [...failedImages, activeImage]; handleImageError(event.currentTarget); }} />
          {/if}
        </div>
        <div class="gallery-controls">
          <button type="button" onclick={() => navigateImage(-1)} aria-label={$text('home_listing.previous_photo')}>←</button>
          <span aria-live="polite" data-testid="home-gallery-counter">{imageIndex + 1} / {images.length}</span>
          <button type="button" onclick={() => navigateImage(1)} aria-label={$text('home_listing.next_photo')}>→</button>
        </div>
        <div class="gallery-thumbnails" role="group" aria-label={$text('home_listing.photos')}>
          {#each images as image, index}
            <button type="button" class:selected={imageIndex === index} aria-label={`${$text('home_listing.photo')} ${index + 1}`} aria-pressed={imageIndex === index} onkeydown={galleryKey} onclick={() => imageIndex = index}>
              <img src={proxyImage(image, 160)} alt="" loading="lazy" />
            </button>
          {/each}
        </div>
      {:else}
        <p>{$text('home_listing.no_photos')}</p>
      {/if}
      {#if dc.gallery_status !== 'complete'}<p class="uncertainty">{$text('home_listing.partial_gallery')}</p>{/if}
    </section>

    <!-- Address -->
    {#if address}
      <div class="listing-section">
        <div class="section-label">{$text('home_listing.location_address')}</div>
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

    {#if dc.enrichment_warnings || dc.warnings}
      <p class="uncertainty" role="status">{homeEvidence(dc.enrichment_warnings ?? dc.warnings)}</p>
    {/if}
    <section class="listing-section" data-testid="home-location-evidence">
      <h3>{$text('home_listing.location')}</h3>
      <p>{geometry ? geometry.radiusM ? $text('home_listing.approximate') : $text('home_listing.building') : latitude !== undefined && longitude !== undefined ? $text('home_listing.approximate') : $text('home_listing.no_location')}</p>
      <p>{homeEvidence(dc.location_precision)} · {homeEvidence(dc.location_source)}</p>
      {#if geometry?.radiusM}
        <p data-testid="home-location-area-label">{homeMapLabel(geometry, $text)}</p>
        <p>{homeEvidence(locationArea.source)}</p>
        {#if locationArea.anchor_name}<p>{homeEvidence(locationArea.anchor_name)}</p>{/if}
        {#if locationArea.evidence_quote}<blockquote>{homeEvidence(locationArea.evidence_quote)}</blockquote>{/if}
      {:else if approximate && latitude !== undefined && longitude !== undefined}
        <p>{$text('home_listing.area_unavailable')}</p>
      {/if}
      {#if approximate}<p class="uncertainty">{$text('home_listing.location_warning')}</p>{/if}
    </section>
    {#if typeof dc.description === 'string' && dc.description}
      <section class="listing-section"><h3>{$text('home_listing.description')}</h3><p class="description">{dc.description}</p></section>
    {/if}
    <section class="listing-section" data-testid="home-listing-facts">
      <h3>{$text('home_listing.details')}</h3>
      <dl>{#each detailKeys as key}<div><dt>{$text(`home_listing.${key}`)}</dt><dd>{homeEvidence(dc[key])}{key.endsWith('_eur') && homeNumber(dc[key]) !== undefined ? ' EUR' : ''}</dd></div>{/each}</dl>
    </section>
    <section class="listing-section" data-testid="home-amenities">
      <h3>{$text('home_listing.amenities')}</h3>
      <dl>{#each amenityKeys as key}<div><dt>{$text(`home_listing.${key}`)}</dt><dd>{amenityValue(key) === true ? $text('home_listing.yes') : amenityValue(key) === false ? $text('home_listing.no') : $text('home_listing.unknown')}</dd></div>{/each}</dl>
    </section>
    <section class="listing-section" data-testid="home-match-evidence">
      <h3>{$text('home_listing.match_evidence')}</h3>
      {#if provider}<p class="uncertainty">{provider} · {$text('home_listing.advertised_evidence')}</p>{/if}
      <p>{statusLabel(evidence.status)}</p>
      {#each matchAmenities as [key, rawMatch]}
        {@const match = homeObject(rawMatch)}
        <article class="evidence-card">
          <h4>{featureLabel(key)}</h4>
          <dl>
            <div><dt>{$text('home_listing.match_status')}</dt><dd>{statusLabel(match.status)}</dd></div>
            {#if match.expectation === 'absent'}<div><dt>{$text('home_listing.requirement')}</dt><dd>{$text('home_listing.status_absent')}</dd></div>{/if}
            <div data-testid="home-advertised-evidence"><dt>{$text('home_listing.advertised_fact')}</dt><dd>{yesNo(match.advertised)}</dd></div>
            <div><dt>{$text('home_listing.listing_text')}</dt><dd>{statusLabel(match.text_status)}</dd></div>
            <div><dt>{$text('home_listing.photo_evidence')}</dt><dd>{statusLabel(match.visual_status)}</dd></div>
          </dl>
        </article>
      {/each}
    </section>
    <section class="listing-section" data-testid="home-visual-evidence">
      <h3>{$text('home_listing.visual_evidence')}</h3>
      <p class="uncertainty">{$text('home_listing.assessment_warning')}</p>
      <p>{statusLabel(visual.status)} · {homeNumber(visual.photo_count) ?? 0} / {homeNumber(visual.total_photo_count) ?? images.length} {$text('home_listing.photos_assessed')}</p>
      <dl>{#each photoFeatures as [key, rawFeature]}{@const feature = homeObject(rawFeature)}<div><dt>{featureLabel(key)}</dt><dd>{statusLabel(feature.status)}</dd></div>{/each}</dl>
    </section>
    <section class="listing-section" data-testid="home-neighborhood-evidence">
      <h3>{$text('home_listing.neighborhood')}</h3>
      <p>{statusLabel(neighborhood.status)}</p>
      <p class="uncertainty">{$text('home_listing.source')}: {typeof neighborhood.source === 'string' ? neighborhood.source : $text('home_listing.unknown')} · {$text('home_listing.checked')}: {checkedDate(neighborhood.checked_at)}</p>
      {#each neighborhoodCategories as [category, rawPlaces]}
        {@const places = neighborhoodPlaces(rawPlaces)}
        {@const coverage = homeObject(homeObject(neighborhood.coverage)[category])}
        <div class="neighborhood-category" data-testid="home-neighborhood-category">
          <h4>{featureLabel(category)}</h4>
          <p class="uncertainty">{statusLabel(coverage.status)} · {$text('home_listing.limited_coverage')}</p>
          {#each places as place}
            <article class="evidence-card" data-testid="home-nearby-place">
              <h5>{typeof place.name === 'string' ? place.name : featureLabel(category)}</h5>
              <p data-testid="home-place-distance">{distanceLabel(place, category)}{distanceValue(place) !== undefined ? `: ${distanceValue(place)} m` : ''}</p>
              <p data-testid="home-place-walking">{walkingMinutes(place) !== undefined ? `${$text('home_listing.routed_walk')}: ${walkingMinutes(place)} ${$text('home_listing.minutes')}` : $text('home_listing.walking_unknown')}</p>
              <p class="uncertainty">{$text('home_listing.source')}: {typeof place.source === 'string' ? place.source : typeof neighborhood.source === 'string' ? neighborhood.source : $text('home_listing.unknown')} · {$text('home_listing.checked')}: {checkedDate(place.checked_at ?? neighborhood.checked_at)}</p>
            </article>
          {:else}
            <p>{$text('home_listing.no_nearby_evidence')}</p>
          {/each}
        </div>
      {/each}
    </section>
  {/snippet}
</EntryWithMapTemplate>

<style>
  .gallery { min-width: 0; }
  .gallery-stage { min-height: 160px; background: var(--color-grey-10); border-radius: var(--radius-5); display: grid; place-items: center; }
  .gallery-controls { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-4); margin-block: var(--spacing-3); }
  .gallery button { background: var(--color-grey-10); color: var(--color-font-primary); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); min-width: 40px; min-height: 40px; padding: var(--spacing-2); cursor: pointer; }
  .gallery button:hover { background: var(--color-grey-20); }
  .gallery button:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .gallery-thumbnails { display: flex; gap: var(--spacing-3); overflow-x: auto; padding: var(--spacing-2); }
  .gallery-thumbnails button { flex: 0 0 64px; height: 56px; }
  .gallery-thumbnails .selected { border: 2px solid var(--color-button-primary); }
  .gallery-thumbnails img { width: 100%; height: 100%; object-fit: cover; }
  h3, h4, h5, p { margin: 0; }
  h4, h5 { font-size: .9375rem; font-weight: 600; }
  .evidence-card, .neighborhood-category { display: flex; flex-direction: column; gap: var(--spacing-3); }
  .evidence-card { padding: var(--spacing-4); background: var(--color-grey-10); border-radius: var(--radius-4); }
  h3 { font-size: 1rem; }
  p, dd { font-size: .875rem; line-height: 1.6; overflow-wrap: anywhere; }
  .description { white-space: pre-wrap; }
  dl { display: grid; gap: var(--spacing-3); margin: 0; }
  dl > div { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.5fr); gap: var(--spacing-4); }
  dt { font-size: .8125rem; color: var(--color-font-tertiary); }
  dd { margin: 0; }
  .uncertainty { font-size: .8125rem; color: var(--color-font-tertiary); }

  .listing-image {
    width: 100%;
    height: 260px;
    object-fit: contain;
    border-radius: var(--radius-5);
  }

  .listing-meta-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--spacing-4);
  }

  .listing-meta-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .listing-type-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: var(--color-app-home-start);
    color: var(--color-grey-0); /* intentional: always white on brand colour */
  }

  .listing-source-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 500;
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
    border: 1px solid var(--color-grey-25);
  }

  .listing-section {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
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
