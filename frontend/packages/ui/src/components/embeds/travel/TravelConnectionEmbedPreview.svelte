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
  import Luggage from '@lucide/svelte/icons/luggage';
  import Slash from '@lucide/svelte/icons/slash';
  import { text } from '@repo/ui';
  import TravelTimeBadge from './TravelTimeBadge.svelte';
  import { countryCodeToFlag } from '../../../utils/countryFlag';
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
    stops: _stops = 0,
    arrivalDelayMinutes,
    hasCancellation = false,
    carriers: carriersProp = [],
    bookingProvider,
    airlineLogo,
    carrierCodes: carrierCodesProp = [],
    bookableSeats: _bookableSeats,
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
  
  // Match the existing fullscreen locale-aware travel times.
  function formatTime(value?: string): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

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
  
  let realtimeStatus = $derived.by(() => {
    if (hasCancellation) return 'Cancellation on route';
    if (arrivalDelayMinutes == null) return '';
    if (arrivalDelayMinutes === 0) return 'On time';
    if (arrivalDelayMinutes > 0) return `+${arrivalDelayMinutes} min arrival`;
    return `${arrivalDelayMinutes} min arrival`;
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
  
  function segmentFor(leg: Record<string, unknown>, end: 'departure' | 'arrival') {
    const segments = Array.isArray(leg.segments) ? leg.segments as Record<string, unknown>[] : [];
    return (end === 'departure' ? segments[0] : segments.at(-1)) || {};
  }
  function journeyTime(leg: Record<string, unknown>, end: 'departure' | 'arrival') {
    const segment = segmentFor(leg, end);
    return formatTime(legText(leg[end] || segment[`${end}_time`]) || (end === 'departure' ? departure : _arrival));
  }
  function journeyCountry(leg: Record<string, unknown>, end: 'departure' | 'arrival', index: number) {
    const value = segmentFor(leg, end)[`${end}_country_code`] || leg[end === 'departure' ? 'origin_country_code' : 'destination_country_code']
      || (index === 0 || (index === 1 && tripType === 'round_trip') ? connection?.[index % 2 === (end === 'departure' ? 0 : 1) ? 'origin_country_code' : 'destination_country_code'] : undefined);
    return typeof value === 'string' ? countryCodeToFlag(value) : '';
  }
  function journeyLocation(leg: Record<string, unknown>, end: 'departure' | 'arrival') {
    const value = leg[end === 'departure' ? 'origin' : 'destination'] || segmentFor(leg, end)[`${end}_station`] || (end === 'departure' ? origin : destination);
    return typeof value === 'string' ? extractCode(value) : '';
  }
  let luggageExcluded = $derived.by(() => {
    const states = [connection?.luggage_included, connection?.baggage_included, connection?.checked_baggage_included];
    // Conflicting inclusion metadata is uncertain, so it must not show an exclusion.
    return states.includes(false) && !states.includes(true);
  });

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
  {#snippet details()}
    <div class="connection-result-layout" class:has-map={routeMap.length > 1} data-testid="connection-preview-details">
      <div class="connection-information">
        {#if carrierLogos.length > 0}
          <div class="airline-logos" data-testid="airline-logos">
            {#each carrierLogos as logo}
              <img class="airline-logo" src={failedCarrierLogos.includes(logo.url) ? transportIconUrl : logo.url}
                alt={logo.label} width="22" height="22" loading="lazy"
                onerror={() => { if (!failedCarrierLogos.includes(logo.url)) failedCarrierLogos = [...failedCarrierLogos, logo.url]; }} />
            {/each}
          </div>
        {/if}
        <div class="itinerary-columns" data-testid="connection-route" class:single-journey={previewLegs.length === 1}>
          {#each previewLegs as leg, index}
            <div class="itinerary-leg">
              <small class="journey-date">{legDate(leg.departure || segmentFor(leg, 'departure').departure_time)}</small>
              <div class="journey-departure" data-testid="connection-time"><TravelTimeBadge time={journeyTime(leg, 'departure')} isDaytime={segmentFor(leg, 'departure').departure_is_daytime as boolean | undefined} /></div>
              <strong class="journey-airport" title={legText(leg.origin) || origin}>{journeyCountry(leg, 'departure', index)} {journeyLocation(leg, 'departure')}</strong>
              <span class="journey-duration" data-testid="connection-meta">{legText(leg.duration) || duration || ''}</span>
              <strong class="journey-airport" title={legText(leg.destination) || destination}>{journeyCountry(leg, 'arrival', index)} {journeyLocation(leg, 'arrival')}</strong>
              <div class="journey-arrival"><TravelTimeBadge time={journeyTime(leg, 'arrival')} isDaytime={segmentFor(leg, 'arrival').arrival_is_daytime as boolean | undefined} /></div>
            </div>
          {/each}
        </div>
        <div class="connection-footer" data-testid="connection-footer">
          {#if luggageExcluded}<span class="luggage-excluded" role="img" aria-label={$text('result_embed.luggage_not_included')} title={$text('result_embed.luggage_not_included')} data-testid="connection-no-luggage"><Luggage size={21} aria-hidden="true" /><span class="luggage-slash"><Slash size={25} aria-hidden="true" /></span></span>{/if}
          {#if formattedPrice}<strong class="connection-price" data-testid="connection-price">{formattedPrice}</strong>{/if}
        </div>
        {#if realtimeStatus}<div class="realtime-status" data-testid="connection-realtime-status">{realtimeStatus}</div>{/if}
        {#if optimizationBadge}<div class="optimization-badge" data-testid="connection-optimization-badge">{optimizationBadge}</div>{/if}
      </div>
      {#if routeMap.length > 1}<div class="connection-map"><ResultEmbedMapPreview center={routeMap[0]} path={routeMap} zoom={5} interactive /></div>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .connection-result-layout { display: flex; height: 100%; width: 100%; min-width: 0; }
  .connection-information { position: relative; width: 100%; min-width: 0; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; box-sizing: border-box; padding: 42px 14px 30px; }
  .airline-logos { position: absolute; top: 10px; left: 50%; transform: translateX(-50%); display: flex; gap: 5px; }
  .airline-logo { width: 22px; height: 22px; border-radius: 50%; object-fit: contain; background: var(--color-grey-0); }
  .itinerary-columns { display: flex; justify-content: center; align-items: stretch; width: 240px; max-width: 100%; min-width: 0; }
  .itinerary-leg { display: flex; flex-direction: column; align-items: center; gap: 5px; min-width: 0; padding: 0 8px; flex: 1 1 0; box-sizing: border-box; text-align: center; }
  .single-journey { width: 120px; }
  .itinerary-leg + .itinerary-leg { border-left: 1px solid var(--color-grey-20); }
  .journey-date, .journey-duration { font-size: var(--font-size-xxs); font-weight: 600; line-height: 1.15; color: var(--color-font-secondary); white-space: nowrap; }
  .journey-airport { max-width: 100%; font-size: var(--font-size-xs); line-height: 1.15; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .journey-departure :global(.time-badge), .journey-arrival :global(.time-badge) { font-size: var(--font-size-xxs); padding: 3px 7px; gap: 4px; }
  .journey-arrival { display: none; }
  .connection-footer { position: absolute; bottom: 8px; left: 48px; right: 48px; display: flex; justify-content: center; align-items: center; gap: 6px; }
  .connection-price { font-size: 1.2rem; font-weight: 800; line-height: 1.2; color: var(--color-success); white-space: nowrap; }
  .luggage-excluded { position: relative; display: inline-flex; color: var(--color-font-secondary); }
  .luggage-slash { position: absolute; inset: -2px; display: inline-flex; transform: scaleX(-1); }
  .realtime-status, .optimization-badge { font-size: var(--font-size-xxs); line-height: 1.2; text-align: center; }
  .realtime-status { color: var(--color-font-secondary); }
  .optimization-badge { color: var(--color-primary); }
  .connection-map { display: none; }
  @container result-card (max-width: 200px) {
    .connection-information { padding: 72px 10px 30px; }
    .airline-logos { top: 46px; }
    .itinerary-columns { width: 130px; }
    .single-journey { width: 65px; }
    .itinerary-leg { padding-left: 2px; padding-right: 2px; }
    .journey-date, .journey-duration { font-size: var(--font-size-micro); }
    .journey-airport { font-size: var(--font-size-tiny); }
    .journey-departure :global(.time-badge) { font-size: var(--font-size-micro); padding: 3px; gap: 2px; }
    .connection-footer { left: 10px; right: 10px; }
    .connection-price { font-size: 1rem; }
  }
  @container result-card (min-width: 401px) {
    .connection-information { padding: 54px 24px 48px; }
    .has-map .connection-information { width: 42%; min-width: 288px; flex-shrink: 0; }
    .connection-map { display: block; flex: 1; height: 100%; min-width: 0; }
    .journey-arrival { display: block; }
    .itinerary-leg { gap: 8px; }
    .connection-footer { bottom: 14px; left: 24px; right: 24px; }
    .journey-date, .journey-duration, .journey-airport { font-size: var(--font-size-xs); }
    .journey-departure :global(.time-badge), .journey-arrival :global(.time-badge) { font-size: var(--font-size-xs); }
  }
</style>
