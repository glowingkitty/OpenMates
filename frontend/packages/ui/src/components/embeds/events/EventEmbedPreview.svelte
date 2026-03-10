<!--
  frontend/packages/ui/src/components/embeds/events/EventEmbedPreview.svelte

  Preview card for a single event (child embed).
  Used inside EventsSearchEmbedFullscreen as clickable cards that open
  EventEmbedFullscreen via ChildEmbedOverlay drill-down.

  Unlike EventsSearchEmbedPreview (the parent search result), this component:
  - Receives structured EventResult data directly from the parent (no embed store lookup)
  - Is NOT mounted by AppSkillUseRenderer — it's instantiated inline by the parent fullscreen
  - Has no cancellation logic (child event embeds are finished by the time they render)
  - Uses showStatus=false and showSkillIcon=false so cards are compact with no bottom bar

  Design mirrors TravelConnectionEmbedPreview.svelte.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

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
  }

  interface Props {
    /** Child embed ID used as UnifiedEmbedPreview id */
    id: string;
    /** Full structured event data */
    event: EventResult;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler that opens EventEmbedFullscreen drill-down */
    onFullscreen?: () => void;
  }

  let {
    id,
    event,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  // ── Display helpers ──────────────────────────────────────────────────────────

  /**
   * Format a date_start ISO string to a short readable date+time.
   * Example: "Sat, Mar 15 · 7:00 PM"
   */
  function formatEventDate(dateStr: string | undefined): string {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return '';
      return (
        d.toLocaleDateString(undefined, {
          weekday: 'short',
          month: 'short',
          day: 'numeric',
        }) +
        ' · ' +
        d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
      );
    } catch {
      return '';
    }
  }

  /**
   * Return short location: "Online" for ONLINE events, "City, Country" for physical.
   */
  function getEventLocation(ev: EventResult): string {
    if (ev.event_type === 'ONLINE') return 'Online';
    if (!ev.venue) return '';
    const parts: string[] = [];
    if (ev.venue.city) parts.push(ev.venue.city);
    if (ev.venue.country) parts.push(ev.venue.country);
    return parts.join(', ');
  }

  /**
   * Map backend provider slugs to human-readable display names.
   * Providers: meetup, luma, classictic, berlin_philharmonic, bachtrack
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
  let eventDate     = $derived(formatEventDate(event.date_start));
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
    // Use Intl.NumberFormat when available for proper currency display
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
    } catch {
      return `${currency} ${amount}`;
    }
  });

  // No-op stop handler — child event embeds are already finished
  async function handleStop() {
    // Not applicable for finished child event embeds
  }
</script>

<UnifiedEmbedPreview
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
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="event-preview-details" class:mobile={isMobileLayout}>
      <!-- Event title -->
      <div class="event-title">{event.title || ''}</div>

      <!-- Date + location row -->
      <div class="event-meta">
        {#if eventDate}
          <span class="event-date">{eventDate}</span>
        {/if}
        {#if eventLocation}
          <span class="event-location">{eventLocation}</span>
        {/if}
      </div>

      <!-- Bottom row: type badge + RSVP count / fee + source -->
      <div class="event-footer">
        {#if event.event_type}
          <span class="event-type-badge" class:online={isOnline}>
            {isOnline ? 'Online' : 'In Person'}
          </span>
        {/if}
        {#if isPaid && feeDisplay}
          <span class="event-fee">{feeDisplay}</span>
        {:else if event.rsvp_count != null && event.rsvp_count > 0}
          <span class="event-rsvp">{event.rsvp_count.toLocaleString()} RSVPs</span>
        {/if}
        {#if providerLabel}
          <span class="event-source">{providerLabel}</span>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ── Details layout ──────────────────────────────────────────────────────── */

  .event-preview-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
    justify-content: center;
    padding: 2px 0;
  }

  .event-preview-details.mobile {
    justify-content: flex-start;
  }

  /* ── Event title ─────────────────────────────────────────────────────────── */

  .event-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .event-preview-details.mobile .event-title {
    font-size: 13px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  /* ── Meta: date + location ───────────────────────────────────────────────── */

  .event-meta {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .event-date {
    font-size: 12px;
    color: var(--color-grey-70);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .event-location {
    font-size: 11px;
    color: var(--color-grey-60);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* ── Footer: type badge + RSVP / fee ────────────────────────────────────── */

  .event-footer {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  /* Type badge: "Online" (teal) or "In Person" (events brand red) */
  .event-type-badge {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 2px 6px;
    border-radius: 20px;
    background: var(--color-app-events-start, #a20000);
    color: #fff;
    flex-shrink: 0;
  }

  .event-type-badge.online {
    background: #1a6b5a;
  }

  .event-fee,
  .event-rsvp {
    font-size: 0.6875rem;
    color: var(--color-grey-60);
  }

  .event-source {
    font-size: 0.6875rem;
    color: var(--color-font-secondary);
    font-weight: 500;
    margin-left: auto;
    flex-shrink: 0;
  }
</style>
