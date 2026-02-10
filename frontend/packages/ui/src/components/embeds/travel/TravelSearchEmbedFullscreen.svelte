<!--
  frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedFullscreen.svelte
  
  Fullscreen view for Travel Search Connections skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.
  
  Shows:
  - Header with route summary and "via {provider}" formatting
  - Connection cards in a grid (auto-responsive columns)
  - Consistent BasicInfosBar at the bottom
  - Top bar with share and minimize buttons
  
  Child embeds are automatically loaded by UnifiedEmbedFullscreen from embedIds prop.
  
  Connection Fullscreen Navigation (Overlay Pattern):
  - Connection results grid is ALWAYS rendered (base layer)
  - When a connection card is clicked, TravelConnectionEmbedFullscreen renders as OVERLAY
  - When connection fullscreen is closed, overlay is removed revealing results beneath
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import TravelConnectionEmbedPreview from './TravelConnectionEmbedPreview.svelte';
  import TravelConnectionEmbedFullscreen from './TravelConnectionEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Connection result interface (transformed from child embeds)
   * Contains all data needed to display connection in both preview and fullscreen
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
    /** Full leg data for detailed fullscreen view */
    legs?: LegData[];
    /** Rich metadata from Google Flights */
    airline_logo?: string;
    co2_kg?: number;
    co2_typical_kg?: number;
    co2_difference_percent?: number;
  }
  
  /** Layover data between segments */
  interface LayoverData {
    airport: string;
    airport_code?: string;
    duration?: string;
    duration_minutes?: number;
    overnight?: boolean;
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
    /** Rich metadata from Google Flights */
    airplane?: string;
    airline_logo?: string;
    legroom?: string;
    travel_class?: string;
    extensions?: string[];
    often_delayed?: boolean;
  }
  
  /**
   * Props for travel search embed fullscreen
   */
  interface Props {
    /** Route summary query (e.g., "Munich → London") */
    query?: string;
    /** Search provider (e.g., 'Google') */
    provider?: string;
    /** Pipe-separated embed IDs or array of embed IDs for child connection embeds */
    embedIds?: string | string[];
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Optional error message */
    errorMessage?: string;
    /** Legacy: results array (used if embedIds not provided) */
    results?: ConnectionResult[];
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
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
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // Currently selected connection for fullscreen detail view
  let selectedConnection = $state<ConnectionResult | null>(null);
  
  // Local reactive state
  let localQuery = $state<string>(queryProp || '');
  let localProvider = $state<string>(providerProp || 'Google');
  let localEmbedIds = $state<string | string[] | undefined>(embedIds);
  let localResults = $state<unknown[]>(resultsProp || []);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>(statusProp || 'finished');
  let localErrorMessage = $state<string>(errorMessageProp || '');
  
  // Keep local state in sync with prop changes
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Google';
    localEmbedIds = embedIds;
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });
  
  // Derived state
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(localEmbedIds);
  let legacyResults = $derived(localResults);
  let status = $derived(localStatus);
  let fullscreenStatus = $derived(status === 'cancelled' ? 'error' : status);
  let errorMessage = $derived(localErrorMessage || ($text('chat.an_error_occured.text') || 'Processing failed.'));
  
  // Skill name from translations
  let skillName = $derived($text('app_skills.travel.search.text') || 'Search');
  
  // "via {provider}" text
  let viaProvider = $derived(
    `${$text('embeds.via.text') || 'via'} ${provider}`
  );
  
  /**
   * Transform raw embed content to ConnectionResult format.
   * Used by UnifiedEmbedFullscreen's childEmbedTransformer.
   * 
   * TOON encoding flattens nested objects, so legs_0_origin becomes a top-level key.
   * We need to reconstruct the legs array from the flattened keys.
   */
  function transformToConnectionResult(embedId: string, content: Record<string, unknown>): ConnectionResult {
    // Try to get legs data - could be already structured or TOON-flattened
    let legs: LegData[] = [];
    
    if (Array.isArray(content.legs)) {
      // Direct legs array (not TOON-flattened)
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
      // Try to reconstruct legs from TOON-flattened format (legs_0_origin, legs_0_destination, etc.)
      legs = reconstructLegs(content);
    }
    
    // Extract carriers - could be direct array or TOON-flattened
    let carriers: string[] = [];
    if (Array.isArray(content.carriers)) {
      carriers = content.carriers as string[];
    } else {
      // Reconstruct from TOON-flattened (carriers_0, carriers_1, etc.)
      for (let i = 0; i < 20; i++) {
        const c = content[`carriers_${i}`];
        if (typeof c === 'string') {
          carriers.push(c);
        } else {
          break;
        }
      }
    }
    
    // Extract carrier_codes - could be direct array or TOON-flattened
    let carrier_codes: string[] = [];
    if (Array.isArray(content.carrier_codes)) {
      carrier_codes = content.carrier_codes as string[];
    } else {
      for (let i = 0; i < 20; i++) {
        const cc = content[`carrier_codes_${i}`];
        if (typeof cc === 'string') {
          carrier_codes.push(cc);
        } else {
          break;
        }
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
  
  /**
   * Reconstruct booking_context dict from TOON-flattened content.
   * TOON flattening turns booking_context.departure_id → booking_context_departure_id.
   * If content already has a native booking_context object (non-TOON path), return it as-is.
   */
  function reconstructBookingContext(content: Record<string, unknown>): Record<string, string> | undefined {
    // If the content already has a native booking_context object, use it directly
    if (content.booking_context && typeof content.booking_context === 'object' && !Array.isArray(content.booking_context)) {
      return content.booking_context as Record<string, string>;
    }
    
    // Reconstruct from TOON-flattened keys: booking_context_departure_id, booking_context_arrival_id, etc.
    const contextKeys = [
      'departure_id', 'arrival_id', 'outbound_date', 'return_date',
      'type', 'currency', 'gl', 'adults', 'travel_class',
    ];
    const ctx: Record<string, string> = {};
    let found = false;
    for (const key of contextKeys) {
      const val = content[`booking_context_${key}`];
      if (val !== undefined && val !== null) {
        ctx[key] = String(val);
        found = true;
      }
    }
    return found ? ctx : undefined;
  }
  
  /**
   * Reconstruct legs array from TOON-flattened content.
   * TOON flattens nested objects: legs[0].origin → legs_0_origin
   */
  function reconstructLegs(content: Record<string, unknown>): LegData[] {
    const legs: LegData[] = [];
    for (let i = 0; i < 10; i++) {
      const origin = content[`legs_${i}_origin`];
      if (typeof origin !== 'string') break;
      
      legs.push({
        leg_index: (content[`legs_${i}_leg_index`] as number) ?? i,
        origin: origin,
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
  
  /**
   * Reconstruct segments array from TOON-flattened content for a given leg index.
   * legs[0].segments[0].carrier → legs_0_segments_0_carrier
   */
  function reconstructSegments(content: Record<string, unknown>, legIndex: number): SegmentData[] {
    const segments: SegmentData[] = [];
    for (let j = 0; j < 10; j++) {
      const carrier = content[`legs_${legIndex}_segments_${j}_carrier`];
      if (typeof carrier !== 'string') break;
      
      segments.push({
        carrier: carrier,
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
  
  /**
   * Transform legacy results to ConnectionResult format
   */
  function transformLegacyResults(results: unknown[]): ConnectionResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const result = transformToConnectionResult(`legacy-${i}`, r);
      return result;
    });
  }
  
  /**
   * Get connection results from context (children or legacy)
   */
  function getConnectionResults(ctx: ChildEmbedContext): ConnectionResult[] {
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as ConnectionResult[];
    }
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return transformLegacyResults(ctx.legacyResults);
    }
    return [];
  }
  
  /**
   * Calculate the cheapest 20% price threshold for highlighting
   */
  function getCheapestThreshold(results: ConnectionResult[]): number {
    const prices = results
      .filter(r => r.total_price)
      .map(r => parseFloat(r.total_price!))
      .filter(p => !isNaN(p))
      .sort((a, b) => a - b);
    if (prices.length === 0) return 0;
    // Bottom 20% index (at least 1 result)
    const idx = Math.max(0, Math.ceil(prices.length * 0.2) - 1);
    return prices[idx];
  }
  
  /**
   * Format date for header display (e.g., "March 7, 2026")
   */
  function formatHeaderDate(isoString?: string): string {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString([], { month: 'long', day: 'numeric', year: 'numeric' });
    } catch {
      return '';
    }
  }
  
  /**
   * Handle connection card click - shows detail fullscreen
   */
  function handleConnectionFullscreen(connection: ConnectionResult) {
    console.debug('[TravelSearchEmbedFullscreen] Opening connection fullscreen:', {
      embedId: connection.embed_id,
      origin: connection.origin,
      destination: connection.destination,
      price: connection.total_price,
    });
    selectedConnection = connection;
  }
  
  /**
   * Handle closing the connection detail fullscreen
   */
  function handleConnectionFullscreenClose() {
    selectedConnection = null;
  }
  
  /**
   * Handle embed data updates during streaming
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) localEmbedIds = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }
  
  /**
   * Handle closing the entire search fullscreen
   */
  function handleMainClose() {
    if (selectedConnection) {
      selectedConnection = null;
    } else {
      onClose();
    }
  }
</script>

<!-- Connection results view - ALWAYS rendered (base layer) -->
<UnifiedEmbedFullscreen
  appId="travel"
  skillId="search_connections"
  title=""
  onClose={handleMainClose}
  skillIconName="search"
  status={fullscreenStatus}
  {skillName}
  showStatus={true}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToConnectionResult}
  legacyResults={legacyResults}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const connectionResults = getConnectionResults(ctx)}
    {@const cheapestThreshold = getCheapestThreshold(connectionResults)}
    {@const firstDeparture = connectionResults.length > 0 ? connectionResults[0].departure : undefined}
    
    <!-- Header with route summary, search params, and provider -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      {#if firstDeparture}
        <div class="search-date">{formatHeaderDate(firstDeparture)}</div>
      {/if}
      <div class="search-provider">{viaProvider}</div>
    </div>
    
    <!-- Error state -->
    {#if status === 'error'}
      <div class="error-state">
        <div class="error-title">{$text('embeds.search_failed.text') || 'Search failed'}</div>
        <div class="error-message">{errorMessage}</div>
      </div>
    {:else}
      {#if connectionResults.length === 0}
        {#if ctx.isLoadingChildren}
          <div class="loading-state">
            <p>{$text('embeds.loading.text') || 'Loading...'}</p>
          </div>
        {:else}
          <div class="no-results">
            <p>{$text('embeds.no_results.text') || 'No connections found.'}</p>
          </div>
        {/if}
      {:else}
        <!-- Connection cards grid -->
        <div class="connection-embeds-grid">
          {#each connectionResults as result}
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
              onFullscreen={() => handleConnectionFullscreen(result)}
            />
          {/each}
        </div>
      {/if}
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Connection detail fullscreen overlay -->
{#if selectedConnection}
  <ChildEmbedOverlay>
    <TravelConnectionEmbedFullscreen
      connection={selectedConnection}
      onClose={handleConnectionFullscreenClose}
      embedId={selectedConnection.embed_id}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  /* ===========================================
     Fullscreen Header
     =========================================== */
  
  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 40px;
    padding: 0 16px;
    text-align: center;
  }
  
  .search-query {
    font-size: 24px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .search-date {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-font-primary);
    margin-top: 6px;
  }
  
  .search-provider {
    font-size: 16px;
    color: var(--color-font-secondary);
    margin-top: 8px;
  }
  
  @container fullscreen (max-width: 500px) {
    .fullscreen-header {
      margin-top: 70px;
      margin-bottom: 24px;
    }
    
    .search-query {
      font-size: 20px;
    }
    
    .search-provider {
      font-size: 14px;
    }
  }
  
  /* ===========================================
     Loading and No Results States
     =========================================== */
  
  .loading-state,
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }
  
  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
    color: var(--color-font-secondary);
    text-align: center;
  }
  
  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }
  
  .error-message {
    font-size: 14px;
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
  }
  
  /* ===========================================
     Connection Embeds Grid
     =========================================== */
  
  .connection-embeds-grid {
    display: grid;
    gap: 16px;
    width: calc(100% - 20px);
    max-width: 1000px;
    margin: 0 auto;
    padding: 0 10px;
    padding-bottom: 120px;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  }
  
  @container fullscreen (max-width: 500px) {
    .connection-embeds-grid {
      grid-template-columns: 1fr;
    }
  }
  
  .connection-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
  
  /* ===========================================
     Skill Icon Styling
     =========================================== */
  
  /* Skill icon uses the existing 'search' icon mapping from BasicInfosBar */
</style>
