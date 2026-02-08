<!--
  frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedFullscreen.svelte
  
  Fullscreen detail view for a single travel connection (child embed).
  Uses UnifiedEmbedFullscreen as base and shows leg-by-leg, segment-by-segment detail.
  
  Layout:
  - Header: Price + route + trip type
  - For each leg:
    - Leg header (e.g., "Outbound: Munich → London")
    - Timeline of segments with departure/arrival times, stations, carrier, flight number
  - Footer: Booking info (seats remaining, last ticketing date)
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
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
  }
  
  /** Leg data */
  interface LegData {
    leg_index: number;
    origin: string;
    destination: string;
    departure: string;
    arrival: string;
    duration: string;
    stops: number;
    segments: SegmentData[];
  }
  
  /** Connection data */
  interface ConnectionData {
    embed_id: string;
    type?: string;
    transport_method?: string;
    trip_type?: string;
    total_price?: string;
    currency?: string;
    bookable_seats?: number;
    last_ticketing_date?: string;
    booking_url?: string;
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
  }
  
  interface Props {
    /** Connection data from parent */
    connection: ConnectionData;
    /** Close handler */
    onClose: () => void;
    /** Embed ID for reference */
    embedId?: string;
  }
  
  let {
    connection,
    onClose,
    embedId,
  }: Props = $props();
  
  // Format price
  let formattedPrice = $derived.by(() => {
    if (!connection.total_price) return '';
    const num = parseFloat(connection.total_price);
    if (isNaN(num)) return `${connection.currency || 'EUR'} ${connection.total_price}`;
    return `${connection.currency || 'EUR'} ${num.toFixed(num % 1 === 0 ? 0 : 2)}`;
  });
  
  // Route summary
  let routeDisplay = $derived.by(() => {
    if (connection.origin && connection.destination) {
      return `${connection.origin} → ${connection.destination}`;
    }
    return '';
  });
  
  // Trip type label
  let tripTypeLabel = $derived.by(() => {
    switch (connection.trip_type) {
      case 'round_trip': return 'Round trip';
      case 'multi_city': return 'Multi-city';
      default: return 'One way';
    }
  });
  
  // Leg labels
  function getLegLabel(leg: LegData, totalLegs: number): string {
    if (totalLegs === 1) return '';
    if (totalLegs === 2) {
      return leg.leg_index === 0 ? 'Outbound' : 'Return';
    }
    return `Leg ${leg.leg_index + 1}`;
  }
  
  // Format time from ISO string
  function formatTime(isoString: string): string {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  }
  
  // Format date from ISO string
  function formatDate(isoString: string): string {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    } catch {
      return isoString;
    }
  }
  
  // Stops label
  function getStopsLabel(stops: number): string {
    if (stops === 0) return 'Direct';
    if (stops === 1) return '1 stop';
    return `${stops} stops`;
  }
  
  // Booking URL (either from backend or constructed from IATA codes)
  let bookingUrl = $derived.by(() => {
    if (connection.booking_url) return connection.booking_url;
    // Fallback: construct Google Flights link from first/last segment
    if (connection.legs && connection.legs.length > 0) {
      const firstLeg = connection.legs[0];
      if (firstLeg.segments && firstLeg.segments.length > 0) {
        const originIata = firstLeg.segments[0].departure_station;
        const destIata = firstLeg.segments[firstLeg.segments.length - 1].arrival_station;
        const depDate = firstLeg.departure?.slice(0, 10) || '';
        if (originIata && destIata && depDate) {
          return `https://www.google.com/travel/flights?q=flights+from+${originIata}+to+${destIata}+on+${depDate}`;
        }
      }
    }
    return '';
  });
  
  // Handle booking button click
  function handleBooking() {
    if (bookingUrl) {
      window.open(bookingUrl, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Skill name for bottom bar
  let skillName = $derived($text('app_skills.travel.search_connections.text') || 'Connection Details');
</script>

<UnifiedEmbedFullscreen
  appId="travel"
  skillId="connection"
  title=""
  {onClose}
  skillIconName="search"
  status="finished"
  {skillName}
  showStatus={false}
  currentEmbedId={embedId}
>
  {#snippet content()}
    <div class="connection-fullscreen">
      <!-- Header: Price + Route + Trip Type -->
      <div class="connection-header">
        {#if formattedPrice}
          <div class="price">{formattedPrice}</div>
        {/if}
        {#if routeDisplay}
          <div class="route">{routeDisplay}</div>
        {/if}
        <div class="trip-type-badge">{tripTypeLabel}</div>
        {#if connection.carriers && connection.carriers.length > 0}
          <div class="carriers">{connection.carriers.join(', ')}</div>
        {/if}
        
        <!-- Booking CTA button -->
        {#if bookingUrl}
          <button class="cta-button" onclick={handleBooking}>
            {($text('embeds.book_on.text') || 'Book on {provider}').replace('{provider}', 'Google Flights')}
          </button>
        {/if}
      </div>
      
      <!-- Legs Timeline -->
      {#if connection.legs && connection.legs.length > 0}
        <div class="legs-container">
          {#each connection.legs as leg}
            {@const legLabel = getLegLabel(leg, connection.legs?.length ?? 0)}
            <div class="leg">
              <!-- Leg Header -->
              <div class="leg-header">
                {#if legLabel}
                  <span class="leg-label">{legLabel}:</span>
                {/if}
                <span class="leg-route">{leg.origin} → {leg.destination}</span>
                <span class="leg-meta">
                  {formatDate(leg.departure)} · {leg.duration} · {getStopsLabel(leg.stops)}
                </span>
              </div>
              
              <!-- Segments Timeline -->
              <div class="segments">
                {#each leg.segments as segment, segIdx}
                  <div class="segment">
                    <!-- Departure -->
                    <div class="segment-endpoint">
                      <div class="segment-time">{formatTime(segment.departure_time)}</div>
                      <div class="timeline-dot"></div>
                      <div class="segment-station">{segment.departure_station}</div>
                    </div>
                    
                    <!-- Flight/train info bar -->
                    <div class="segment-info">
                      <div class="timeline-line"></div>
                      <div class="segment-details">
                        <span class="carrier-name">{segment.carrier}</span>
                        {#if segment.number}
                          <span class="flight-number">{segment.number}</span>
                        {/if}
                        <span class="segment-duration">{segment.duration}</span>
                      </div>
                    </div>
                    
                    <!-- Arrival -->
                    <div class="segment-endpoint">
                      <div class="segment-time">{formatTime(segment.arrival_time)}</div>
                      <div class="timeline-dot"></div>
                      <div class="segment-station">{segment.arrival_station}</div>
                    </div>
                    
                    <!-- Layover indicator between segments -->
                    {#if segIdx < leg.segments.length - 1}
                      <div class="layover">
                        <div class="layover-line"></div>
                        <span class="layover-label">Connection</span>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <!-- No leg details available - show summary -->
        <div class="summary-only">
          {#if connection.departure && connection.arrival}
            <div class="summary-times">
              <span>{formatTime(connection.departure)}</span>
              <span class="summary-arrow">→</span>
              <span>{formatTime(connection.arrival)}</span>
            </div>
          {/if}
          {#if connection.duration}
            <div class="summary-duration">{connection.duration}</div>
          {/if}
          {#if connection.stops !== undefined}
            <div class="summary-stops">{getStopsLabel(connection.stops)}</div>
          {/if}
        </div>
      {/if}
      
      <!-- Booking Info Footer -->
      <div class="booking-info">
        {#if connection.bookable_seats !== undefined && connection.bookable_seats > 0}
          <div class="booking-item" class:warning={connection.bookable_seats <= 4}>
            {connection.bookable_seats} {connection.bookable_seats === 1 ? 'seat' : 'seats'} remaining
          </div>
        {/if}
        {#if connection.last_ticketing_date}
          <div class="booking-item">
            Book by {connection.last_ticketing_date}
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Connection Fullscreen Layout
     =========================================== */
  
  .connection-fullscreen {
    max-width: 600px;
    margin: 60px auto 120px;
    padding: 0 20px;
  }
  
  @container fullscreen (max-width: 500px) {
    .connection-fullscreen {
      margin-top: 70px;
      padding: 0 16px;
    }
  }
  
  /* ===========================================
     Header
     =========================================== */
  
  .connection-header {
    text-align: center;
    margin-bottom: 40px;
  }
  
  .price {
    font-size: 32px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.2;
  }
  
  @container fullscreen (max-width: 500px) {
    .price {
      font-size: 28px;
    }
  }
  
  .route {
    font-size: 18px;
    color: var(--color-font-secondary);
    margin-top: 8px;
    line-height: 1.3;
  }
  
  .trip-type-badge {
    display: inline-block;
    margin-top: 12px;
    padding: 4px 12px;
    border-radius: 100px;
    background-color: var(--color-grey-20);
    font-size: 13px;
    font-weight: 500;
    color: var(--color-grey-80);
  }
  
  .carriers {
    font-size: 14px;
    color: var(--color-grey-60);
    margin-top: 8px;
  }
  
  /* CTA Booking Button */
  .cta-button {
    background-color: var(--color-button-primary);
    color: white;
    border: none;
    border-radius: 15px;
    padding: 12px 24px;
    font-family: 'Lexend Deca', sans-serif;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.15s;
    margin-top: 16px;
    min-width: 200px;
  }
  
  .cta-button:hover {
    background-color: var(--color-button-primary-hover);
    transform: translateY(-1px);
  }
  
  .cta-button:active {
    background-color: var(--color-button-primary-pressed);
    transform: translateY(0);
  }
  
  /* ===========================================
     Legs Container
     =========================================== */
  
  .legs-container {
    display: flex;
    flex-direction: column;
    gap: 32px;
  }
  
  .leg {
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 16px;
    padding: 20px;
  }
  
  .leg-header {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--color-grey-20);
  }
  
  .leg-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-primary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .leg-route {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .leg-meta {
    font-size: 13px;
    color: var(--color-grey-60);
  }
  
  /* ===========================================
     Segments Timeline
     =========================================== */
  
  .segments {
    display: flex;
    flex-direction: column;
  }
  
  .segment {
    display: flex;
    flex-direction: column;
  }
  
  .segment-endpoint {
    display: grid;
    grid-template-columns: 60px 20px 1fr;
    align-items: center;
    gap: 8px;
    min-height: 28px;
  }
  
  .segment-time {
    font-size: 15px;
    font-weight: 600;
    color: var(--color-font-primary);
    text-align: right;
  }
  
  .timeline-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background-color: var(--color-primary);
    justify-self: center;
  }
  
  .segment-station {
    font-size: 14px;
    color: var(--color-font-primary);
    font-weight: 500;
  }
  
  .segment-info {
    display: grid;
    grid-template-columns: 60px 20px 1fr;
    gap: 8px;
    min-height: 40px;
    align-items: center;
  }
  
  /* First column in segment-info grid is the empty time slot area */
  
  .timeline-line {
    width: 2px;
    height: 100%;
    min-height: 32px;
    background-color: var(--color-primary);
    opacity: 0.3;
    justify-self: center;
  }
  
  .segment-details {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--color-grey-60);
    padding: 4px 0;
  }
  
  .carrier-name {
    font-weight: 500;
    color: var(--color-grey-80);
  }
  
  .flight-number {
    color: var(--color-grey-50);
  }
  
  .segment-duration {
    color: var(--color-grey-50);
  }
  
  /* Layover between segments */
  .layover {
    display: grid;
    grid-template-columns: 60px 20px 1fr;
    gap: 8px;
    min-height: 36px;
    align-items: center;
  }
  
  .layover-line {
    width: 2px;
    height: 100%;
    min-height: 28px;
    background: repeating-linear-gradient(
      to bottom,
      var(--color-grey-40) 0px,
      var(--color-grey-40) 4px,
      transparent 4px,
      transparent 8px
    );
    justify-self: center;
    grid-column: 2;
  }
  
  .layover-label {
    grid-column: 3;
    font-size: 12px;
    color: var(--color-warning, #f59e0b);
    font-weight: 500;
    font-style: italic;
  }
  
  /* ===========================================
     Summary Only (when no leg details)
     =========================================== */
  
  .summary-only {
    text-align: center;
    padding: 24px 0;
  }
  
  .summary-times {
    font-size: 20px;
    font-weight: 600;
    color: var(--color-font-primary);
  }
  
  .summary-arrow {
    margin: 0 8px;
    color: var(--color-grey-50);
  }
  
  .summary-duration,
  .summary-stops {
    font-size: 14px;
    color: var(--color-grey-60);
    margin-top: 4px;
  }
  
  /* ===========================================
     Booking Info Footer
     =========================================== */
  
  .booking-info {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 24px;
    padding: 16px;
    background: var(--color-grey-10, rgba(0, 0, 0, 0.03));
    border-radius: 12px;
  }
  
  .booking-info:empty {
    display: none;
  }
  
  .booking-item {
    font-size: 13px;
    color: var(--color-grey-60);
  }
  
  .booking-item.warning {
    color: var(--color-warning, #f59e0b);
    font-weight: 600;
  }
  
  /* ===========================================
     Skill Icon Styling
     =========================================== */
  
  /* Skill icon uses the existing 'search' icon mapping from BasicInfosBar */
</style>
