<!--
  frontend/packages/ui/src/components/embeds/maps/MapsSearchEmbedFullscreen.svelte

  Fullscreen view for Maps Search skill embeds.
  Uses EntryWithMapTemplate so search results and map share the same fullscreen
  template contract as other map-style embeds.

  Displays:
  - Interactive map with markers for all place results
  - Scrollable list of MapLocationEmbedPreview cards
  - Child drill-down overlay with MapLocationEmbedFullscreen

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import MapLocationEmbedPreview from './MapLocationEmbedPreview.svelte';
  import MapLocationEmbedFullscreen from './MapLocationEmbedFullscreen.svelte';
  import type { ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import type { MapMarker } from '../EmbedLeafletMap.svelte';

  interface PlaceResult {
    embed_id: string;
    displayName?: string;
    formattedAddress?: string;
    location?: { latitude?: number; longitude?: number };
    rating?: number;
    userRatingCount?: number;
    websiteUri?: string;
    placeId?: string;
    placeType?: string;
    imageUrl?: string;
  }

  interface Props {
    /** Raw embed data — component extracts its own fields internally */
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
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
    onShowChat,
  }: Props = $props();

  // Extract fields from data prop
  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '');
  let provider = $derived(typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Google');
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let resultsProp = $derived(Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as PlaceResult[] : []);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  let selectedPlace = $state<PlaceResult | null>(null);
  let selectedIndex = $state(0);
  let loadedPlaces = $state<PlaceResult[]>([]);

  $effect(() => {
    loadedPlaces = transformLegacyResults(resultsProp);
  });

  function handleOpenPlace(place: PlaceResult, index: number) {
    selectedPlace = place;
    selectedIndex = index;
  }

  function handleClosePlace() {
    selectedPlace = null;
  }

  function handlePreviousPlace(places: PlaceResult[]) {
    if (selectedIndex <= 0) return;
    selectedIndex -= 1;
    selectedPlace = places[selectedIndex] ?? null;
  }

  function handleNextPlace(places: PlaceResult[]) {
    if (selectedIndex >= places.length - 1) return;
    selectedIndex += 1;
    selectedPlace = places[selectedIndex] ?? null;
  }

  function pickFirstString(...values: Array<unknown>): string | undefined {
    for (const value of values) {
      if (typeof value === 'string' && value.trim()) {
        return value;
      }
    }
    return undefined;
  }

  function pickFirstNumber(...values: Array<unknown>): number | undefined {
    for (const value of values) {
      if (typeof value === 'number' && Number.isFinite(value)) {
        return value;
      }
    }
    return undefined;
  }

  function transformToPlaceResult(
    childEmbedId: string,
    content: Record<string, unknown>
  ): PlaceResult {
    const nestedLocation = content.location as Record<string, unknown> | undefined;
    const latitude = pickFirstNumber(
      nestedLocation?.latitude,
      nestedLocation?.lat,
      content.location_latitude,
      content.location_lat,
      content.latitude,
      content.lat,
    );
    const longitude = pickFirstNumber(
      nestedLocation?.longitude,
      nestedLocation?.lon,
      nestedLocation?.lng,
      content.location_longitude,
      content.location_lon,
      content.location_lng,
      content.longitude,
      content.lon,
      content.lng,
    );

    const placeTypeValue = content.placeType || content.place_type;
    const placeType = typeof placeTypeValue === 'string'
      ? placeTypeValue
      : Array.isArray(content.types) && typeof content.types[0] === 'string'
        ? content.types[0]
        : undefined;

    return {
      embed_id: childEmbedId,
      displayName: pickFirstString(content.displayName, content.name),
      formattedAddress: pickFirstString(content.formattedAddress, content.formatted_address, content.address),
      location: latitude != null && longitude != null
        ? { latitude, longitude }
        : undefined,
      rating: pickFirstNumber(content.rating),
      userRatingCount: pickFirstNumber(content.userRatingCount, content.user_rating_count, content.reviews),
      websiteUri: pickFirstString(content.websiteUri, content.website_uri),
      placeId: pickFirstString(content.placeId, content.place_id),
      placeType,
      imageUrl: pickFirstString(content.imageUrl, content.image_url, content.photo_url),
    };
  }

  function transformLegacyResults(results: unknown[]): PlaceResult[] {
    return (results as Array<Record<string, unknown>>).map((result, index) =>
      transformToPlaceResult(`legacy-${index}`, result)
    );
  }

  function getPlaceResults(ctx: ChildEmbedContext): PlaceResult[] {
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as PlaceResult[];
    }
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return transformLegacyResults(ctx.legacyResults);
    }
    return [];
  }

  function handleChildrenLoaded(children: unknown[]) {
    loadedPlaces = children as PlaceResult[];

    if (!initialChildEmbedId) return;
    const idx = loadedPlaces.findIndex((place) => place.embed_id === initialChildEmbedId);
    if (idx !== -1) {
      handleOpenPlace(loadedPlaces[idx], idx);
    }
  }

  function buildMarkers(places: PlaceResult[]): MapMarker[] {
    return places
      .filter((place) => place.location?.latitude != null && place.location?.longitude != null)
      .map((place) => ({
        lat: place.location!.latitude!,
        lon: place.location!.longitude!,
        label: place.displayName,
      }));
  }

  function buildMapCenter(places: PlaceResult[]): { lat: number; lon: number } | undefined {
    const validPlaces = places.filter(
      (place) => place.location?.latitude != null && place.location?.longitude != null
    );
    if (validPlaces.length === 0) return undefined;

    const latitudes = validPlaces.map((place) => place.location!.latitude!);
    const longitudes = validPlaces.map((place) => place.location!.longitude!);

    return {
      lat: (Math.min(...latitudes) + Math.max(...latitudes)) / 2,
      lon: (Math.min(...longitudes) + Math.max(...longitudes)) / 2,
    };
  }

  let mapMarkers = $derived(buildMarkers(loadedPlaces));
  let mapCenter = $derived(buildMapCenter(loadedPlaces));
</script>

<EntryWithMapTemplate
  appId="maps"
  skillId="search"
  {onClose}
  currentEmbedId={embedId}
  skillIconName="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  {embedIds}
  childEmbedTransformer={transformToPlaceResult}
  legacyResults={resultsProp}
  onChildrenLoaded={handleChildrenLoaded}
  onAutoOpenChild={(index, children) => {
    const places = children as PlaceResult[];
    if (places[index]) handleOpenPlace(places[index], index);
  }}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  {mapCenter}
  mapZoom={12}
  mapMarkers={mapMarkers}
>
  {#snippet detailContent(ctx)}
    {@const places = getPlaceResults(ctx)}

    {#if ctx.isLoadingChildren}
      <div class="loading-state">
        <p>{$text('common.loading')}</p>
      </div>
    {:else if places.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results')}</p>
      </div>
    {:else}
      <div class="results-list">
        {#each places as place, index}
          {@const isSelected = selectedPlace?.embed_id === place.embed_id}
          <div
            class="result-item"
            class:selected={isSelected}
            role="button"
            tabindex="0"
            onclick={() => handleOpenPlace(place, index)}
            onkeydown={(event) => (event.key === 'Enter' || event.key === ' ') && handleOpenPlace(place, index)}
          >
            <MapLocationEmbedPreview
              id={place.embed_id}
              displayName={place.displayName}
              formattedAddress={place.formattedAddress}
              rating={place.rating}
              userRatingCount={place.userRatingCount}
              placeType={place.placeType}
              imageUrl={place.imageUrl}
              {isSelected}
              status="finished"
              isMobile={false}
              onFullscreen={() => handleOpenPlace(place, index)}
            />
          </div>
        {/each}
      </div>

      {#if selectedPlace}
        <ChildEmbedOverlay>
          <MapLocationEmbedFullscreen
            data={{ decodedContent: selectedPlace }}
            onClose={handleClosePlace}
            hasPreviousEmbed={selectedIndex > 0}
            hasNextEmbed={selectedIndex < places.length - 1}
            onNavigatePrevious={() => handlePreviousPlace(places)}
            onNavigateNext={() => handleNextPlace(places)}
          />
        </ChildEmbedOverlay>
      {/if}
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
  .results-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    overflow-y: auto;
    max-height: min(70dvh, 620px);
    padding-right: var(--spacing-1);
  }

  .result-item {
    cursor: pointer;
    border-radius: var(--radius-7);
    border: 2px solid transparent;
    transition: border-color var(--duration-fast) var(--easing-default);
    pointer-events: all;
  }

  .result-item:hover {
    border-color: var(--color-border);
  }

  .result-item.selected {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb, 0, 123, 255), 0.15);
  }

  .result-item:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }

  .result-item :global(.unified-embed-preview.desktop) {
    width: 100% !important;
    min-width: unset !important;
    max-width: unset !important;
  }

  .loading-state,
  .no-results {
    color: var(--color-font-secondary);
    font-size: 1rem;
    text-align: center;
    padding: var(--spacing-12) var(--spacing-4);
  }

  .results-list::-webkit-scrollbar {
    width: 6px;
  }

  .results-list::-webkit-scrollbar-track {
    background: transparent;
  }

  .results-list::-webkit-scrollbar-thumb {
    background: var(--color-border);
    border-radius: 3px;
  }

  .results-list::-webkit-scrollbar-thumb:hover {
    background: var(--color-grey-60);
  }

  @container fullscreen (max-width: 600px) {
    .results-list {
      max-height: none;
      padding-right: 0;
    }
  }
</style>
