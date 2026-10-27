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
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import EmbedCalendarDate from '../EmbedCalendarDate.svelte';

  interface Props {
    resultContext?: 'auto' | 'chat' | 'results';
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
    resultContext = 'auto',
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
  let occurrenceDate = $derived([actualTakeoff, departureDate].find(value =>
    typeof value === 'string' && value.length > 0 && !Number.isNaN(new Date(value).getTime())));
  let displayDate = $derived(formatDate(occurrenceDate));

  let hasTrack = $derived(trackPointCount > 0);
</script>

<UnifiedEmbedPreview
  resultPreview
  {resultContext}
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
  {#snippet details()}
    <ResultEmbedCard title={flightNumber || 'Flight Track'} description={routeDisplay} sourceLabel="Flightradar24" textFirst>
      {#snippet badge()}{#if occurrenceDate}<EmbedCalendarDate date={occurrenceDate} />{/if}{/snippet}
      {#snippet facts()}
        {#if displayDate}<span>{displayDate}</span>{/if}
        {#if takeoffTime || landingTime}<span>{takeoffTime || '—'} → {landingTime || '—'}</span>{/if}
        {#if diverted}<strong>Diverted</strong>{/if}
        <span>{hasTrack ? `Track available · ${trackPointCount} pts` : status === 'processing' ? 'Loading track…' : 'No track data'}</span>
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>
