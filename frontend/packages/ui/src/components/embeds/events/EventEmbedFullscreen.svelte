<!--
  frontend/packages/ui/src/components/embeds/events/EventEmbedFullscreen.svelte

  Fullscreen detail view for a single event (child embed drill-down).
  Opened when user clicks an EventEmbedPreview card inside EventsSearchEmbedFullscreen.

  This component receives the full EventResult object from its parent (no embed loading
  needed — the data is already decoded by EventsSearchEmbedFullscreen's childEmbedTransformer).

  Layout:
  - EmbedTopBar (handled by UnifiedEmbedFullscreen)
  - EmbedHeader: event title as heading, date+location as subtitle
  - Content:
    - Type badge + RSVP count
    - Full date/time (start + end if available)
    - Venue details (physical) or "Online event" notice
    - Organizer name
    - Event description (full text)
    - "View on Meetup" CTA button

  Design mirrors TravelConnectionEmbedFullscreen without the flight-specific sections.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /**
   * Full event result from the events/search skill.
   * Passed directly from EventsSearchEmbedFullscreen — no embed store lookup needed.
   */
  interface EventResult {
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
    /** Full event data from parent's childEmbedTransformer */
    event: EventResult;
    /** Close handler (navigates back to EventsSearchEmbedFullscreen) */
    onClose: () => void;
    /** Whether there is a previous sibling event (for ← → navigation) */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next sibling event */
    hasNextEmbed?: boolean;
    /** Navigate to previous event */
    onNavigatePrevious?: () => void;
    /** Navigate to next event */
    onNavigateNext?: () => void;
  }

  let {
    event,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  // ── Display helpers ──────────────────────────────────────────────────────────

  /**
   * Format ISO datetime to full readable string.
   * Example: "Saturday, March 15, 2026 at 7:00 PM"
   */
  function formatFullDate(dateStr: string | undefined): string {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return '';
      return (
        d.toLocaleDateString(undefined, {
          weekday: 'long',
          year: 'numeric',
          month: 'long',
          day: 'numeric',
        }) +
        ' at ' +
        d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
      );
    } catch {
      return '';
    }
  }

  /**
   * Short date format for the header subtitle.
   * Example: "Sat, Mar 15 · 7:00 PM"
   */
  function formatShortDate(dateStr: string | undefined): string {
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
   * Return a short location string for the header subtitle.
   */
  function getShortLocation(ev: EventResult): string {
    if (ev.event_type === 'ONLINE') return 'Online';
    if (!ev.venue) return '';
    const parts: string[] = [];
    if (ev.venue.city) parts.push(ev.venue.city);
    if (ev.venue.country) parts.push(ev.venue.country);
    return parts.join(', ');
  }

  /**
   * Build a full venue address string.
   */
  function getVenueAddress(ev: EventResult): string {
    const v = ev.venue;
    if (!v) return '';
    const parts: string[] = [];
    if (v.name) parts.push(v.name);
    if (v.address) parts.push(v.address);
    const cityLine: string[] = [];
    if (v.city) cityLine.push(v.city);
    if (v.state) cityLine.push(v.state);
    if (v.country) cityLine.push(v.country);
    if (cityLine.length) parts.push(cityLine.join(', '));
    return parts.join('\n');
  }

  // Derived values for header
  let headerTitle    = $derived(event.title || '');
  let shortDate      = $derived(formatShortDate(event.date_start));
  let shortLocation  = $derived(getShortLocation(event));
  let headerSubtitle = $derived(
    [shortDate, shortLocation].filter(Boolean).join(' · ')
  );

  // Derived values for content area
  let isOnline      = $derived(event.event_type === 'ONLINE');
  let fullDateStart = $derived(formatFullDate(event.date_start));
  let fullDateEnd   = $derived(formatFullDate(event.date_end));
  let venueAddress  = $derived(getVenueAddress(event));

  // Fee display
  let feeDisplay = $derived.by(() => {
    if (!event.is_paid || !event.fee) return '';
    const amount = event.fee.amount;
    const currency = event.fee.currency || '';
    if (amount == null) return '';
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
    } catch {
      return `${currency} ${amount}`;
    }
  });

  /**
   * Open the event URL in a new tab.
   */
  function handleOpenEvent() {
    if (event.url) {
      window.open(event.url, '_blank', 'noopener,noreferrer');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="events"
  skillId="event"
  {onClose}
  skillIconName="event"
  showSkillIcon={true}
  embedHeaderTitle={headerTitle}
  embedHeaderSubtitle={headerSubtitle}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet content()}
    <div class="event-fullscreen">
      <!-- Type badge + RSVP row -->
      <div class="event-meta-row">
        {#if event.event_type}
          <span class="event-type-badge" class:online={isOnline}>
            {isOnline ? 'Online' : 'In Person'}
          </span>
        {/if}
        {#if event.is_paid && feeDisplay}
          <span class="event-fee-badge">{feeDisplay}</span>
        {:else if !event.is_paid}
          <span class="event-free-badge">Free</span>
        {/if}
        {#if event.rsvp_count != null && event.rsvp_count > 0}
          <span class="event-rsvp">{event.rsvp_count.toLocaleString()} RSVPs</span>
        {/if}
      </div>

      <!-- Full date/time -->
      {#if fullDateStart}
        <div class="event-section">
          <div class="section-label">Date & Time</div>
          <div class="section-value">{fullDateStart}</div>
          {#if fullDateEnd}
            <div class="section-value secondary">Ends {fullDateEnd}</div>
          {/if}
        </div>
      {/if}

      <!-- Venue / Location -->
      {#if isOnline}
        <div class="event-section">
          <div class="section-label">Location</div>
          <div class="section-value">Online event</div>
        </div>
      {:else if venueAddress}
        <div class="event-section">
          <div class="section-label">Location</div>
          <div class="section-value venue-address">{venueAddress}</div>
        </div>
      {/if}

      <!-- Organizer -->
      {#if event.organizer?.name}
        <div class="event-section">
          <div class="section-label">Organizer</div>
          <div class="section-value">{event.organizer.name}</div>
        </div>
      {/if}

      <!-- Description -->
      {#if event.description}
        <div class="event-section">
          <div class="section-label">About</div>
          <!-- Description comes from Meetup as plain text (may contain HTML).
               We render it as preformatted text to avoid XSS while preserving line breaks. -->
          <div class="event-description">{event.description}</div>
        </div>
      {/if}

      <!-- CTA: View on Meetup -->
      {#if event.url}
        <div class="event-cta">
          <button class="cta-button" onclick={handleOpenEvent}>
            {$text('embeds.view_on_meetup')}
          </button>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ── Event fullscreen layout ─────────────────────────────────────────────── */

  .event-fullscreen {
    max-width: 640px;
    margin: 60px auto 120px;
    padding: 0 20px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  @container fullscreen (max-width: 500px) {
    .event-fullscreen {
      margin-top: 70px;
      padding: 0 16px;
    }
  }

  /* ── Meta row: type badge + RSVP ────────────────────────────────────────── */

  .event-meta-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  .event-type-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: var(--color-app-events-start, #a20000);
    color: #fff;
  }

  .event-type-badge.online {
    background: #1a6b5a;
  }

  .event-fee-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 12px;
    font-weight: 600;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .event-free-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(34, 197, 94, 0.15);
    color: var(--color-font-primary);
  }

  .event-rsvp {
    font-size: 13px;
    color: var(--color-grey-60);
  }

  /* ── Info sections ───────────────────────────────────────────────────────── */

  .event-section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .section-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-grey-60);
  }

  .section-value {
    font-size: 15px;
    color: var(--color-font-primary);
    line-height: 1.5;
  }

  .section-value.secondary {
    font-size: 13px;
    color: var(--color-grey-60);
  }

  /* Venue address preserves newlines between name/address/city */
  .venue-address {
    white-space: pre-line;
    font-size: 14px;
  }

  /* ── Description ─────────────────────────────────────────────────────────── */

  .event-description {
    font-size: 14px;
    color: var(--color-font-primary);
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 400px;
    overflow-y: auto;
    /* Subtle fade at the bottom to hint scrollability */
    -webkit-mask-image: linear-gradient(to bottom, black 85%, transparent 100%);
    mask-image: linear-gradient(to bottom, black 85%, transparent 100%);
  }

  /* ── CTA button ──────────────────────────────────────────────────────────── */

  .event-cta {
    display: flex;
    justify-content: center;
    padding-top: 8px;
  }

  .cta-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 13px 32px;
    border-radius: 100px;
    font-size: 15px;
    font-weight: 500;
    cursor: pointer;
    border: none;
    font-family: 'Lexend Deca', sans-serif;
    /* Events brand gradient */
    background: linear-gradient(
      135deg,
      var(--color-app-events-start, #a20000),
      var(--color-app-events-end, #e61b3e)
    );
    color: #fff;
    transition: opacity 0.15s ease, scale 0.1s ease;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.2));
  }

  .cta-button:hover {
    opacity: 0.9;
    scale: 1.02;
  }

  .cta-button:active {
    opacity: 1;
    scale: 0.98;
    filter: none;
  }

  /* ── Skill icon in EmbedHeader ───────────────────────────────────────────── */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="event"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/event.svg');
    mask-image: url('@openmates/ui/static/icons/event.svg');
  }
</style>
