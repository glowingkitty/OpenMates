<!--
  frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte
  
  Preview component for a single travel connection (child embed).
  Uses UnifiedEmbedPreview as base and displays connection summary:
  - Price (prominent)
  - Duration and stops
  - Departure/arrival times
  - Carrier names
  
  Similar to WebsiteEmbedPreview but with travel-specific layout.
  This component is rendered inside TravelSearchEmbedFullscreen's grid.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { proxyImage, MAX_WIDTH_AIRLINE_LOGO } from '../../../utils/imageProxy';
  
  /**
   * Props for travel connection embed preview
   * Data comes from the parent fullscreen component which transforms
   * raw TOON-decoded embed content into this structured format
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Total price (e.g., '245.50') */
    price?: string;
    /** Currency code (e.g., 'EUR') */
    currency?: string;
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
    /** Carrier names */
    carriers?: string[];
    /** IATA carrier codes (e.g., ['LH', 'BA']) for airline logos */
    carrierCodes?: string[];
    /** Number of bookable seats remaining */
    bookableSeats?: number;
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
    id,
    price,
    currency = 'EUR',
    transportMethod = 'airplane',
    tripType = 'one_way',
    origin,
    destination,
    departure,
    arrival: _arrival,
    duration,
    stops = 0,
    carriers: carriersProp = [],
    carrierCodes: carrierCodesProp = [],
    bookableSeats,
    // isCheapest not used in redesigned preview — price is always green
    isCheapest: _isCheapest = false,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Defensive: TOON serialization may collapse arrays into bare strings.
  // Ensure carriers and carrierCodes are always arrays even if a non-array
  // value slips through from the renderer. Belt-and-suspenders with the
  // extractToonArray() fix in GroupRenderer.
  // carriersProp accepted for prop compatibility but carriers are not displayed in redesigned preview
  let _carriers = $derived(Array.isArray(carriersProp) ? carriersProp : []);
  let carrierCodes = $derived(Array.isArray(carrierCodesProp) ? carrierCodesProp : []);
  
  // Format price for display
  let formattedPrice = $derived.by(() => {
    if (!price) return '';
    const numPrice = parseFloat(price);
    if (isNaN(numPrice)) return `${currency} ${price}`;
    // Format with locale-aware number formatting
    return `${currency} ${numPrice.toFixed(numPrice % 1 === 0 ? 0 : 2)}`;
  });
  
  // Time formatting is handled by BasicInfosBar via routeDisplay + skillName
  
  // Format departure date for display (e.g., "Sat, Mar 28")
  let departureDate = $derived.by(() => {
    if (!departure) return '';
    try {
      const date = new Date(departure);
      return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  });

  // Trip type label for price display
  let tripTypeLabel = $derived.by(() => {
    switch (tripType) {
      case 'round_trip': return 'Round trip';
      case 'multi_city': return 'Multi-city';
      default: return 'One way';
    }
  });

  // Combined meta line: "Sat, Mar 28 · 31h 20m · 2 stops"
  let metaLine = $derived.by(() => {
    const parts: string[] = [];
    if (departureDate) parts.push(departureDate);
    if (duration) parts.push(duration);
    parts.push(stopsLabel);
    return parts.join(' · ');
  });
  
  // Generate airline logo URLs from carrier codes via image proxy
  let airlineLogos = $derived.by(() => {
    if (!carrierCodes || carrierCodes.length === 0) return [];
    // Show max 3 airline logos
    return carrierCodes.slice(0, 3).map(code => ({
      code,
      url: proxyImage(`https://images.kiwi.com/airlines/64/${code}.png`, MAX_WIDTH_AIRLINE_LOGO),
    }));
  });
  
  // Stops label
  let stopsLabel = $derived.by(() => {
    if (stops === 0) return 'Direct';
    if (stops === 1) return '1 stop';
    return `${stops} stops`;
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
    const match = location.match(/\(([^)]+)\)/);
    if (match) return match[1];
    // If no code in parens, return first word
    return location.split(' ')[0] || location;
  }
  
  // No-op stop handler (connections don't have cancellable tasks)
  async function handleStop() {
    // Not applicable for child connection embeds
  }
</script>

<UnifiedEmbedPreview
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
    <div class="connection-details" class:mobile={isMobileLayout} data-testid="connection-preview-details">
      <!-- Price row: green price + trip type + airline logos -->
      <div class="price-row">
        {#if formattedPrice}
          <span class="connection-price" data-testid="connection-price">{formattedPrice}</span>
          <span class="trip-type-separator">|</span>
          <span class="trip-type-label">{tripTypeLabel}</span>
        {/if}
      </div>

      <!-- Airline logos row -->
      {#if airlineLogos.length > 0}
        <div class="airline-logos" data-testid="airline-logos">
          {#each airlineLogos as logo}
            <img
              class="airline-logo"
              src={logo.url}
              alt={logo.code}
              width="22"
              height="22"
              loading="lazy"
            />
          {/each}
        </div>
      {/if}

      <!-- Route: "Berlin (BER) → Bangkok (BKK)" -->
      {#if origin && destination}
        <div class="connection-route" data-testid="connection-route">
          <span class="route-text">{origin} → {destination}</span>
        </div>
      {/if}

      <!-- Meta line: "Sat, Mar 28 · 31h 20m · 2 stops" -->
      <div class="connection-meta" data-testid="connection-meta">{metaLine}</div>

      <!-- Seats remaining warning -->
      {#if bookableSeats !== undefined && bookableSeats > 0 && bookableSeats <= 4}
        <div class="seats-warning">
          {bookableSeats} {bookableSeats === 1 ? 'seat' : 'seats'} left
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Connection Preview — Redesigned Card Layout
     Matches Figma: node 4950-44635 (preview section)
     =========================================== */

  .connection-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
    justify-content: center;
    padding: 2px 0;
  }

  .connection-details.mobile {
    justify-content: flex-start;
  }

  /* Price row: "1.111 EUR | One way" */
  .price-row {
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex-wrap: wrap;
  }

  .connection-price {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--color-success, #00a313);
    line-height: 1.2;
  }

  .connection-details.mobile .connection-price {
    font-size: 1.1rem;
  }

  .trip-type-separator {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.2;
  }

  .trip-type-label {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.2;
  }

  .connection-details.mobile .trip-type-separator,
  .connection-details.mobile .trip-type-label {
    font-size: 1.1rem;
  }

  /* Airline logos — overlapping circle stack */
  .airline-logos {
    display: flex;
    align-items: center;
  }

  .airline-logos .airline-logo + .airline-logo {
    margin-left: -6px;
  }

  .airline-logo {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    object-fit: cover;
    background: var(--color-grey-10, #fff);
    border: 1.5px solid var(--color-grey-20, #e2e2e2);
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.04);
    flex-shrink: 0;
  }

  /* Route: "Berlin (BER) → Bangkok (BKK)" */
  .connection-route {
    font-size: 0.875rem;
    color: var(--color-font-primary);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .route-text {
    font-weight: 600;
  }

  /* Meta line: "Sat, Mar 28 · 31h 20m · 2 stops" */
  .connection-meta {
    font-size: 0.875rem;
    color: var(--color-grey-60);
    line-height: 1.3;
  }

  /* Seats warning */
  .seats-warning {
    font-size: 0.75rem;
    color: var(--color-warning, #f59e0b);
    font-weight: 600;
    margin-top: 1px;
  }
</style>
