<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedFullscreen.svelte

  Fullscreen view for Travel Search Stays skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with skill label and "via {provider}"
  - Grid of TravelStayEmbedPreview cards with price/rating/amenity data
  - Cheapest 20% threshold highlighting
  - Drill-down: clicking a card opens TravelStayEmbedFullscreen overlay with sibling nav

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import TravelStayEmbedPreview from './TravelStayEmbedPreview.svelte';
  import TravelStayEmbedFullscreen from './TravelStayEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /**
   * Stay result interface (transformed from decoded child embed content)
   */
  interface StayResult {
    embed_id: string;
    type?: string;
    name?: string;
    description?: string;
    property_type?: string;
    link?: string;
    property_token?: string;
    latitude?: number;
    longitude?: number;
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
    images?: Array<{ thumbnail?: string; original_image?: string }>;
    thumbnail?: string;
    nearby_places?: Array<{ name?: string; transportations?: Array<{ type?: string; duration?: string }> }>;
    eco_certified?: boolean;
    free_cancellation?: boolean;
    hash?: string;
    gps_coordinates?: { latitude?: number; longitude?: number };
  }

  interface Props {
    query?: string;
    provider?: string;
    embedIds?: string | string[];
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    errorMessage?: string;
    results?: unknown[];
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
    query: queryProp,
    provider: providerProp,
    embedIds,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
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

  // Local reactive state for streaming updates
  let localQuery = $state('');
  let localProvider = $state('Google');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');

  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Google';
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });

  let provider = $derived(localProvider);
  let legacyResults = $derived(localResults);
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  // =========================================================================
  // TOON Reconstruction Helpers
  // =========================================================================

  function reconstructStringArray(content: Record<string, unknown>, prefix: string): string[] {
    if (Array.isArray(content[prefix])) return content[prefix] as string[];
    const arr: string[] = [];
    for (let i = 0; i < 50; i++) {
      const val = content[`${prefix}_${i}`];
      if (typeof val === 'string') arr.push(val);
      else break;
    }
    return arr;
  }

  function reconstructImages(content: Record<string, unknown>): Array<{ thumbnail?: string; original_image?: string }> {
    if (Array.isArray(content.images)) {
      return (content.images as Record<string, unknown>[]).map(img => ({
        thumbnail: img.thumbnail as string | undefined,
        original_image: img.original_image as string | undefined,
      }));
    }
    const images: Array<{ thumbnail?: string; original_image?: string }> = [];
    for (let i = 0; i < 20; i++) {
      const thumb = content[`images_${i}_thumbnail`];
      const orig = content[`images_${i}_original_image`];
      if (thumb || orig) {
        images.push({ thumbnail: thumb as string | undefined, original_image: orig as string | undefined });
      } else break;
    }
    return images;
  }

  function reconstructNearbyPlaces(content: Record<string, unknown>): Array<{ name?: string; transportations?: Array<{ type?: string; duration?: string }> }> {
    if (Array.isArray(content.nearby_places)) {
      return (content.nearby_places as Record<string, unknown>[]).map(place => ({
        name: place.name as string | undefined,
        transportations: Array.isArray(place.transportations)
          ? (place.transportations as Record<string, unknown>[]).map(t => ({
              type: t.type as string | undefined,
              duration: t.duration as string | undefined,
            }))
          : undefined,
      }));
    }
    const places: Array<{ name?: string; transportations?: Array<{ type?: string; duration?: string }> }> = [];
    for (let i = 0; i < 10; i++) {
      const name = content[`nearby_places_${i}_name`];
      if (name === undefined && content[`nearby_places_${i}_transportations_0_type`] === undefined) break;
      const transports: Array<{ type?: string; duration?: string }> = [];
      for (let j = 0; j < 10; j++) {
        const tType = content[`nearby_places_${i}_transportations_${j}_type`];
        const tDuration = content[`nearby_places_${i}_transportations_${j}_duration`];
        if (tType || tDuration) transports.push({ type: tType as string | undefined, duration: tDuration as string | undefined });
        else break;
      }
      places.push({ name: name as string | undefined, transportations: transports.length > 0 ? transports : undefined });
    }
    return places;
  }

  // =========================================================================
  // Child Embed Transformer
  // =========================================================================

  function transformToStayResult(embedId: string, content: Record<string, unknown>): StayResult {
    return {
      embed_id: embedId,
      type: (content.type as string) || 'stay',
      name: content.name as string | undefined,
      description: content.description as string | undefined,
      property_type: content.property_type as string | undefined,
      link: content.link as string | undefined,
      property_token: content.property_token as string | undefined,
      latitude: content.latitude as number | undefined,
      longitude: content.longitude as number | undefined,
      hotel_class: content.hotel_class as number | undefined,
      overall_rating: content.overall_rating as number | undefined,
      reviews: content.reviews as number | undefined,
      rate_per_night: content.rate_per_night as string | undefined,
      extracted_rate_per_night: content.extracted_rate_per_night as number | undefined,
      total_rate: content.total_rate as string | undefined,
      extracted_total_rate: content.extracted_total_rate as number | undefined,
      currency: (content.currency as string) || 'EUR',
      check_in_time: content.check_in_time as string | undefined,
      check_out_time: content.check_out_time as string | undefined,
      amenities: reconstructStringArray(content, 'amenities'),
      images: reconstructImages(content),
      thumbnail: content.thumbnail as string | undefined,
      nearby_places: reconstructNearbyPlaces(content),
      eco_certified: content.eco_certified === true || content.eco_certified === 'true',
      free_cancellation: content.free_cancellation === true || content.free_cancellation === 'true',
      hash: content.hash as string | undefined,
    };
  }

  /**
   * Transform legacy inline results (backwards compat).
   * Handles nested grouped results: [{id, results: [...]}]
   */
  function transformLegacyResults(results: unknown[]): StayResult[] {
    if (!results || results.length === 0) return [];
    const firstItem = results[0] as Record<string, unknown>;
    let flat = results;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: unknown[] = [];
      for (const entry of results as Array<{ id?: string; results?: unknown[] }>) {
        if (entry.results && Array.isArray(entry.results)) flattened.push(...entry.results);
      }
      flat = flattened;
    }
    return (flat as Array<Record<string, unknown>>).map((r, i) => transformToStayResult(`legacy-${i}`, r));
  }

  /**
   * Calculate cheapest 20% price threshold for highlighting.
   */
  function getCheapestThreshold(results: StayResult[]): number {
    const prices = results
      .filter(r => r.extracted_rate_per_night != null && r.extracted_rate_per_night > 0)
      .map(r => r.extracted_rate_per_night!)
      .sort((a, b) => a - b);
    if (prices.length === 0) return 0;
    const idx = Math.max(0, Math.ceil(prices.length * 0.2) - 1);
    return prices[idx];
  }

  /**
   * Get first thumbnail image URL for a property.
   */
  function getThumbnail(stay: StayResult): string | undefined {
    if (stay.thumbnail) return stay.thumbnail;
    if (stay.images && stay.images.length > 0) return stay.images[0].thumbnail || stay.images[0].original_image;
    return undefined;
  }

  /**
   * Handle embed data updates during streaming.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) embedIdsOverride = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }

  // Track all loaded results for cheapest threshold calculation
  let allLoadedResults = $state<StayResult[]>([]);
  let cheapestThreshold = $derived(getCheapestThreshold(allLoadedResults));
</script>

<SearchResultsTemplate
  appId="travel"
  skillId="search_stays"
  embedHeaderTitle={$text('app_skills.travel.search_stays')}
  embedHeaderSubtitle={viaProvider}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToStayResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  onResultsLoaded={(results) => { allLoadedResults = results; }}
  minCardWidth="280px"
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, index, onSelect })}
    {@const isCheapest = cheapestThreshold > 0 && result.extracted_rate_per_night != null && result.extracted_rate_per_night <= cheapestThreshold}
    <TravelStayEmbedPreview
      id={result.embed_id || result.hash || `stay-${index}`}
      name={result.name}
      thumbnail={getThumbnail(result)}
      hotelClass={result.hotel_class}
      overallRating={result.overall_rating}
      reviews={result.reviews}
      currency={result.currency}
      ratePerNight={result.extracted_rate_per_night}
      totalRate={result.extracted_total_rate}
      amenities={result.amenities?.slice(0, 3)}
      {isCheapest}
      ecoCertified={result.eco_certified}
      freeCancellation={result.free_cancellation}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <TravelStayEmbedFullscreen
      stay={nav.result}
      onClose={nav.onClose}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>
