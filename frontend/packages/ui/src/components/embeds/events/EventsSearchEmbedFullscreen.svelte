<!--
  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedFullscreen.svelte

  Fullscreen view for Events Search skill embeds.
  Uses UnifiedEmbedFullscreen as base.

  Shows:
  - Header with search query and "via {provider}" formatting
  - List of event cards: title, date, event_type badge, location, RSVP count, link button
  - Consistent BasicInfosBar at the bottom (matches preview)

  Architecture note:
  Events results are stored inline in the parent embed TOON (not as separate child embeds
  like news/web search). So we use legacyResults and do NOT pass embedIds or childEmbedTransformer.
  This is the simplest fullscreen pattern in the codebase.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /**
   * Single event result from the events/search skill backend.
   * See backend/apps/events/skills/search_skill.py for the full schema.
   */
  interface EventResult {
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
   * Results are passed inline (no child embeds needed).
   */
  interface Props {
    /** Search query */
    query: string;
    /** Events provider (e.g., 'Meetup') */
    provider: string;
    /** Event results (inline, not child embeds) */
    results?: EventResult[];
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
    query,
    provider,
    results: resultsProp = [],
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

  // Header props for gradient banner
  let embedHeaderTitle = $derived(query);
  let embedHeaderSubtitle = $derived(`${$text('embeds.via')} ${provider}`);

  // Detect mobile layout
  let isMobile = $derived(
    typeof window !== 'undefined' && window.innerWidth <= 500
  );

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
    if (event.venue.city) parts.push(event.venue.city);
    if (event.venue.country) parts.push(event.venue.country);
    return parts.join(', ');
  }

  /**
   * Get event results from UnifiedEmbedFullscreen context.
   * Events don't use child embeds — always use legacyResults.
   */
  function getEventResults(ctx: ChildEmbedContext): EventResult[] {
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return ctx.legacyResults as EventResult[];
    }
    return [];
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
  legacyResults={resultsProp}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const events = getEventResults(ctx)}

    {#if events.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results')}</p>
      </div>
    {:else}
      <div class="events-list" class:mobile={isMobile}>
        {#each events as event}
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
     No Results State
     =========================================== */

  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
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
</style>
