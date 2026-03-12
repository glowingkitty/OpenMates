<!--
  frontend/packages/ui/src/components/embeds/travel/TravelFlightDetailsEmbedPreview.svelte

  Preview card for a standalone get_flight skill result embed.
  Shown when the LLM calls get_flight directly in chat (not via the
  TravelConnectionEmbedFullscreen booking flow).

  Displays: flight number, route (origin→destination), actual takeoff/landing
  times, and a small route indicator. Falls back gracefully if track data is
  unavailable (e.g. the flight was not found).

  Architecture: Uses UnifiedEmbedPreview as base (same as all other embed
  preview components). See docs/architecture/app-skills.md.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

  interface Props {
    /** Embed ID */
    id: string;
    /** IATA flight number (e.g. 'LH2472') */
    flightNumber?: string;
    /** Departure date in YYYY-MM-DD format */
    departureDate?: string;
    /** Origin IATA code (e.g. 'MUC') */
    originIata?: string;
    /** Destination IATA code (e.g. 'LHR') */
    destinationIata?: string;
    /** Actual takeoff datetime (ISO 8601) */
    actualTakeoff?: string;
    /** Actual landing datetime (ISO 8601) */
    actualLanding?: string;
    /** Number of GPS track points available */
    trackPointCount?: number;
    /** Whether the flight was diverted */
    diverted?: boolean;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }

  let {
    id,
    flightNumber,
    departureDate,
    originIata,
    destinationIata,
    actualTakeoff,
    actualLanding,
    trackPointCount = 0,
    diverted = false,
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  /** Route display string (e.g. 'MUC → LHR') */
  let routeDisplay = $derived.by(() => {
    if (originIata && destinationIata) return `${originIata} → ${destinationIata}`;
    if (originIata) return originIata;
    return '';
  });

  /** Skill name shown in the preview header */
  let skillName = $derived(flightNumber || 'Flight Track');

  /** Format an ISO 8601 datetime to a short time string (HH:MM) */
  function formatTime(iso?: string): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  }

  /** Format a date string for display */
  function formatDate(iso?: string): string {
    if (!iso) return departureDate || '';
    try {
      return new Date(iso).toLocaleDateString([], {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return departureDate || '';
    }
  }

  let takeoffTime = $derived(formatTime(actualTakeoff));
  let landingTime = $derived(formatTime(actualLanding));
  let displayDate = $derived(formatDate(actualTakeoff || departureDate));

  let hasTrack = $derived(trackPointCount > 0);
</script>

<UnifiedEmbedPreview
  {id}
  appId="travel"
  skillId="get_flight"
  skillIconName="travel"
  {status}
  skillName={skillName}
  {isMobile}
  {onFullscreen}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="flight-details-preview" class:mobile={isMobileLayout}>
      <!-- Flight number headline -->
      <div class="flight-number-row">
        <span class="flight-number">{flightNumber || '—'}</span>
        {#if diverted}
          <span class="diversion-badge">Diverted</span>
        {/if}
      </div>

      <!-- Route -->
      {#if routeDisplay}
        <div class="route-row">{routeDisplay}</div>
      {/if}

      <!-- Date -->
      {#if displayDate}
        <div class="date-row">{displayDate}</div>
      {/if}

      <!-- Actual times -->
      {#if takeoffTime || landingTime}
        <div class="times-row">
          {#if takeoffTime}
            <span class="time">{takeoffTime}</span>
            <span class="arrow">→</span>
          {/if}
          {#if landingTime}
            <span class="time">{landingTime}</span>
          {/if}
        </div>
      {/if}

      <!-- Track indicator -->
      <div class="track-indicator">
        {#if hasTrack}
          <span class="track-badge">Track available · {trackPointCount} pts</span>
        {:else if status === 'processing'}
          <span class="track-badge track-loading">Loading track…</span>
        {:else}
          <span class="track-badge track-unavailable">No track data</span>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .flight-details-preview {
    padding: 2px 0 4px;
  }

  .flight-number-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 3px;
  }

  .flight-number {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--color-text-primary);
    letter-spacing: 0.02em;
  }

  .diversion-badge {
    font-size: 0.7rem;
    font-weight: 600;
    color: var(--color-warning, #f59e0b);
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 12%, transparent);
    border-radius: 4px;
    padding: 1px 6px;
  }

  .route-row {
    font-size: 0.9rem;
    font-weight: 500;
    color: var(--color-text-primary);
    margin-bottom: 1px;
  }

  .date-row {
    font-size: 0.78rem;
    color: var(--color-text-secondary);
    margin-bottom: 4px;
  }

  .times-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }

  .time {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--color-text-primary);
    font-variant-numeric: tabular-nums;
  }

  .arrow {
    font-size: 0.8rem;
    color: var(--color-text-secondary);
  }

  .track-indicator {
    display: flex;
  }

  .track-badge {
    font-size: 0.7rem;
    font-weight: 500;
    color: var(--color-text-secondary);
    background: var(--color-grey-20, rgba(0, 0, 0, 0.06));
    border-radius: 4px;
    padding: 2px 6px;
  }

  .track-loading {
    color: var(--color-primary);
    background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  }

  .track-unavailable {
    color: var(--color-text-tertiary, var(--color-text-secondary));
  }
</style>
