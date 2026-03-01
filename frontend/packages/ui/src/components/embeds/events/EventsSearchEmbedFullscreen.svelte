<!--
  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedFullscreen.svelte

  Fullscreen view for Events Search skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.

  Shows:
  - Header with search query and "via {provider}" formatting
  - List of event cards: title, date, event_type badge, location, RSVP count, link button

  Architecture note:
  Events results are stored as SEPARATE CHILD EMBEDS (like news/web search) — NOT inline in
  the parent embed TOON. The parent embed carries `embed_ids` pointing to the individual event
  child embeds. We use embedIds + childEmbedTransformer so UnifiedEmbedFullscreen handles loading.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /**
   * Single event result from the events/search skill backend.
   * Produced by childEmbedTransformer from each child embed's decoded TOON content.
   * See backend/apps/events/skills/search_skill.py for the full schema.
   */
  interface EventResult {
    /** Child embed ID (required for keying #each) */
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
    /** Always None from backend */
    image_url?: string | null;
  }

  /**
   * Props for events search embed fullscreen.
   * Child embeds are loaded automatically via UnifiedEmbedFullscreen when embedIds is provided.
   */
  interface Props {
    /** Search query */
    query: string;
    /** Events provider (e.g., 'Meetup') */
    provider: string;
    /** Pipe-separated embed IDs or array — loaded automatically by UnifiedEmbedFullscreen */
    embedIds?: string | string[];
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Direction of navigation for slide-in animation */
    navigateDirection?: 'previous' | 'next';
    /** Whether to show the "chat" button (ultra-wide forceOverlayMode) */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }

  let {
    query: queryProp,
    provider: providerProp,
    embedIds,
    status: statusProp,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  // ── Local state ─────────────────────────────────────────────────────────────
  let localQuery    = $state('');
  let localProvider = $state('Meetup');
  let localStatus   = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  // embedIdsOverride: updated by handleEmbedDataUpdated when new embed_ids arrive via streaming.
  // Use override ?? prop so the prop value is available immediately on mount (before any $effect).
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue    = $derived(embedIdsOverride ?? embedIds);

  $effect(() => {
    localQuery    = queryProp    || '';
    localProvider = providerProp || 'Meetup';
    localStatus   = statusProp   || 'finished';
  });

  let query    = $derived(localQuery);
  let provider = $derived(localProvider);
  let status   = $derived(localStatus);

  // Header props for gradient banner
  let embedHeaderTitle    = $derived(query);
  let embedHeaderSubtitle = $derived(`${$text('embeds.via')} ${provider}`);

  // Detect mobile layout via container queries (not window.innerWidth) is preferred in fullscreen,
  // but for backwards compat with event-list class-based mobile detection we keep it minimal here.
  let isMobile = $derived(
    typeof window !== 'undefined' && window.innerWidth <= 500
  );

  // ── Child embed transformer ──────────────────────────────────────────────────
  /**
   * Converts raw decoded TOON content of each child embed into a typed EventResult.
   * Called once per child embed by UnifiedEmbedFullscreen.
   *
   * Child embed TOON content mirrors the fields written by search_skill.py:
   *   id, provider, title, description, url, date_start, date_end, timezone,
   *   event_type, venue (name/address/city/state/country/lat/lon), organizer
   *   (id/name/slug), rsvp_count, is_paid, fee (amount/currency), image_url, type
   *
   * TOON flattening converts nested objects like venue.city → venue_city, so we
   * check both nested and flat field names to be robust.
   */
  function transformToEventResult(childEmbedId: string, content: Record<string, unknown>): EventResult {
    // Venue may be a nested object (raw) or TOON-flattened (venue_city, venue_country, …)
    let venue: EventResult['venue'] | undefined;
    if (content.venue && typeof content.venue === 'object') {
      const v = content.venue as Record<string, unknown>;
      venue = {
        name:    v.name    as string | undefined,
        address: v.address as string | undefined,
        city:    v.city    as string | undefined,
        state:   v.state   as string | undefined,
        country: v.country as string | undefined,
        lat:     v.lat     as number | undefined,
        lon:     v.lon     as number | undefined,
      };
    } else if (content.venue_city || content.venue_country) {
      // TOON-flattened fields
      venue = {
        name:    content.venue_name    as string | undefined,
        address: content.venue_address as string | undefined,
        city:    content.venue_city    as string | undefined,
        state:   content.venue_state   as string | undefined,
        country: content.venue_country as string | undefined,
        lat:     content.venue_lat     as number | undefined,
        lon:     content.venue_lon     as number | undefined,
      };
    }

    // Fee may be nested or flattened
    let fee: EventResult['fee'] | undefined;
    if (content.fee && typeof content.fee === 'object') {
      const f = content.fee as Record<string, unknown>;
      fee = { amount: f.amount as number | undefined, currency: f.currency as string | undefined };
    } else if (content.fee_amount != null) {
      fee = { amount: content.fee_amount as number | undefined, currency: content.fee_currency as string | undefined };
    }

    // Organizer may be nested or flattened
    let organizer: EventResult['organizer'] | undefined;
    if (content.organizer && typeof content.organizer === 'object') {
      const o = content.organizer as Record<string, unknown>;
      organizer = { id: o.id as string | undefined, name: o.name as string | undefined, slug: o.slug as string | undefined };
    } else if (content.organizer_name) {
      organizer = { id: content.organizer_id as string | undefined, name: content.organizer_name as string | undefined, slug: content.organizer_slug as string | undefined };
    }

    return {
      embed_id:   childEmbedId,
      id:         content.id          as string | undefined,
      provider:   content.provider    as string | undefined,
      title:      content.title       as string | undefined,
      description:content.description as string | undefined,
      url:        content.url         as string | undefined,
      date_start: content.date_start  as string | undefined,
      date_end:   content.date_end    as string | undefined,
      timezone:   content.timezone    as string | undefined,
      event_type: content.event_type  as string | undefined,
      venue,
      organizer,
      rsvp_count: content.rsvp_count  as number | undefined,
      is_paid:    content.is_paid     as boolean | undefined,
      fee,
      image_url:  content.image_url   as string | null | undefined,
    };
  }

  // ── Embed data updates ───────────────────────────────────────────────────────
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (typeof c.query    === 'string') localQuery    = c.query;
    if (typeof c.provider === 'string') localProvider = c.provider;
    if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
  }

  // ── Display helpers ──────────────────────────────────────────────────────────

  /**
   * Format a date_start ISO string to a readable local date+time.
   * Returns empty string if date is missing or invalid.
   * Example output: "Sat, Mar 15 · 7:00 PM"
   */
  function formatEventDate(dateStr: string | undefined): string {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return '';
      return d.toLocaleDateString(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric'
      }) + ' · ' + d.toLocaleTimeString(undefined, {
        hour: 'numeric',
        minute: '2-digit'
      });
    } catch {
      return '';
    }
  }

  /**
   * Get a short location string for an event.
   * Online events return "Online".
   * Physical events return "City, Country" (or just country if city missing).
   */
  function getEventLocation(event: EventResult): string {
    if (event.event_type === 'ONLINE') return 'Online';
    if (!event.venue) return '';
    const parts: string[] = [];
    if (event.venue.city)    parts.push(event.venue.city);
    if (event.venue.country) parts.push(event.venue.country);
    return parts.join(', ');
  }
</script>

<UnifiedEmbedFullscreen
  appId="events"
  skillId="search"
  onClose={onClose}
  currentEmbedId={embedId}
  skillIconName="event"
  embedHeaderTitle={embedHeaderTitle}
  embedHeaderSubtitle={embedHeaderSubtitle}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToEventResult}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const events = ctx.children as EventResult[]}

    {#if status === 'error'}
      <div class="error-state">
        <p class="error-title">{$text('chat.an_error_occured')}</p>
      </div>
    {:else if ctx.isLoadingChildren}
      <div class="no-results">
        <p>{$text('embeds.loading')}</p>
      </div>
    {:else if events.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results')}</p>
      </div>
    {:else}
      <div class="events-list" class:mobile={isMobile}>
        {#each events as event (event.embed_id)}
          {@const eventLocation = getEventLocation(event)}
          <div class="event-card">
            <!-- Event header: title + type badge -->
            <div class="event-header">
              <div class="event-title">{event.title || ''}</div>
              {#if event.event_type}
                <span class="event-type-badge" class:online={event.event_type === 'ONLINE'}>
                  {event.event_type === 'ONLINE' ? 'Online' : 'In Person'}
                </span>
              {/if}
            </div>

            <!-- Event meta: date + location -->
            <div class="event-meta">
              {#if event.date_start}
                <div class="event-date">{formatEventDate(event.date_start)}</div>
              {/if}
              {#if eventLocation}
                <div class="event-location">{eventLocation}</div>
              {/if}
            </div>

            <!-- Event footer: RSVP count + link button -->
            <div class="event-footer">
              {#if event.rsvp_count != null && event.rsvp_count > 0}
                <span class="event-rsvp">{event.rsvp_count.toLocaleString()} RSVPs</span>
              {/if}
              {#if event.url}
                <a
                  href={event.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="event-link-button"
                >
                  View Event
                </a>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Error / No Results / Loading States
     =========================================== */

  .no-results,
  .error-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }

  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }

  /* ===========================================
     Events List Layout
     =========================================== */

  .events-list {
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: calc(100% - 20px);
    max-width: 800px;
    margin: 0 auto;
    padding: 0 10px;
    padding-bottom: 120px; /* Space for bottom bar + gradient */
  }

  /* ===========================================
     Event Card
     =========================================== */

  .event-card {
    background: var(--color-surface-raised, var(--color-grey-10, #1e1e1e));
    border: 1px solid var(--color-border, rgba(255, 255, 255, 0.08));
    border-radius: 12px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    transition: border-color 0.15s ease;
  }

  .event-card:hover {
    border-color: var(--color-border-hover, rgba(255, 255, 255, 0.16));
  }

  /* ===========================================
     Event Header: title + type badge
     =========================================== */

  .event-header {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    justify-content: space-between;
  }

  .event-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.4;
    flex: 1;
    /* Limit to 3 lines */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  .events-list.mobile .event-title {
    font-size: 15px;
  }

  /* Type badge: "Online" (teal) or "In Person" (warm) */
  .event-type-badge {
    flex-shrink: 0;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 3px 8px;
    border-radius: 20px;
    background: var(--color-app-events-start, #a20000);
    color: #fff;
    margin-top: 2px;
  }

  .event-type-badge.online {
    background: #1a6b5a;
  }

  /* ===========================================
     Event Meta: date + location
     =========================================== */

  .event-meta {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .event-date {
    font-size: 14px;
    color: var(--color-grey-80);
    font-weight: 500;
  }

  .event-location {
    font-size: 13px;
    color: var(--color-grey-60);
  }

  /* ===========================================
     Event Footer: RSVP + link button
     =========================================== */

  .event-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 2px;
  }

  .event-rsvp {
    font-size: 13px;
    color: var(--color-grey-60);
  }

  .event-link-button {
    display: inline-flex;
    align-items: center;
    padding: 7px 14px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    color: #fff;
    /* Use events brand gradient */
    background: linear-gradient(
      135deg,
      var(--color-app-events-start, #a20000),
      var(--color-app-events-end, #e61b3e)
    );
    transition: opacity 0.15s ease;
    white-space: nowrap;
  }

  .event-link-button:hover {
    opacity: 0.85;
  }

  /* ===========================================
     Skill Icon (EmbedHeader / BasicInfosBar)
     =========================================== */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="event"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/event.svg');
    mask-image: url('@openmates/ui/static/icons/event.svg');
  }
</style>
