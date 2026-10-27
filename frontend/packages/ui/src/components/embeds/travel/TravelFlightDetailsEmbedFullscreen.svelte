<!--
  frontend/packages/ui/src/components/embeds/travel/TravelFlightDetailsEmbedFullscreen.svelte

  Fullscreen view for a standalone get_flight skill result embed.
  Shows the real flight GPS track on a Leaflet/OpenStreetMap map, plus enrichment
  details: actual takeoff/landing times, runway used, actual distance, diversion.

  This component is used when the LLM calls get_flight directly in chat (not via
  the TravelConnectionEmbedFullscreen booking flow). The track data comes from the
  embed content decoded by the embed resolver.

  Architecture: Uses ResultEmbedFullscreen as base.
  See docs/architecture/app-skills.md for the skill execution model.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/TravelFlightDetailsEmbedRenderer.swift
-->

<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  // ---------------------------------------------------------------------------
  // Interfaces
  // ---------------------------------------------------------------------------

  interface TrackPoint {
    timestamp: number;
    lat: number;
    lon: number;
    alt?: number;
    gspeed?: number;
  }

  interface Props {
    /** Raw embed data containing decodedContent, attrs, embedData */
    data: EmbedFullscreenRawData;
    /** Close handler */
    onClose: () => void;
    /** Embed ID for share/navigation */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Navigate to previous embed */
    onNavigatePrevious?: () => void;
    /** Navigate to next embed */
    onNavigateNext?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // Extract fields from data.decodedContent with type safety
  // ---------------------------------------------------------------------------

  let dc = $derived(data.decodedContent ?? {});

  let flightNumber = $derived(typeof dc.flight_number === 'string' ? dc.flight_number : undefined);
  let departureDate = $derived(typeof dc.departure_date === 'string' ? dc.departure_date : undefined);
  let originIata = $derived(typeof dc.origin_iata === 'string' ? dc.origin_iata : undefined);
  let destinationIata = $derived(typeof dc.destination_iata === 'string' ? dc.destination_iata : undefined);
  let actualTakeoff = $derived(typeof dc.actual_takeoff === 'string' ? dc.actual_takeoff : undefined);
  let actualLanding = $derived(typeof dc.actual_landing === 'string' ? dc.actual_landing : undefined);
  let runwayTakeoff = $derived(typeof dc.runway_takeoff === 'string' ? dc.runway_takeoff : undefined);
  let runwayLanding = $derived(typeof dc.runway_landing === 'string' ? dc.runway_landing : undefined);
  let actualDistanceKm = $derived(typeof dc.actual_distance_km === 'number' ? dc.actual_distance_km : undefined);
  let flightTimeMinutes = $derived(typeof dc.flight_time_minutes === 'number' ? dc.flight_time_minutes : undefined);
  let diverted = $derived(typeof dc.diverted === 'boolean' ? dc.diverted : false);
  let actualDestinationIata = $derived(typeof dc.actual_destination_iata === 'string' ? dc.actual_destination_iata : undefined);
  let tracks: TrackPoint[] = $derived(Array.isArray(dc.tracks) ? dc.tracks as TrackPoint[] : []);
  let fr24Id = $derived(typeof dc.fr24_id === 'string' ? dc.fr24_id : undefined);

  // ---------------------------------------------------------------------------
  // Derived display values
  // ---------------------------------------------------------------------------

  let routeDisplay = $derived.by(() => {
    if (originIata && destinationIata) return `${originIata} → ${destinationIata}`;
    if (originIata) return originIata;
    return flightNumber || '';
  });

  let headerTitle = $derived(flightNumber || 'Flight Track');
  let headerSubtitle = $derived(routeDisplay !== flightNumber ? routeDisplay : '');

  function formatDateFull(iso?: string): string {
    if (!iso) return departureDate || '';
    try {
      return new Date(iso).toLocaleDateString([], {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      });
    } catch {
      return departureDate || '';
    }
  }

  function formatDateTime(iso?: string): string {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      const date = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
      const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return `${date} ${time}`;
    } catch {
      return '—';
    }
  }

  let takeoffDisplay = $derived(formatDateTime(actualTakeoff));
  let landingDisplay = $derived(formatDateTime(actualLanding));
  let displayDate = $derived(formatDateFull(actualTakeoff || undefined));

  let distanceDisplay = $derived.by(() => {
    if (actualDistanceKm == null) return null;
    return `${Math.round(actualDistanceKm).toLocaleString()} km`;
  });

  let durationDisplay = $derived.by(() => {
    if (flightTimeMinutes == null) return null;
    const h = Math.floor(flightTimeMinutes / 60);
    const m = flightTimeMinutes % 60;
    if (h === 0) return `${m}m`;
    return m > 0 ? `${h}h ${m}m` : `${h}h`;
  });

  let hasTrackData = $derived(tracks.length >= 2);
  let mapCenter = $derived(hasTrackData ? { lat: tracks[0].lat, lon: tracks[0].lon } : undefined);
  let mapMarkers = $derived(hasTrackData ? [
    { lat: tracks[0].lat, lon: tracks[0].lon, label: originIata || 'Departure' },
    { lat: tracks[tracks.length - 1].lat, lon: tracks[tracks.length - 1].lon,
      label: diverted && actualDestinationIata ? `${actualDestinationIata} (Diverted)` : destinationIata || 'Arrival' },
  ] : []);
  function openProvider() { window.open('https://www.flightradar24.com', '_blank', 'noopener,noreferrer'); }
</script>

<ResultEmbedFullscreen
  result={dc}
  {mapCenter}
  {mapMarkers}
  mapPath={tracks}
  mapZoom={5}
  appId="travel"
  skillId="get_flight"
  {onClose}
  skillIconName="travel"
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    <EmbedHeaderCtaButton label="Open on Flightradar24" onclick={openProvider} testId="external-provider-cta" />
  {/snippet}
  {#snippet summary()}
    {#if durationDisplay}<ResultEmbedInfo icon="clock" label="Flight duration" value={durationDisplay}>{durationDisplay}</ResultEmbedInfo>{/if}
    {#if distanceDisplay}<ResultEmbedInfo icon="route" label="Recorded flight distance" value={distanceDisplay}>{distanceDisplay}</ResultEmbedInfo>{/if}
    <ResultEmbedInfo icon="plane" label="Track coverage" value={hasTrackData ? `${tracks.length} points` : 'No track data'} state={hasTrackData ? 'yes' : 'unknown'}>{hasTrackData ? 'Recorded GPS flight track supplied by Flightradar24.' : 'No recorded track is available; a route is not inferred.'}</ResultEmbedInfo>
  {/snippet}
  {#snippet detailContent()}
    <div class="flight-details-fullscreen" data-testid="flight-track-details">
      <!-- Date header -->
      {#if displayDate}
        <div class="date-header">{displayDate}</div>
      {/if}

      <!-- Diversion warning -->
      {#if diverted}
        <div class="diversion-warning">
          <span class="diversion-icon">⚠</span>
          Flight diverted
          {#if actualDestinationIata}
            to {actualDestinationIata}
          {/if}
        </div>
      {/if}

      <div class="fr24-attribution">Track data: <a href="https://www.flightradar24.com" target="_blank" rel="noopener noreferrer">Flightradar24</a></div>
      {#if !hasTrackData}<p role="status" data-testid="flight-track-unavailable">No track data available</p>{/if}

      <!-- Flight details grid -->
      <div class="details-grid">
        <!-- Actual takeoff -->
        <div class="detail-row">
          <span class="detail-label">Takeoff</span>
          <span class="detail-value">{takeoffDisplay}</span>
        </div>

        <!-- Actual landing -->
        <div class="detail-row">
          <span class="detail-label">Landing</span>
          <span class="detail-value">{landingDisplay}</span>
        </div>

        <!-- Duration -->
        {#if durationDisplay}
          <div class="detail-row">
            <span class="detail-label">Duration</span>
            <span class="detail-value">{durationDisplay}</span>
          </div>
        {/if}

        <!-- Runway takeoff -->
        {#if runwayTakeoff}
          <div class="detail-row">
            <span class="detail-label">Runway (dep.)</span>
            <span class="detail-value mono">{runwayTakeoff}</span>
          </div>
        {/if}

        <!-- Runway landing -->
        {#if runwayLanding}
          <div class="detail-row">
            <span class="detail-label">Runway (arr.)</span>
            <span class="detail-value mono">{runwayLanding}</span>
          </div>
        {/if}

        <!-- Actual distance -->
        {#if distanceDisplay}
          <div class="detail-row">
            <span class="detail-label">Distance</span>
            <span class="detail-value">{distanceDisplay}</span>
          </div>
        {/if}

        <!-- FR24 ID (for reference) -->
        {#if fr24Id}
          <div class="detail-row detail-row-minor">
            <span class="detail-label">FR24 ID</span>
            <span class="detail-value mono">{fr24Id}</span>
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .flight-details-fullscreen {
    width: 100%;
  }

  .date-header {
    font-size: 0.85rem;
    color: var(--color-text-secondary);
    margin-bottom: var(--spacing-6);
    text-align: center;
  }

  .diversion-warning {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-warning, #f59e0b) 30%, transparent);
    border-radius: var(--radius-4);
    padding: 10px 14px;
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--color-warning, #f59e0b);
    margin-bottom: var(--spacing-8);
  }

  .diversion-icon {
    font-size: 1rem;
  }

  .fr24-attribution {
    font-size: 0.7rem;
    color: var(--color-text-tertiary, var(--color-text-secondary));
    text-align: right;
    margin-bottom: var(--spacing-10);
  }

  .fr24-attribution a {
    color: inherit;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  /* Details grid */
  .details-grid {
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid var(--color-grey-20, rgba(0, 0, 0, 0.08));
    border-radius: var(--radius-5);
    overflow: hidden;
  }

  .detail-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--spacing-6) var(--spacing-8);
    border-bottom: 1px solid var(--color-grey-10, rgba(0, 0, 0, 0.04));
  }

  .detail-row:last-child {
    border-bottom: none;
  }

  .detail-row-minor {
    opacity: 0.65;
  }

  .detail-label {
    font-size: 0.82rem;
    color: var(--color-text-secondary);
    font-weight: 500;
  }

  .detail-value {
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--color-text-primary);
    text-align: right;
  }

  .detail-value.mono {
    font-family: var(--font-mono, monospace);
    font-size: 0.82rem;
    letter-spacing: 0.04em;
  }
</style>
