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
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';

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
    /** Child embed ID used as UnifiedEmbedPreview id */
    id: string;
    /** Full structured event data */
    event: EventResult;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler that opens EventEmbedFullscreen drill-down */
    onFullscreen: () => void;
  }

  let {
    id,
    event,
    isMobile = false,
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
    if (ev.event_type === 'ONLINE') return 'Online';
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

  let imageError = $state(false);

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
  hasFullWidthImage={!!eventImageUrl && !event.title}
>
  {#snippet details({ isMobile: isMobileLayout, isLarge: isLargeLayout = false })}
    <div class="event-preview-details" class:mobile={isMobileLayout} class:large={isLargeLayout}>
      <div class="event-content-row">
        <!-- Text content (left side) -->
        <div class="event-text">
          {#if isLargeLayout}
            <div class="event-title">{event.title || ''}</div>
          {/if}

          <!-- Date + location -->
          <div class="event-meta">
            {#if eventDateParts.date}
              <span class="event-date">{eventDateParts.date}</span>
            {/if}
            {#if eventDateParts.time}
              <span class="event-time">{eventDateParts.time}</span>
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

        <!-- Image (right side) -->
        {#if eventImageUrl && !imageError && !isMobileLayout}
          <div class="event-preview-image">
            <img
              src={eventImageUrl}
              alt={event.title || 'Event'}
              loading="lazy"
              crossorigin="anonymous"
              onerror={(e) => {
                imageError = true;
                handleImageError(e.currentTarget as HTMLImageElement);
              }}
            />
          </div>
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
    height: 100%;
    width: 100%;
    justify-content: center;
    text-align: left;
  }

  .event-preview-details.mobile {
    justify-content: flex-start;
  }

  .event-content-row {
    display: flex;
    align-items: stretch;
    flex: 1;
    min-height: 0;
    height: 100%;
    width: 100%;
    gap: var(--spacing-4);
    margin-right: calc(-1 * var(--spacing-10));
  }

  .event-text {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-2);
    flex: 1 1 auto;
    min-width: 0;
    align-self: center;
    padding: 2px 0;
  }

  /* ── Event title (large preview only) ────────────────────────────────────── */

  .event-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.25;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  /* ── Meta: date + location ───────────────────────────────────────────────── */

  .event-meta {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .event-date,
  .event-time {
    font-size: 0.875rem;
    color: var(--color-grey-70);
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .event-preview-details.large .event-date,
  .event-preview-details.large .event-time {
    font-size: 1rem;
  }

  .event-location {
    font-size: 0.75rem;
    color: var(--color-grey-60);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* ── Footer: badges row ──────────────────────────────────────────────────── */

  .event-footer {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--spacing-2);
    margin-top: var(--spacing-1);
  }

  .event-type-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-1) var(--spacing-4);
    border-radius: 100px;
    font-size: 0.625rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: var(--color-app-events-start, #a20000);
    color: #fff; /* intentional: always white on brand colour */
  }

  .event-type-badge.online {
    background: #1a6b5a; /* intentional: brand teal for online events */
  }

  .event-fee {
    font-size: 0.6875rem;
    font-weight: 600;
    color: var(--color-grey-70);
  }

  .event-rsvp {
    font-size: 0.6875rem;
    color: var(--color-grey-60);
  }

  .event-source {
    font-size: 0.6875rem;
    color: var(--color-grey-50);
  }

  /* ── Image (right side) ──────────────────────────────────────────────────── */

  .event-preview-image {
    flex: 0 0 auto;
    aspect-ratio: 1 / 1;
    min-width: 0;
    height: 100%;
    overflow: hidden;
  }

  .event-preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
  }
</style>
