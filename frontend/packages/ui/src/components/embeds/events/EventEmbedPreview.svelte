<!--
  frontend/packages/ui/src/components/embeds/events/EventEmbedPreview.svelte

  Preview card for a single event (child embed).
  Used inside EventsSearchEmbedFullscreen as clickable cards that open
  EventEmbedFullscreen via ChildEmbedOverlay drill-down.

  Shows event image on the right side (matching WebsiteEmbedPreview pattern)
  with text content (title, date, location, badges) on the left.

  Unlike EventsSearchEmbedPreview (the parent search result), this component:
  - Receives structured EventResult data directly from the parent (no embed store lookup)
  - Is NOT mounted by AppSkillUseRenderer — it's instantiated inline by the parent fullscreen
  - Has no cancellation logic (child event embeds are finished by the time they render)
  - Uses showStatus=false and showSkillIcon=false so cards are compact with no bottom bar

  Design mirrors WebsiteEmbedPreview.svelte image-right pattern.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

  /**
   * A single event result from the events/search skill backend.
   * Passed in by EventsSearchEmbedFullscreen after transforming child embed content.
   */
  interface EventResult {
    /** Child embed ID */
    embed_id: string;
    id?: string;
    provider?: string;
    title?: string;
    description?: string;
    url?: string;
    date_start?: string;
    date_end?: string;
    timezone?: string;
    /** "PHYSICAL" or "ONLINE" */
    event_type?: string;
    venue?: {
      name?: string;
      address?: string;
      city?: string;
      state?: string;
      country?: string;
      lat?: number;
      lon?: number;
    };
    organizer?: {
      id?: string;
      name?: string;
      slug?: string;
    };
    rsvp_count?: number;
    is_paid?: boolean;
    fee?: {
      amount?: number;
      currency?: string;
    };
    image_url?: string | null;
    cover_url?: string | null;
  }

  interface Props {
    resultContext?: 'auto' | 'chat' | 'results';
    /** Child embed ID used as UnifiedEmbedPreview id */
    id: string;
    /** Full structured event data */
    event: EventResult;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Optional localized labels for compact preview metadata. */
    onlineLabel?: string;
    inPersonLabel?: string;
    rsvpLabel?: string;
    /** Click handler that opens EventEmbedFullscreen drill-down */
    onFullscreen: () => void;
  }

  let {
    resultContext = 'auto',
    id,
    event,
    isMobile = false,
    onlineLabel = 'Online',
    inPersonLabel = 'In Person',
    rsvpLabel = 'RSVPs',
    onFullscreen,
  }: Props = $props();

  // ── Display helpers ──────────────────────────────────────────────────────────

  interface EventDateParts {
    date: string;
    time: string;
  }

  /**
   * Format a date_start ISO string to short readable date and time lines.
   * Shows relative day labels for today/tomorrow.
   */
  function formatEventDateParts(dateStr: string | undefined): EventDateParts {
    if (!dateStr) return { date: '', time: '' };
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return { date: '', time: '' };
      const now = new Date();
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const startOfTomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
      const startOfDayAfterTomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 2);
      const dateOnly = new Date(d.getFullYear(), d.getMonth(), d.getDate());

      const monthDay = d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
      });
      const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });

      if (dateOnly.getTime() === startOfToday.getTime()) {
        return { date: `Today, ${monthDay}`, time };
      }

      if (dateOnly.getTime() === startOfTomorrow.getTime()) {
        return { date: `Tomorrow, ${monthDay}`, time };
      }

      const dayLabel =
        dateOnly >= startOfDayAfterTomorrow
          ? d.toLocaleDateString(undefined, {
              weekday: 'short',
              month: 'short',
              day: 'numeric',
            })
          : monthDay;

      return { date: dayLabel, time };
    } catch {
      return { date: '', time: '' };
    }
  }

  /**
   * Return short location: "Online" for ONLINE events, "City, Country" for physical.
   */
  function getEventLocation(ev: EventResult): string {
    if (ev.event_type === 'ONLINE') return onlineLabel;
    if (!ev.venue) return '';
    const parts: string[] = [];
    if (ev.venue.city) parts.push(ev.venue.city);
    if (ev.venue.country) parts.push(ev.venue.country);
    return parts.join(', ');
  }

  /**
   * Map backend provider slugs to human-readable display names.
   */
  function getProviderLabel(provider: string | undefined): string {
    switch (provider?.toLowerCase()) {
      case 'meetup':              return 'Meetup';
      case 'luma':                return 'Luma';
      case 'classictic':          return 'Classictic';
      case 'berlin_philharmonic': return 'Berlin Philharmonic';
      case 'bachtrack':           return 'Bachtrack';
      default:                    return provider || '';
    }
  }

  // Derived display values
  let eventDateParts = $derived(formatEventDateParts(event.date_start));
  let eventLocation = $derived(getEventLocation(event));
  let isOnline      = $derived(event.event_type === 'ONLINE');
  let isPaid        = $derived(event.is_paid ?? false);
  let providerLabel = $derived(getProviderLabel(event.provider));

  // Format fee for display (e.g. "€12.00")
  let feeDisplay = $derived.by(() => {
    if (!isPaid || !event.fee) return '';
    const amount = event.fee.amount;
    const currency = event.fee.currency || '';
    if (amount == null) return '';
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
    } catch {
      return `${currency} ${amount}`;
    }
  });

  let eventImageUrl = $derived.by(() => {
    const rawImageUrl = event.image_url || event.cover_url;
    return rawImageUrl ? proxyImage(rawImageUrl, MAX_WIDTH_PREVIEW_THUMBNAIL) : '';
  });



  // No-op stop handler — child event embeds are already finished
  async function handleStop() {
    // Not applicable for finished child event embeds
  }
</script>

<UnifiedEmbedPreview
  resultPreview
  {resultContext}
  {id}
  appId="events"
  skillId="event"
  skillIconName="event"
  status="finished"
  skillName={event.title || ''}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={!!eventImageUrl && !event.title}
>
  {#snippet details()}
    <ResultEmbedCard title={event.title || 'Event'} imageUrl={eventImageUrl || undefined} imageAlt={event.title || 'Event'} description={event.description} sourceLabel={providerLabel || undefined}>
      {#snippet badge()}{#if eventDateParts.date}<span class="date-badge">{eventDateParts.date}</span>{/if}{/snippet}
      {#snippet facts()}
        {#if eventDateParts.time}<span>{eventDateParts.time}</span>{/if}
        {#if eventLocation}<span>{eventLocation}</span>{/if}
        {#if event.event_type}<span>{isOnline ? onlineLabel : inPersonLabel}</span>{/if}
        {#if isPaid && feeDisplay}<span>{feeDisplay}</span>{:else if event.is_paid === false}<span>Free</span>{/if}
        {#if event.rsvp_count != null && event.rsvp_count > 0}<span>{event.rsvp_count.toLocaleString()} {rsvpLabel}</span>{/if}
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>

<style>
.date-badge { background: var(--color-grey-0); color: var(--color-font-primary); padding: var(--spacing-2); border-radius: var(--radius-3); font-size: 12px; }
</style>
