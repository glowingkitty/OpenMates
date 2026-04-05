<!--
  frontend/packages/ui/src/components/embeds/events/EventEmbedFullscreen.svelte

  Fullscreen detail view for a single event (child embed drill-down).
  Uses EntryWithMapTemplate for responsive map + detail card layout.

  Shows map when venue has lat/lon coordinates (Meetup events).
  Falls back to details-only layout when no coordinates (Classictic, online events).

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

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
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    /** Embed ID forwarded to UnifiedEmbedFullscreen for the share handler */
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  // Build the event object from data.decodedContent.
  // Must be $derived so it updates when navigating between results (prev/next).
  // Handles both nested venue object (from search transformer) and flat TOON fields
  // (venue_lat, venue_lon, etc. — from _flatten_for_toon_tabular in embed_service.py).
  let dc = $derived(data.decodedContent);

  /** Parse a number from unknown value (handles TOON string→number edge cases). */
  function asNumber(v: unknown): number | undefined {
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string') { const n = Number(v); if (Number.isFinite(n)) return n; }
    return undefined;
  }

  function asString(v: unknown): string | undefined {
    return typeof v === 'string' ? v : undefined;
  }

  let event: EventResult = $derived.by(() => {
    // Venue: try nested object first, fall back to flat TOON fields (venue_lat, venue_lon, etc.)
    let venue: EventResult['venue'] | undefined;
    const rawVenue = dc.venue;
    if (rawVenue && typeof rawVenue === 'object') {
      const v = rawVenue as Record<string, unknown>;
      venue = {
        name: asString(v.name), address: asString(v.address),
        city: asString(v.city), state: asString(v.state), country: asString(v.country),
        lat: asNumber(v.lat), lon: asNumber(v.lon),
      };
    } else if (dc.venue_city || dc.venue_country || dc.venue_lat != null) {
      venue = {
        name: asString(dc.venue_name), address: asString(dc.venue_address),
        city: asString(dc.venue_city), state: asString(dc.venue_state), country: asString(dc.venue_country),
        lat: asNumber(dc.venue_lat), lon: asNumber(dc.venue_lon),
      };
    }

    // Organizer: nested or flat
    let organizer: EventResult['organizer'] | undefined;
    const rawOrg = dc.organizer;
    if (rawOrg && typeof rawOrg === 'object') {
      const o = rawOrg as Record<string, unknown>;
      organizer = { id: asString(o.id), name: asString(o.name), slug: asString(o.slug) };
    } else if (dc.organizer_name) {
      organizer = { id: asString(dc.organizer_id), name: asString(dc.organizer_name), slug: asString(dc.organizer_slug) };
    }

    // Fee: nested or flat
    let fee: EventResult['fee'] | undefined;
    const rawFee = dc.fee;
    if (rawFee && typeof rawFee === 'object') {
      const f = rawFee as Record<string, unknown>;
      fee = { amount: asNumber(f.amount), currency: asString(f.currency) };
    } else if (dc.fee_amount != null) {
      fee = { amount: asNumber(dc.fee_amount), currency: asString(dc.fee_currency) };
    }

    return {
      embed_id: asString(dc.embed_id) || (embedId || ''),
      id: asString(dc.id),
      provider: asString(dc.provider),
      title: asString(dc.title),
      description: asString(dc.description),
      url: asString(dc.url),
      date_start: asString(dc.date_start),
      date_end: asString(dc.date_end),
      timezone: asString(dc.timezone),
      event_type: asString(dc.event_type),
      venue,
      organizer,
      rsvp_count: asNumber(dc.rsvp_count),
      is_paid: typeof dc.is_paid === 'boolean' ? dc.is_paid : undefined,
      fee,
      image_url: asString(dc.image_url) ?? null,
    };
  });

  // ── Display helpers ──

  interface DateTimeDisplay {
    relativeLabel: string;
    lines: string[];
  }

  function parseDate(dateStr: string | undefined): Date | null {
    if (!dateStr) return null;
    const date = new Date(dateStr);
    return isNaN(date.getTime()) ? null : date;
  }

  function isSameCalendarDay(start: Date, end: Date): boolean {
    return start.getFullYear() === end.getFullYear()
      && start.getMonth() === end.getMonth()
      && start.getDate() === end.getDate();
  }

  function formatDateOnly(dateStr: string | undefined): string {
    const date = parseDate(dateStr);
    if (!date) return '';
    return date.toLocaleDateString(undefined, {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  }

  function formatTimeOnly(dateStr: string | undefined): string {
    const date = parseDate(dateStr);
    if (!date) return '';
    return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }

  function formatDateTime(dateStr: string | undefined): string {
    const date = parseDate(dateStr);
    if (!date) return '';
    return `${formatDateOnly(dateStr)} ${formatTimeOnly(dateStr)}`;
  }

  function buildDateTimeDisplay(startStr: string | undefined, endStr: string | undefined): DateTimeDisplay {
    const start = parseDate(startStr);
    if (!start) {
      return { relativeLabel: '', lines: [] };
    }

    const end = parseDate(endStr);
    const relativeDayLabel = getRelativeDayLabel(startStr);
    const relativeLabel = relativeDayLabel === 'today'
      ? 'Today'
      : relativeDayLabel === 'tomorrow'
        ? 'Tomorrow'
        : '';

    if (end && !isSameCalendarDay(start, end)) {
      return {
        relativeLabel: '',
        lines: [formatDateTime(startStr), `to ${formatDateTime(endStr)}`],
      };
    }

    const dateLine = formatDateOnly(startStr);
    const startTime = formatTimeOnly(startStr);
    const endTime = formatTimeOnly(endStr);
    const timeLine = endTime ? `${startTime} to ${endTime}` : startTime;

    return {
      relativeLabel,
      lines: [dateLine, timeLine].filter(Boolean),
    };
  }

  function formatShortDate(dateStr: string | undefined): string {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return '';
      return d.toLocaleDateString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric',
      }) + ' · ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    } catch { return ''; }
  }

  /**
   * Compare a Date to today/tomorrow (date portion only, local time).
   * Returns 'today' | 'tomorrow' | null.
   */
  function getRelativeDayLabel(dateStr: string | undefined): 'today' | 'tomorrow' | null {
    if (!dateStr) return null;
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return null;
      const now = new Date();
      const eventDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
      const today    = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
      if (eventDay.getTime() === today.getTime())    return 'today';
      if (eventDay.getTime() === tomorrow.getTime()) return 'tomorrow';
      return null;
    } catch { return null; }
  }

  function getShortLocation(ev: EventResult): string {
    if (ev.event_type === 'ONLINE') return 'Online';
    if (!ev.venue) return '';
    const parts: string[] = [];
    if (ev.venue.city) parts.push(ev.venue.city);
    if (ev.venue.country) parts.push(ev.venue.country);
    return parts.join(', ');
  }

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

  let headerTitle    = $derived(event.title || '');
  let shortDate      = $derived(formatShortDate(event.date_start));
  let shortLocation  = $derived(getShortLocation(event));
  let headerSubtitle = $derived([shortDate, shortLocation].filter(Boolean).join(' · '));

  let isOnline          = $derived(event.event_type === 'ONLINE');
  let dateTimeDisplay   = $derived(buildDateTimeDisplay(event.date_start, event.date_end));
  let venueAddress  = $derived(getVenueAddress(event));

  // Map data — only when venue has coordinates
  let mapCenter = $derived(
    !isOnline && event.venue?.lat != null && event.venue?.lon != null
      ? { lat: event.venue.lat, lon: event.venue.lon }
      : undefined
  );

  let mapMarkers = $derived(
    mapCenter
      ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: event.venue?.name || event.title }]
      : []
  );

  let feeDisplay = $derived.by(() => {
    if (!event.is_paid || !event.fee) return '';
    const amount = event.fee.amount;
    const currency = event.fee.currency || '';
    if (amount == null) return '';
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
    } catch { return `${currency} ${amount}`; }
  });

  /**
   * Map backend provider slugs to human-readable display names.
   * Providers: meetup, luma, classictic, berlin_philharmonic, bachtrack
   */
  function getProviderLabel(provider: string | undefined): string {
    switch (provider?.toLowerCase()) {
      case 'meetup':              return 'Meetup';
      case 'luma':                return 'Luma';
      case 'eventbrite':          return 'Eventbrite';
      case 'classictic':          return 'Classictic';
      case 'berlin_philharmonic': return 'Berlin Philharmonic';
      case 'bachtrack':           return 'Bachtrack';
      default:                    return provider || '';
    }
  }

  function getCtaPrefix(provider: string | undefined): 'register' | 'book' | 'open' {
    const normalizedProvider = provider?.toLowerCase() || '';

    if (['luma', 'eventbrite', 'meetup'].includes(normalizedProvider)) {
      return 'register';
    }

    if (['classictic', 'berlin_philharmonic', 'bachtrack', 'ticketmaster', 'eventim', 'dice'].includes(normalizedProvider)) {
      return 'book';
    }

    return 'open';
  }

  let providerLabel  = $derived(getProviderLabel(event.provider));
  let eventImageUrl = $derived.by(() => {
    const rawImageUrl = event.image_url || event.cover_url;
    return rawImageUrl ? proxyImage(rawImageUrl, MAX_WIDTH_HEADER_IMAGE) : '';
  });
  let openButtonText = $derived.by(() => {
    if (!providerLabel) return '';

    const ctaPrefix = getCtaPrefix(event.provider);
    if (ctaPrefix === 'register') return `Register on ${providerLabel}`;
    if (ctaPrefix === 'book') return `Book on ${providerLabel}`;

    return $text('embeds.open_on_provider').replace('{provider}', providerLabel);
  });

  function handleOpenEvent() {
    if (event.url) window.open(event.url, '_blank', 'noopener,noreferrer');
  }
</script>

<EntryWithMapTemplate
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
  {mapCenter}
  mapZoom={13}
  {mapMarkers}
  currentEmbedId={embedId}
>
  {#snippet embedHeaderCta()}
    {#if event.url && openButtonText}
      <EmbedHeaderCtaButton label={openButtonText} onclick={handleOpenEvent} />
    {/if}
  {/snippet}

  {#snippet detailContent(_ctx)}
    {#if eventImageUrl}
      <img class="event-image" src={eventImageUrl} alt={event.title || 'Event'} loading="lazy" />
    {/if}

    <!-- Type badge + RSVP row + source -->
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
      {#if providerLabel}
        <span class="event-source-badge">{providerLabel}</span>
      {/if}
    </div>

    <!-- Full date/time — show Today/Tomorrow label when applicable -->
    {#if dateTimeDisplay.lines.length > 0}
      <div class="event-section">
        <div class="section-label">Date & Time</div>
        {#if dateTimeDisplay.relativeLabel}
          <div class="section-value date-relative">{dateTimeDisplay.relativeLabel}</div>
        {/if}
        {#each dateTimeDisplay.lines as dateTimeLine}
          <div class="section-value">{dateTimeLine}</div>
        {/each}
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
        <div class="event-description">{event.description}</div>
      </div>
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
  .event-image {
    width: 100%;
    height: 190px;
    object-fit: cover;
    border-radius: var(--radius-5);
  }

  .event-meta-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--spacing-4);
  }

  .event-type-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: var(--color-app-events-start, #a20000);
    color: var(--color-grey-0); /* intentional: always white on brand colour */
  }

  .event-type-badge.online {
    background: #1a6b5a; /* intentional: brand teal for online events */
  }

  .event-fee-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .event-free-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    background: rgba(34, 197, 94, 0.15);
    color: var(--color-font-primary);
  }

  .event-rsvp {
    font-size: 0.8125rem;
    color: var(--color-grey-60);
  }

  .event-source-badge {
    display: inline-flex;
    align-items: center;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 500;
    background: var(--color-grey-15);
    color: var(--color-font-secondary);
    border: 1px solid var(--color-grey-25);
  }

  .event-section {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
  }

  .section-label {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-grey-60);
  }

  .section-value {
    font-size: 0.9375rem;
    color: var(--color-font-primary);
    line-height: 1.5;
  }

  .venue-address {
    white-space: pre-line;
    font-size: 0.875rem;
  }

  .event-description {
    font-size: 0.875rem;
    color: var(--color-font-primary);
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* Today / Tomorrow label — larger than the regular date value */
  .date-relative {
    font-size: 1.125rem;
    font-weight: 700;
    color: var(--color-font-primary);
  }

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="event"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/event.svg');
    mask-image: url('@openmates/ui/static/icons/event.svg');
  }
</style>
