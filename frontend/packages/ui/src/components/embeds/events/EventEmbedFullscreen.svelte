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
  import { text } from '@repo/ui';

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
  }

  interface Props {
    event: EventResult;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
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

  // ── Display helpers ──

  function formatFullDate(dateStr: string | undefined): string {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return '';
      return d.toLocaleDateString(undefined, {
        weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
      }) + ' at ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    } catch { return ''; }
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

  let isOnline      = $derived(event.event_type === 'ONLINE');
  let fullDateStart = $derived(formatFullDate(event.date_start));
  let fullDateEnd   = $derived(formatFullDate(event.date_end));
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
      case 'classictic':          return 'Classictic';
      case 'berlin_philharmonic': return 'Berlin Philharmonic';
      case 'bachtrack':           return 'Bachtrack';
      default:                    return provider || '';
    }
  }

  let providerLabel  = $derived(getProviderLabel(event.provider));
  // Uses existing open_on_provider i18n key: "Open on {provider}" (all 20 locales)
  let openButtonText = $derived($text('embeds.open_on_provider').replace('{provider}', providerLabel));

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
  mapZoom={15}
  {mapMarkers}
>
  {#snippet detailContent()}
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
        <div class="event-description">{event.description}</div>
      </div>
    {/if}
  {/snippet}

  {#snippet ctaContent()}
    {#if event.url}
      <button class="cta-button" onclick={handleOpenEvent}>
        {openButtonText}
      </button>
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
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
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: var(--color-app-events-start, #a20000);
    color: #fff; /* intentional: always white on brand colour */
  }

  .event-type-badge.online {
    background: #1a6b5a; /* intentional: brand teal for online events */
  }

  .event-fee-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .event-free-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
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
    padding: 4px 12px;
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
    gap: 4px;
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

  .section-value.secondary {
    font-size: 0.8125rem;
    color: var(--color-grey-60);
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
    max-height: 300px;
    overflow-y: auto;
    -webkit-mask-image: linear-gradient(to bottom, black 85%, transparent 100%);
    mask-image: linear-gradient(to bottom, black 85%, transparent 100%);
  }

  .cta-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 13px 32px;
    border-radius: 100px;
    font-size: 0.9375rem;
    font-weight: 500;
    cursor: pointer;
    border: none;
    font-family: 'Lexend Deca', sans-serif;
    background: linear-gradient(135deg, var(--color-app-events-start, #a20000), var(--color-app-events-end, #e61b3e));
    color: #fff; /* intentional: always white on brand gradient */
    transition: opacity 0.15s ease, scale 0.1s ease;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.2));
    width: 100%;
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

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="event"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/event.svg');
    mask-image: url('@openmates/ui/static/icons/event.svg');
  }
</style>
