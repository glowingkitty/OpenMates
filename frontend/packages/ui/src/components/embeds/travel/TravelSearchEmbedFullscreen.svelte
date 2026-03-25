<!--
  frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedFullscreen.svelte

  Fullscreen view for Travel Search Connections skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with derived route summary, date, connection count, price range
  - Connection preview cards in a responsive grid with cheapest 20% highlighting
  - Drill-down: clicking a card opens TravelConnectionEmbedFullscreen overlay with sibling nav

  Complex header: route summary, departure date, connection count, "via {provider}",
  and "from EUR {price}" are all derived from loaded child results.

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import TravelConnectionEmbedPreview from './TravelConnectionEmbedPreview.svelte';
  import TravelConnectionEmbedFullscreen from './TravelConnectionEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /** Layover data between segments */
  interface LayoverData {
    airport: string;
    airport_code?: string;
    duration?: string;
    duration_minutes?: number;
    overnight?: boolean;
  }

  /** Segment data within a leg */
  interface SegmentData {
    carrier: string;
    carrier_code?: string;
    number?: string;
    departure_station: string;
    departure_time: string;
    departure_latitude?: number;
    departure_longitude?: number;
    arrival_station: string;
    arrival_time: string;
    arrival_latitude?: number;
    arrival_longitude?: number;
    duration: string;
    airplane?: string;
    airline_logo?: string;
    legroom?: string;
    travel_class?: string;
    extensions?: string[];
    often_delayed?: boolean;
  }

  /** Leg data for fullscreen detail view */
  interface LegData {
    leg_index: number;
    origin: string;
    destination: string;
    departure: string;
    arrival: string;
    duration: string;
    stops: number;
    segments: SegmentData[];
    layovers?: LayoverData[];
  }

  /**
   * Connection result interface (transformed from child embeds)
   */
  interface ConnectionResult {
    embed_id: string;
    type?: string;
    transport_method?: string;
    trip_type?: string;
    total_price?: string;
    currency?: string;
    bookable_seats?: number;
    last_ticketing_date?: string;
    booking_url?: string;
    booking_provider?: string;
    booking_token?: string;
    booking_context?: Record<string, string>;
    origin?: string;
    destination?: string;
    departure?: string;
    arrival?: string;
    duration?: string;
    stops?: number;
    carriers?: string[];
    carrier_codes?: string[];
    hash?: string;
    legs?: LegData[];
    airline_logo?: string;
    co2_kg?: number;
    co2_typical_kg?: number;
    co2_difference_percent?: number;
  }

  interface Props {
    query?: string;
    provider?: string;
    embedIds?: string | string[];
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    errorMessage?: string;
    results?: ConnectionResult[];
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
    initialChildEmbedId?: string;
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
    onShowChat,
    initialChildEmbedId
  }: Props = $props();

  // Local reactive state for streaming updates
  let localQuery = $state('');
  let localProvider = $state('');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let storeResolved = $state(false);
  let localErrorMessage = $state('');

  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || '';
      localProvider = providerProp || 'Google';
      localResults = resultsProp || [];
      localStatus = statusProp || 'finished';
      localErrorMessage = errorMessageProp || '';
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let legacyResults = $derived(localResults);
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  // Track loaded results for header derivation
  let headerResults = $state<ConnectionResult[]>([]);

  // =========================================================================
  // Derived Header
  // =========================================================================

  let headerRouteSummary = $derived.by(() => {
    if (headerResults.length > 0) {
      const first = headerResults[0];
      if (first.origin && first.destination) return `${first.origin} \u2192 ${first.destination}`;
    }
    return query || '';
  });

  let headerDateDisplay = $derived.by(() => {
    if (headerResults.length === 0) return '';
    const first = headerResults[0];
    if (!first.departure) return '';
    try {
      const date = new Date(first.departure);
      return date.toLocaleDateString([], { weekday: 'short', month: 'long', day: 'numeric', year: 'numeric' });
    } catch { return ''; }
  });

  let headerPriceInfo = $derived.by(() => {
    if (headerResults.length === 0) return '';
    const prices = headerResults
      .filter(r => r.total_price)
      .map(r => parseFloat(r.total_price!))
      .filter(p => !isNaN(p));
    if (prices.length === 0) return '';
    const currency = headerResults[0]?.currency || 'EUR';
    const minPrice = Math.min(...prices);
    return `${$text('embeds.from')} ${currency} ${Math.round(minPrice)}`;
  });

  let headerSubtitle = $derived.by(() => {
    const count = headerResults.length;
    const parts: string[] = [];
    if (count > 0) {
      const countLabel = count === 1
        ? `1 ${$text('embeds.connection')}`
        : `${count} ${$text('embeds.connections')}`;
      parts.push(countLabel);
    }
    parts.push(viaProvider);
    if (headerPriceInfo) parts.push(headerPriceInfo);
    return parts.join('  \u00b7  ');
  });

  let headerTitle = $derived.by(() => {
    if (!headerRouteSummary) return query || '';
    if (headerDateDisplay) return `${headerRouteSummary}  \u00b7  ${headerDateDisplay}`;
    return headerRouteSummary;
  });

  // =========================================================================
  // TOON Reconstruction
  // =========================================================================

  function reconstructBookingContext(content: Record<string, unknown>): Record<string, string> | undefined {
    if (content.booking_context && typeof content.booking_context === 'object' && !Array.isArray(content.booking_context)) {
      return content.booking_context as Record<string, string>;
    }
    const contextKeys = ['departure_id', 'arrival_id', 'outbound_date', 'return_date', 'type', 'currency', 'gl', 'adults', 'travel_class'];
    const ctx: Record<string, string> = {};
    let found = false;
    for (const key of contextKeys) {
      const val = content[`booking_context_${key}`];
      if (val !== undefined && val !== null) { ctx[key] = String(val); found = true; }
    }
    return found ? ctx : undefined;
  }

  function reconstructLegs(content: Record<string, unknown>): LegData[] {
    const legs: LegData[] = [];
    for (let i = 0; i < 10; i++) {
      const origin = content[`legs_${i}_origin`];
      if (typeof origin !== 'string') break;
      legs.push({
        leg_index: (content[`legs_${i}_leg_index`] as number) ?? i,
        origin,
        destination: (content[`legs_${i}_destination`] as string) || '',
        departure: (content[`legs_${i}_departure`] as string) || '',
        arrival: (content[`legs_${i}_arrival`] as string) || '',
        duration: (content[`legs_${i}_duration`] as string) || '',
        stops: (content[`legs_${i}_stops`] as number) || 0,
        segments: reconstructSegments(content, i),
      });
    }
    return legs;
  }

  function reconstructSegments(content: Record<string, unknown>, legIndex: number): SegmentData[] {
    const segments: SegmentData[] = [];
    for (let j = 0; j < 10; j++) {
      const carrier = content[`legs_${legIndex}_segments_${j}_carrier`];
      if (typeof carrier !== 'string') break;
      segments.push({
        carrier,
        carrier_code: content[`legs_${legIndex}_segments_${j}_carrier_code`] as string | undefined,
        number: content[`legs_${legIndex}_segments_${j}_number`] as string | undefined,
        departure_station: (content[`legs_${legIndex}_segments_${j}_departure_station`] as string) || '',
        departure_time: (content[`legs_${legIndex}_segments_${j}_departure_time`] as string) || '',
        departure_latitude: content[`legs_${legIndex}_segments_${j}_departure_latitude`] as number | undefined,
        departure_longitude: content[`legs_${legIndex}_segments_${j}_departure_longitude`] as number | undefined,
        arrival_station: (content[`legs_${legIndex}_segments_${j}_arrival_station`] as string) || '',
        arrival_time: (content[`legs_${legIndex}_segments_${j}_arrival_time`] as string) || '',
        arrival_latitude: content[`legs_${legIndex}_segments_${j}_arrival_latitude`] as number | undefined,
        arrival_longitude: content[`legs_${legIndex}_segments_${j}_arrival_longitude`] as number | undefined,
        duration: (content[`legs_${legIndex}_segments_${j}_duration`] as string) || '',
        airplane: content[`legs_${legIndex}_segments_${j}_airplane`] as string | undefined,
        airline_logo: content[`legs_${legIndex}_segments_${j}_airline_logo`] as string | undefined,
        legroom: content[`legs_${legIndex}_segments_${j}_legroom`] as string | undefined,
        travel_class: content[`legs_${legIndex}_segments_${j}_travel_class`] as string | undefined,
        often_delayed: content[`legs_${legIndex}_segments_${j}_often_delayed`] as boolean | undefined,
      });
    }
    return segments;
  }

  function transformToConnectionResult(embedId: string, content: Record<string, unknown>): ConnectionResult {
    let legs: LegData[] = [];
    if (Array.isArray(content.legs)) {
      legs = (content.legs as Record<string, unknown>[]).map((leg, i) => ({
        leg_index: (leg.leg_index as number) ?? i,
        origin: (leg.origin as string) || '',
        destination: (leg.destination as string) || '',
        departure: (leg.departure as string) || '',
        arrival: (leg.arrival as string) || '',
        duration: (leg.duration as string) || '',
        stops: (leg.stops as number) || 0,
        segments: Array.isArray(leg.segments)
          ? (leg.segments as Record<string, unknown>[]).map(seg => ({
              carrier: (seg.carrier as string) || '',
              carrier_code: seg.carrier_code as string | undefined,
              number: seg.number as string | undefined,
              departure_station: (seg.departure_station as string) || '',
              departure_time: (seg.departure_time as string) || '',
              departure_latitude: seg.departure_latitude as number | undefined,
              departure_longitude: seg.departure_longitude as number | undefined,
              arrival_station: (seg.arrival_station as string) || '',
              arrival_time: (seg.arrival_time as string) || '',
              arrival_latitude: seg.arrival_latitude as number | undefined,
              arrival_longitude: seg.arrival_longitude as number | undefined,
              duration: (seg.duration as string) || '',
              airplane: seg.airplane as string | undefined,
              airline_logo: seg.airline_logo as string | undefined,
              legroom: seg.legroom as string | undefined,
              travel_class: seg.travel_class as string | undefined,
              extensions: Array.isArray(seg.extensions) ? seg.extensions as string[] : undefined,
              often_delayed: seg.often_delayed as boolean | undefined,
            }))
          : reconstructSegments(content, i),
        layovers: Array.isArray(leg.layovers)
          ? (leg.layovers as Record<string, unknown>[]).map(lay => ({
              airport: (lay.airport as string) || '',
              airport_code: lay.airport_code as string | undefined,
              duration: lay.duration as string | undefined,
              duration_minutes: lay.duration_minutes as number | undefined,
              overnight: lay.overnight as boolean | undefined,
            }))
          : undefined,
      }));
    } else {
      legs = reconstructLegs(content);
    }

    let carriers: string[] = [];
    if (Array.isArray(content.carriers)) {
      carriers = content.carriers as string[];
    } else {
      for (let i = 0; i < 20; i++) {
        const c = content[`carriers_${i}`];
        if (typeof c === 'string') carriers.push(c);
        else break;
      }
    }

    let carrier_codes: string[] = [];
    if (Array.isArray(content.carrier_codes)) {
      carrier_codes = content.carrier_codes as string[];
    } else {
      for (let i = 0; i < 20; i++) {
        const cc = content[`carrier_codes_${i}`];
        if (typeof cc === 'string') carrier_codes.push(cc);
        else break;
      }
    }

    return {
      embed_id: embedId,
      type: (content.type as string) || 'connection',
      transport_method: (content.transport_method as string) || 'airplane',
      trip_type: (content.trip_type as string) || 'one_way',
      total_price: content.total_price as string | undefined,
      currency: (content.currency as string) || 'EUR',
      bookable_seats: content.bookable_seats as number | undefined,
      last_ticketing_date: content.last_ticketing_date as string | undefined,
      booking_url: content.booking_url as string | undefined,
      booking_provider: content.booking_provider as string | undefined,
      booking_token: content.booking_token as string | undefined,
      booking_context: reconstructBookingContext(content),
      origin: content.origin as string | undefined,
      destination: content.destination as string | undefined,
      departure: content.departure as string | undefined,
      arrival: content.arrival as string | undefined,
      duration: content.duration as string | undefined,
      stops: (content.stops as number) || 0,
      carriers,
      carrier_codes,
      hash: content.hash as string | undefined,
      legs,
      airline_logo: content.airline_logo as string | undefined,
      co2_kg: content.co2_kg as number | undefined,
      co2_typical_kg: content.co2_typical_kg as number | undefined,
      co2_difference_percent: content.co2_difference_percent as number | undefined,
    };
  }

  function transformLegacyResults(results: unknown[]): ConnectionResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) =>
      transformToConnectionResult(`legacy-${i}`, r)
    );
  }

  function getCheapestThreshold(results: ConnectionResult[]): number {
    const prices = results
      .filter(r => r.total_price)
      .map(r => parseFloat(r.total_price!))
      .filter(p => !isNaN(p))
      .sort((a, b) => a - b);
    if (prices.length === 0) return 0;
    const idx = Math.max(0, Math.ceil(prices.length * 0.2) - 1);
    return prices[idx];
  }

  let cheapestThreshold = $derived(getCheapestThreshold(headerResults));

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') {
      storeResolved = true;
    }
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) embedIdsOverride = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }

  // Also populate header results from legacy results when no embedIds are used.
  $effect(() => {
    if (localResults.length > 0 && headerResults.length === 0) {
      headerResults = transformLegacyResults(localResults);
    }
  });
</script>

<SearchResultsTemplate
  appId="travel"
  skillId="search_connections"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToConnectionResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  onResultsLoaded={(results) => { headerResults = results; }}
  {initialChildEmbedId}
  minCardWidth="260px"
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    <TravelConnectionEmbedPreview
      id={result.embed_id}
      price={result.total_price}
      currency={result.currency}
      transportMethod={result.transport_method}
      tripType={result.trip_type}
      origin={result.origin}
      destination={result.destination}
      departure={result.departure}
      arrival={result.arrival}
      duration={result.duration}
      stops={result.stops}
      carriers={result.carriers}
      carrierCodes={result.carrier_codes}
      bookableSeats={result.bookable_seats}
      isCheapest={cheapestThreshold > 0 && result.total_price != null && parseFloat(result.total_price) <= cheapestThreshold}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <TravelConnectionEmbedFullscreen
      connection={nav.result}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>

<style>
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
