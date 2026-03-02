<!--
  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedFullscreen.svelte

  Fullscreen view for Events Search skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.

  Shows:
  - Header with search query and "via {provider}" formatting
  - Grid of EventEmbedPreview cards (one per event)
  - Drill-down: clicking a card opens EventEmbedFullscreen overlay (ChildEmbedOverlay pattern)

  Architecture note:
  Events results are stored as SEPARATE CHILD EMBEDS (like news/web search) — NOT inline in
  the parent embed TOON. The parent embed carries `embed_ids` pointing to the individual event
  child embeds. We use embedIds + childEmbedTransformer so UnifiedEmbedFullscreen handles loading.

  Drill-down pattern mirrors TravelSearchEmbedFullscreen:
  - The events grid is ALWAYS rendered as the base layer
  - When a card is clicked, EventEmbedFullscreen renders as an overlay (ChildEmbedOverlay)
  - Closing the overlay reveals the events grid without re-animation or re-fetch
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import EventEmbedPreview from './EventEmbedPreview.svelte';
  import EventEmbedFullscreen from './EventEmbedFullscreen.svelte';
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
    /**
     * Child embed ID to auto-open on mount (set when arriving from an inline badge click).
     * When provided, the fullscreen will immediately open the EventEmbedFullscreen overlay
     * for that specific event once results have loaded.
     */
    initialChildEmbedId?: string;
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
    onShowChat,
    initialChildEmbedId
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

  // ── Drill-down state ─────────────────────────────────────────────────────────
  /**
   * Index of the currently selected event in the results array.
   * -1 means no event is open in the overlay.
   * Needed (rather than storing the EventResult object) so ← → sibling navigation works.
   */
  let selectedEventIndex = $state<number>(-1);

  /**
   * All loaded event results — populated via onChildrenLoaded callback.
   * Stored separately from ctx.children to enable sibling navigation in the overlay.
   */
  let allEvents = $state<EventResult[]>([]);

  /** Guard: prevent the auto-open $effect from firing more than once per mount. */
  let _autoOpenFired = $state(false);

  /** Open an event's detail fullscreen overlay. */
  function handleEventClick(index: number) {
    selectedEventIndex = index;
  }

  /**
   * Close the event overlay.
   *
   * When opened via inline badge (initialChildEmbedId set): close the entire
   * fullscreen immediately — no parent results grid needed.
   * When opened normally (card click): return to the results grid.
   */
  function handleEventClose() {
    if (initialChildEmbedId) {
      // Opened via inline badge — skip the grid and close the entire fullscreen
      console.debug('[EventsSearchEmbedFullscreen] Closing event overlay (inline badge origin) — closing entire fullscreen');
      onClose();
    } else {
      console.debug('[EventsSearchEmbedFullscreen] Closing event overlay, returning to events grid');
      selectedEventIndex = -1;
    }
  }

  /**
   * Handle closing the entire events search fullscreen.
   * If a child overlay is open (and was NOT from an inline badge), close it first.
   */
  function handleMainClose() {
    if (selectedEventIndex >= 0 && !initialChildEmbedId) {
      selectedEventIndex = -1;
    } else {
      onClose();
    }
  }

  /** Navigate to the previous event in the overlay. */
  function handleEventPrevious() {
    if (selectedEventIndex > 0) {
      selectedEventIndex = selectedEventIndex - 1;
    }
  }

  /** Navigate to the next event in the overlay. */
  function handleEventNext() {
    if (selectedEventIndex < allEvents.length - 1) {
      selectedEventIndex = selectedEventIndex + 1;
    }
  }

  // The currently selected event object (undefined when overlay is closed)
  let selectedEvent = $derived(
    selectedEventIndex >= 0 ? allEvents[selectedEventIndex] : undefined
  );

  /**
   * Auto-open the event overlay for a specific child embed when the fullscreen
   * is opened via an inline badge click (initialChildEmbedId is set).
   * Fires at most once per mount (_autoOpenFired guard) to prevent re-opening
   * after the user closes the child overlay.
   */
  $effect(() => {
    if (!initialChildEmbedId) return;
    if (_autoOpenFired) return; // fire at most once per mount
    if (allEvents.length === 0) return; // results not yet loaded

    const idx = allEvents.findIndex(e => e.embed_id === initialChildEmbedId);
    if (idx >= 0) {
      console.debug(
        '[EventsSearchEmbedFullscreen] Auto-opening event overlay for initialChildEmbedId:',
        initialChildEmbedId,
        'at index',
        idx,
      );
      _autoOpenFired = true;
      handleEventClick(idx);
    } else {
      console.warn(
        '[EventsSearchEmbedFullscreen] initialChildEmbedId not found in loaded results:',
        initialChildEmbedId,
        'available embed_ids:',
        allEvents.map(e => e.embed_id),
      );
    }
  });

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
      embed_id:    childEmbedId,
      id:          content.id          as string | undefined,
      provider:    content.provider    as string | undefined,
      title:       content.title       as string | undefined,
      description: content.description as string | undefined,
      url:         content.url         as string | undefined,
      date_start:  content.date_start  as string | undefined,
      date_end:    content.date_end    as string | undefined,
      timezone:    content.timezone    as string | undefined,
      event_type:  content.event_type  as string | undefined,
      venue,
      organizer,
      rsvp_count:  content.rsvp_count  as number | undefined,
      is_paid:     content.is_paid     as boolean | undefined,
      fee,
      image_url:   content.image_url   as string | null | undefined,
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
</script>

<UnifiedEmbedFullscreen
  appId="events"
  skillId="search"
  onClose={handleMainClose}
  currentEmbedId={embedId}
  skillIconName="search"
  embedHeaderTitle={embedHeaderTitle}
  embedHeaderSubtitle={embedHeaderSubtitle}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToEventResult}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  onChildrenLoaded={(children) => { allEvents = children as EventResult[]; }}
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
      <!--
        Events grid: each event rendered as an EventEmbedPreview card.
        Clicking a card opens EventEmbedFullscreen via ChildEmbedOverlay drill-down.
        The grid stays mounted beneath the overlay — no re-animation when returning.
      -->
      <div class="events-grid">
        {#each events as event, index (event.embed_id)}
          <EventEmbedPreview
            id={event.embed_id}
            {event}
            isMobile={false}
            onFullscreen={() => handleEventClick(index)}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!--
  Drill-down overlay: renders the single-event fullscreen on top of the results grid.
  The grid stays alive beneath — no re-fetch or re-animation on close.
  Only rendered when an event card has been clicked (selectedEvent is defined).
-->
{#if selectedEvent}
  <ChildEmbedOverlay>
    <EventEmbedFullscreen
      event={selectedEvent}
      onClose={handleEventClose}
      hasPreviousEmbed={selectedEventIndex > 0}
      hasNextEmbed={selectedEventIndex < allEvents.length - 1}
      onNavigatePrevious={handleEventPrevious}
      onNavigateNext={handleEventNext}
    />
  </ChildEmbedOverlay>
{/if}

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
     Events Grid
     Responsive: single column on narrow, two-column on wide
     =========================================== */

  .events-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 16px;
    padding: 24px 16px;
    padding-bottom: 120px; /* Space for bottom bar + gradient */
    max-width: 900px;
    margin: 0 auto;
  }

  /* Two-column grid on wider fullscreen panels */
  @container fullscreen (min-width: 640px) {
    .events-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }

  /* ===========================================
     Skill Icon (EmbedHeader / BasicInfosBar)
     =========================================== */

  /* Events search skill uses "search" icon (magnifying glass) in the fullscreen header.
     Matches the convention used by WebSearch and TravelSearch. */
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
