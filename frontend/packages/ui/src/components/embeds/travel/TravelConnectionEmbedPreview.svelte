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
    /** Number of bookable seats remaining */
    bookableSeats?: number;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    price,
    currency = 'EUR',
    transportMethod = 'airplane',
    // tripType is accepted as a prop but not currently displayed in the preview card
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    tripType = 'one_way',
    origin,
    destination,
    departure,
    arrival,
    duration,
    stops = 0,
    carriers = [],
    bookableSeats,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Format price for display
  let formattedPrice = $derived.by(() => {
    if (!price) return '';
    const numPrice = parseFloat(price);
    if (isNaN(numPrice)) return `${currency} ${price}`;
    // Format with locale-aware number formatting
    return `${currency} ${numPrice.toFixed(numPrice % 1 === 0 ? 0 : 2)}`;
  });
  
  // Format departure/arrival times for display
  function formatTime(isoString?: string): string {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  }
  
  let departureTime = $derived(formatTime(departure));
  let arrivalTime = $derived(formatTime(arrival));
  
  // Stops label
  let stopsLabel = $derived.by(() => {
    if (stops === 0) return 'Direct';
    if (stops === 1) return '1 stop';
    return `${stops} stops`;
  });
  
  // Carrier display (join with comma, max 2)
  let carrierDisplay = $derived.by(() => {
    if (!carriers || carriers.length === 0) return '';
    if (carriers.length <= 2) return carriers.join(', ');
    return `${carriers.slice(0, 2).join(', ')} +${carriers.length - 2}`;
  });
  
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
  skillIconName="travel"
  {status}
  skillName={routeDisplay}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="connection-details" class:mobile={isMobileLayout}>
      <!-- Price (prominent) -->
      {#if formattedPrice}
        <div class="connection-price">{formattedPrice}</div>
      {/if}
      
      <!-- Route -->
      <div class="connection-route">
        {#if origin && destination}
          <span class="route-text">{origin} → {destination}</span>
        {/if}
      </div>
      
      <!-- Time and duration row -->
      <div class="connection-times">
        {#if departureTime && arrivalTime}
          <span class="time-range">{departureTime} – {arrivalTime}</span>
        {/if}
        {#if duration}
          <span class="duration">{duration}</span>
        {/if}
      </div>
      
      <!-- Stops and carrier info -->
      <div class="connection-meta">
        <span class="stops" class:direct={stops === 0}>{stopsLabel}</span>
        {#if carrierDisplay}
          <span class="carrier">{carrierDisplay}</span>
        {/if}
      </div>
      
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
     Connection Details Content
     =========================================== */
  
  .connection-details {
    display: flex;
    flex-direction: column;
    gap: 3px;
    height: 100%;
    justify-content: center;
    padding: 2px 0;
  }
  
  .connection-details.mobile {
    justify-content: flex-start;
  }
  
  /* Price - prominent display */
  .connection-price {
    font-size: 18px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.2;
  }
  
  .connection-details.mobile .connection-price {
    font-size: 16px;
  }
  
  /* Route */
  .connection-route {
    font-size: 13px;
    color: var(--color-grey-80);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .route-text {
    font-weight: 500;
  }
  
  /* Times and duration */
  .connection-times {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .time-range {
    font-weight: 500;
    color: var(--color-grey-80);
  }
  
  .duration {
    color: var(--color-grey-60);
  }
  
  /* Stops and carrier */
  .connection-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--color-grey-60);
    line-height: 1.3;
  }
  
  .stops.direct {
    color: var(--color-success, #22c55e);
    font-weight: 500;
  }
  
  .carrier {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  /* Seats warning */
  .seats-warning {
    font-size: 11px;
    color: var(--color-warning, #f59e0b);
    font-weight: 600;
    margin-top: 1px;
  }
</style>
