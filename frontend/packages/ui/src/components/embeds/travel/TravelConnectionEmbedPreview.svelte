<!--
  frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte

  Preview component for a single travel connection (child embed).
  Uses UnifiedEmbedPreview as base and displays redesigned connection card:
  - Price (green) + trip type
  - Flag emojis + airline logos
  - Duration and stops
  - Route display with origin/destination

  Similar to WebsiteEmbedPreview but with travel-specific layout.
  This component is rendered inside TravelSearchEmbedFullscreen's grid.
-->

<script lang="ts">
  import transportIconUrl from '../../../../static/icons/travel.svg';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedMapPreview from '../ResultEmbedMapPreview.svelte';
  import { extractResultRoute } from '../resultMapRoutes';
  import { proxyImage, MAX_WIDTH_AIRLINE_LOGO } from '../../../utils/imageProxy';
  import { formatTravelFare, type TravelFare } from './fareDisplay';

  const PROVIDER_FAVICONS = [
    { match: 'deutsche bahn', url: 'https://www.bahn.de/favicon.ico' },
    { match: 'flix', url: 'https://www.flixbus.com/favicon.ico' },
  ];
  
  /**
   * Props for travel connection embed preview
   * Data comes from the parent fullscreen component which transforms
   * raw TOON-decoded embed content into this structured format
   */
  interface Props {
    resultContext?: 'auto' | 'chat' | 'results';
    connection?: Record<string, unknown>;
    /** Unique embed ID */
    id: string;
    /** Total price (e.g., '245.50') */
    price?: string | number;
    /** Currency code (e.g., 'EUR') */
    currency?: string;
    /** Structured fare state from pass-aware rail providers */
    fare?: TravelFare | null;
    /** Legacy partial fare flag */
    fareIsPartial?: boolean;
    /** Transport method (e.g., 'airplane') */
    transportMethod?: string;
    /** Trip type (e.g., 'one_way', 'round_trip', 'multi_city') */
    tripType?: string;
    /** Origin location (e.g., 'Munich (MUC)') */
    origin?: string;
    /** Destination location (e.g., 'London Heathrow (LHR)') */
    destination?: string;
    /** Departure time ISO 8601 */
    departure?: string;
    /** Arrival time ISO 8601 */
    arrival?: string;
    /** Total duration (e.g., '2h 30m') */
    duration?: string;
    /** Number of stops */
    stops?: number;
    /** Realtime arrival delay in minutes; negative means early */
    arrivalDelayMinutes?: number;
    /** True if the route contains a cancellation notice */
    hasCancellation?: boolean;
    /** Carrier names */
    carriers?: string[];
    /** Provider used for booking/search, e.g. Deutsche Bahn or FlixBus / FlixTrain */
    bookingProvider?: string;
    /** Primary provider/logo URL from the connection result */
    airlineLogo?: string;
    /** IATA carrier codes (e.g., ['LH', 'BA']) for airline logos */
    carrierCodes?: string[];
    /** Number of bookable seats remaining */
    bookableSeats?: number;
    /** OpenMates route optimization metadata */
    optimization?: {
      optimized_by?: string;
      badge?: string;
    };
    /** Whether this connection is among the cheapest results */
    isCheapest?: boolean;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }
  
  let {
    resultContext = 'auto',
    id,
    connection,
    price,
    currency = 'EUR',
    fare,
    fareIsPartial,
    transportMethod = 'airplane',
    tripType = 'one_way',
    origin,
    destination,
    departure,
    arrival: _arrival,
    duration,
    stops = 0,
    arrivalDelayMinutes,
    hasCancellation = false,
    carriers: carriersProp = [],
    bookingProvider,
    airlineLogo,
    carrierCodes: carrierCodesProp = [],
    bookableSeats,
    optimization,
    // isCheapest not used in redesigned preview — price is always green
    isCheapest: _isCheapest = false,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  let previewLegs = $derived.by(() => {
    const legs = Array.isArray(connection?.legs) ? connection.legs as Record<string, unknown>[] : [];
    return legs.length ? legs : [{ origin, destination, departure, arrival: _arrival, duration }];
  });
  function legDate(value: unknown) {
    if (typeof value !== 'string') return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  }
  function legText(value: unknown) { return typeof value === 'string' ? value : ''; }
  let routeMap = $derived(extractResultRoute(connection || {}));

  // Defensive: TOON serialization may collapse arrays into bare strings.
  // Ensure carriers and carrierCodes are always arrays even if a non-array
  // value slips through from the renderer. Belt-and-suspenders with the
  // extractToonArray() fix in GroupRenderer.
  // carriersProp accepted for prop compatibility but carriers are not displayed in redesigned preview
  function normalizeStringArray(value: string[] | string | undefined): string[] {
    if (Array.isArray(value)) return value;
    if (typeof value === 'string' && value.length > 0) return [value];
    return [];
  }

  let _carriers = $derived(normalizeStringArray(carriersProp as string[] | string | undefined));
  let carrierCodes = $derived(normalizeStringArray(carrierCodesProp as string[] | string | undefined));
  
  // Format price/fare state for display.
  let formattedPrice = $derived.by(() => {
    return formatTravelFare({ fare, total_price: price, currency, fare_is_partial: fareIsPartial });
  });
  
  // BasicInfosBar shows the compact route title; the card itself shows travel times.
  function formatTime(value?: string): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // Trip type label for price display
  let tripTypeLabel = $derived.by(() => {
    switch (tripType) {
      case 'round_trip': return 'Round trip';
      case 'multi_city': return 'Multi-city';
      default: return 'One way';
    }
  });

  let metaLine = $derived([duration, stopsLabel].filter(Boolean).join(' · '));
  let failedCarrierLogos = $state<string[]>([]);

  let providerFaviconUrl = $derived.by(() => {
    if (airlineLogo) return airlineLogo;
    const normalizedProvider = (bookingProvider || _carriers[0] || '').toLowerCase();
    return PROVIDER_FAVICONS.find(provider => normalizedProvider.includes(provider.match))?.url || undefined;
  });

  let carrierLogos = $derived.by(() => {
    if (transportMethod === 'airplane') {
      if (carrierCodes.length > 0) {
        return carrierCodes.slice(0, 3).map(code => ({
          label: code,
          url: proxyImage(`https://images.kiwi.com/airlines/64/${code}.png`, MAX_WIDTH_AIRLINE_LOGO),
        }));
      }
      if (airlineLogo) return [{ label: bookingProvider || _carriers[0] || 'Airline', url: proxyImage(airlineLogo, MAX_WIDTH_AIRLINE_LOGO) }];
      return [];
    }

    if (!providerFaviconUrl) return [];
    return [{ label: bookingProvider || _carriers[0] || 'Provider', url: proxyImage(providerFaviconUrl, MAX_WIDTH_AIRLINE_LOGO) }];
  });
  
  // Stops label
  let stopsLabel = $derived.by(() => {
    if (stops === 0) return 'Direct';
    if (stops === 1) return '1 stop';
    return `${stops} stops`;
  });

  let realtimeStatus = $derived.by(() => {
    if (hasCancellation) return 'Cancellation on route';
    if (arrivalDelayMinutes == null) return '';
    if (arrivalDelayMinutes === 0) return 'On time';
    if (arrivalDelayMinutes > 0) return `+${arrivalDelayMinutes} min arrival`;
    return `${arrivalDelayMinutes} min arrival`;
  });

  let realtimeStatusTone = $derived.by(() => {
    if (hasCancellation) return 'cancelled';
    if (arrivalDelayMinutes == null || arrivalDelayMinutes === 0) return 'ontime';
    return arrivalDelayMinutes > 0 ? 'late' : 'early';
  });

  let optimizationBadge = $derived.by(() => {
    if (optimization?.optimized_by !== 'openmates') return '';
    return optimization.badge || 'Optimized by OpenMates';
  });
  
  // Carriers array is used for props but display is now in the meta line
  
  // Route display for BasicInfosBar title
  let routeDisplay = $derived.by(() => {
    if (origin && destination) {
      // Extract short codes from "Munich (MUC)" format
      const originShort = extractCode(origin);
      const destShort = extractCode(destination);
      return `${originShort} → ${destShort}`;
    }
    return transportMethod === 'airplane' ? 'Flight' : 'Connection';
  });
  
  /**
   * Extract airport/station code from formatted string like "Munich (MUC)"
   * Returns the code if found, otherwise the full string
   */
  function extractCode(location: string): string {
    const match = location.match(/\(([A-Z0-9]{2,5})\)/);
    if (match) return match[1];
    // Station qualifiers like "(tief)" are not useful route labels.
    return location.replace(/\s*\([^)]*\)/g, '').split(' ')[0] || location;
  }
  
  // No-op stop handler (connections don't have cancellable tasks)
  async function handleStop() {
    // Not applicable for child connection embeds
  }
</script>

<UnifiedEmbedPreview
  resultPreview
  {resultContext}
  {id}
  appId="travel"
  skillId="connection"
  skillIconName="search"
  {status}
  skillName={routeDisplay}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="connection-result-layout">
    <div class="connection-details" class:mobile={isMobileLayout} data-testid="connection-preview-details">
      <div class="carrier-row">
        {#if carrierLogos.length > 0}
          <div class="airline-logos" data-testid="airline-logos">
            {#each carrierLogos as logo}
              <img class="airline-logo" src={failedCarrierLogos.includes(logo.url) ? transportIconUrl : logo.url}
                alt={logo.label} width="22" height="22" loading="lazy"
                onerror={() => { if (!failedCarrierLogos.includes(logo.url)) failedCarrierLogos = [...failedCarrierLogos, logo.url]; }} />
            {/each}
          </div>
        {/if}
        <span class="trip-type-label">{tripTypeLabel}</span>
      </div>
      <div class="itinerary-columns" data-testid="connection-route">
        <div class="itinerary-times" data-testid="connection-time">
          {#each previewLegs as leg}
            <div class="itinerary-leg">
              <small class="journey-date">{legDate(leg.departure)}</small>
              <strong class="journey-times">{formatTime(legText(leg.departure))} <span aria-hidden="true">→</span> {formatTime(legText(leg.arrival))}</strong>
              <div class="journey-route" title={`${legText(leg.origin)} → ${legText(leg.destination)}`}>
                <b>{legText(leg.origin) || origin || ''}</b><span aria-hidden="true"> → </span><b>{legText(leg.destination) || destination || ''}</b>
              </div>
            </div>
          {/each}
        </div>
      </div>
      <div class="connection-footer" data-testid="connection-footer">
        {#if formattedPrice}<strong class="connection-price" data-testid="connection-price">{formattedPrice}</strong>{/if}
        <span class="connection-meta" data-testid="connection-meta">{metaLine}</span>
      </div>

      {#if realtimeStatus}
        <div class="realtime-status" class:late={realtimeStatusTone === 'late'} class:early={realtimeStatusTone === 'early'} class:ontime={realtimeStatusTone === 'ontime'} class:cancelled={realtimeStatusTone === 'cancelled'} data-testid="connection-realtime-status">
          {realtimeStatus}
        </div>
      {/if}

      {#if optimizationBadge}
        <div class="optimization-badge" data-testid="connection-optimization-badge">
          {optimizationBadge}
        </div>
      {/if}

      <!-- Seats remaining warning -->
      {#if bookableSeats !== undefined && bookableSeats > 0 && bookableSeats <= 4}
        <div class="seats-warning">
          {bookableSeats} {bookableSeats === 1 ? 'seat' : 'seats'} left
        </div>
      {/if}
    </div>
    {#if routeMap.length > 1}<div class="connection-map"><ResultEmbedMapPreview center={routeMap[0]} path={routeMap} zoom={5} /></div>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .connection-result-layout { height: 100%; display: flex; align-items: stretch; min-width: 0; box-sizing: border-box; }
  .connection-details { display: flex; flex-direction: column; gap: 5px; box-sizing: border-box; min-width: 0; width: 100%; height: 100%; padding: 48px 48px 12px; }
  .carrier-row { display: flex; align-items: center; gap: 8px; min-height: 22px; }
  .airline-logos { display: flex; align-items: center; gap: 3px; flex-shrink: 0; }
  .airline-logo { width: 22px; height: 22px; border-radius: 50%; object-fit: contain; background: var(--color-grey-0); }
  .trip-type-label { font-size: var(--font-size-xxs); color: var(--color-font-secondary); }
  .itinerary-columns { min-width: 0; }
  .itinerary-times { display: flex; gap: 10px; min-width: 0; overflow-x: auto; }
  .itinerary-leg { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1 0 110px; }
  .itinerary-leg + .itinerary-leg { border-left: 1px solid var(--color-grey-20); padding-left: 10px; }
  .journey-date { color: var(--color-font-secondary); font-size: var(--font-size-xxs); line-height: 1.2; }
  .journey-times { font-size: var(--font-size-xxs); line-height: 1.3; white-space: nowrap; }
  .journey-route { font-size: var(--font-size-xxs); line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .journey-route b { font-weight: 600; }
  .connection-footer { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 3px 8px; margin-top: auto; }
  .connection-price { font-size: 1rem; font-weight: 700; color: var(--color-success); line-height: 1.2; }
  .connection-meta { font-size: var(--font-size-xxs); color: var(--color-font-secondary); line-height: 1.2; }
  .realtime-status, .optimization-badge, .seats-warning { font-size: var(--font-size-xxs); line-height: 1.2; }
  .realtime-status.late, .realtime-status.cancelled { color: var(--color-error); }
  .realtime-status.early, .realtime-status.ontime { color: var(--color-success); }
  .optimization-badge { color: var(--color-primary); }
  .seats-warning { color: var(--color-warning); }
  .connection-map { display: none; }
  @container result-card (min-width: 400px) {
    .connection-details { width: 33.3333%; padding: 54px 28px 48px; }
    .connection-map { display: block; flex: 1; min-width: 0; }
  }
</style>
