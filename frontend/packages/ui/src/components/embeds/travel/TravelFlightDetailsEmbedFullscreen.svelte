<!--
  frontend/packages/ui/src/components/embeds/travel/TravelFlightDetailsEmbedFullscreen.svelte

  Fullscreen view for a standalone get_flight skill result embed.
  Shows the real flight GPS track on a Leaflet/OpenStreetMap map, plus enrichment
  details: actual takeoff/landing times, runway used, actual distance, diversion.

  This component is used when the LLM calls get_flight directly in chat (not via
  the TravelConnectionEmbedFullscreen booking flow). The track data comes from the
  embed content decoded by the embed resolver.

  Architecture: Uses UnifiedEmbedFullscreen as base.
  See docs/architecture/app-skills.md for the skill execution model.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { onDestroy } from 'svelte';
  import 'leaflet/dist/leaflet.css';
  import type { Map as LeafletMap } from 'leaflet';

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

  let dc = $derived(data.decodedContent);

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

  // ---------------------------------------------------------------------------
  // Route map (Leaflet / OpenStreetMap)
  // ---------------------------------------------------------------------------

  let mapContainer: HTMLDivElement | undefined = $state(undefined);
  let L: typeof import('leaflet') | null = null;
  let map: LeafletMap | null = null;
  let mapInitialized = $state(false);

  /** Detect dark mode from CSS custom property or media query */
  let isDarkMode = $derived.by(() => {
    if (typeof window === 'undefined') return false;
    const cssVar = getComputedStyle(document.documentElement).getPropertyValue('--is-dark-mode').trim();
    if (cssVar === '1' || cssVar === 'true') return true;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  });

  /** Whether we have enough track data to show the map */
  let hasTrackData = $derived(tracks.length >= 2);

  /**
   * Initialize the Leaflet map showing the real GPS flight track.
   * If track data is available, draws the actual polyline from FR24.
   */
  async function initializeMap() {
    if (!mapContainer || !hasTrackData || mapInitialized) return;

    try {
      L = await import('leaflet');

      const firstPoint = tracks[0];
      map = L.map(mapContainer, {
        center: [firstPoint.lat, firstPoint.lon],
        zoom: 5,
        zoomControl: true,
        scrollWheelZoom: false,
        attributionControl: true,
      });

      // OSM tile layer
      const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
          '| Track: <a href="https://www.flightradar24.com" target="_blank" rel="noopener">Flightradar24</a>',
        className: isDarkMode ? 'dark-tiles' : '',
      }).addTo(map);

      // Airport marker icon
      const airportIcon = L.divIcon({
        className: 'travel-route-marker',
        html: '<div class="marker-dot"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });

      // Start marker
      L.marker([tracks[0].lat, tracks[0].lon], { icon: airportIcon })
        .addTo(map)
        .bindPopup(originIata || 'Departure');

      // End marker
      const lastPoint = tracks[tracks.length - 1];
      L.marker([lastPoint.lat, lastPoint.lon], { icon: airportIcon })
        .addTo(map)
        .bindPopup(
          diverted && actualDestinationIata
            ? `${actualDestinationIata} (Diverted)`
            : destinationIata || 'Arrival',
        );

      // Draw real track polyline from FR24 GPS data
      const latLngs = tracks.map(p => L.latLng(p.lat, p.lon));
      L.polyline(latLngs, {
        color: 'var(--color-primary, #6366f1)',
        weight: 2.5,
        opacity: 0.85,
      }).addTo(map);

      // Fit bounds to the track
      const bounds = L.latLngBounds(latLngs);
      map.fitBounds(bounds, { padding: [40, 40] });

      // Update tiles on dark mode change
      const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
      darkModeQuery.addEventListener('change', () => {
        const container = tileLayer.getContainer();
        if (container) {
          if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            container.classList.add('dark-tiles');
          } else {
            container.classList.remove('dark-tiles');
          }
        }
      });

      mapInitialized = true;
    } catch (err) {
      console.error('[TravelFlightDetailsEmbedFullscreen] Failed to initialize map:', err);
    }
  }

  // Initialize map when container and track data are ready
  $effect(() => {
    if (mapContainer && hasTrackData && !mapInitialized) {
      initializeMap();
    }
  });

  // Cleanup on destroy
  onDestroy(() => {
    if (map) {
      map.remove();
      map = null;
    }
  });
</script>

<UnifiedEmbedFullscreen
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
  {#snippet content()}
    <div class="flight-details-fullscreen">
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

      <!-- Route map -->
      {#if hasTrackData}
        <div class="route-map-container" bind:this={mapContainer}></div>
        <div class="fr24-attribution">
          Track data: <a href="https://www.flightradar24.com" target="_blank" rel="noopener noreferrer">Flightradar24</a>
        </div>
      {:else}
        <div class="no-track-placeholder">
          <span class="no-track-icon">✈</span>
          <span class="no-track-text">No track data available</span>
        </div>
      {/if}

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
</UnifiedEmbedFullscreen>

<style>
  .flight-details-fullscreen {
    max-width: 600px;
    margin: 60px auto 120px;
    padding: 0 20px;
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

  /* Map */
  .route-map-container {
    width: 100%;
    height: 280px;
    border-radius: var(--radius-5);
    overflow: hidden;
    margin-bottom: var(--spacing-3);
    /* Dark filter for OpenStreetMap tiles in dark mode */
    :global(.dark-tiles) {
      filter: invert(100%) hue-rotate(180deg) brightness(0.85) contrast(1.1);
    }
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

  .no-track-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-4);
    padding: var(--spacing-20) var(--spacing-10);
    background: var(--color-grey-10, rgba(0, 0, 0, 0.04));
    border-radius: var(--radius-5);
    margin-bottom: var(--spacing-10);
  }

  .no-track-icon {
    font-size: 2rem;
    opacity: 0.4;
  }

  .no-track-text {
    font-size: 0.85rem;
    color: var(--color-text-secondary);
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
