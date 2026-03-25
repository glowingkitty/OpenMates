<!--
  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedFullscreen.svelte

  Fullscreen view for Events Search skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with search query and "via {provider}" formatting
  - Grid of EventEmbedPreview cards (one per event)
  - Drill-down: clicking a card opens EventEmbedFullscreen overlay with sibling nav

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import EventEmbedPreview from './EventEmbedPreview.svelte';
  import EventEmbedFullscreen from './EventEmbedFullscreen.svelte';
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
    cover_url?: string | null;
  }

  /** Legacy result shape from .preview.ts files (no embed_id yet) */
  interface LegacyEventResult {
    id?: string;
    provider?: string;
    title?: string;
    description?: string;
    url?: string;
    date_start?: string;
    date_end?: string;
    timezone?: string;
    event_type?: string;
    venue?: EventResult['venue'];
    organizer?: EventResult['organizer'];
    rsvp_count?: number;
    is_paid?: boolean;
    fee?: EventResult['fee'];
    image_url?: string | null;
    cover_url?: string | null;
  }

  interface Props {
    query: string;
    provider: string;
    embedIds?: string | string[];
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Dev-preview legacy results (no child embed store needed) */
    results?: LegacyEventResult[];
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
    initialChildEmbedId?: string;
  }

  let {
    query: queryProp,
    provider: providerProp,
    embedIds,
    status: statusProp,
    results: resultsProp,
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

  // Local reactive state for streaming updates
  let localQuery    = $state('');
  let localProvider = $state('Meetup');
  let localStatus   = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue    = $derived(embedIdsOverride ?? embedIds);

  $effect(() => {
    localQuery    = queryProp    || '';
    localProvider = providerProp || 'Meetup';
    localStatus   = statusProp   || 'finished';
  });

  let query    = $derived(localQuery);
  let provider = $derived(localProvider);
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);
  let legacyResults = $derived(resultsProp ?? []);

  /**
   * Transform legacy results (from .preview.ts files) to EventResult format.
   * Assigns a synthetic embed_id so the results grid works correctly.
   */
  function transformLegacyResults(results: unknown[]): EventResult[] {
    return (results as LegacyEventResult[]).map((r, i) => ({
      embed_id: `legacy-event-${i}`,
      id:          r.id,
      provider:    r.provider,
      title:       r.title,
      description: r.description,
      url:         r.url,
      date_start:  r.date_start,
      date_end:    r.date_end,
      timezone:    r.timezone,
      event_type:  r.event_type,
      venue:       r.venue,
      organizer:   r.organizer,
      rsvp_count:  r.rsvp_count,
      is_paid:     r.is_paid,
      fee:         r.fee,
      image_url:   r.image_url,
      cover_url:   r.cover_url,
    }));
  }

  /**
   * Transform raw embed content to EventResult format.
   * Handles both native nested objects and TOON-flattened keys.
   */
  function transformToEventResult(childEmbedId: string, content: Record<string, unknown>): EventResult {
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

    let fee: EventResult['fee'] | undefined;
    if (content.fee && typeof content.fee === 'object') {
      const f = content.fee as Record<string, unknown>;
      fee = { amount: f.amount as number | undefined, currency: f.currency as string | undefined };
    } else if (content.fee_amount != null) {
      fee = { amount: content.fee_amount as number | undefined, currency: content.fee_currency as string | undefined };
    }

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
      cover_url:   content.cover_url   as string | null | undefined,
    };
  }

  /**
   * Handle embed data updates during streaming.
   */
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

<SearchResultsTemplate
  appId="events"
  skillId="search"
  minCardWidth="260px"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToEventResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet resultCard({ result, onSelect })}
    <EventEmbedPreview
      id={result.embed_id}
      event={result}
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <EventEmbedFullscreen
      event={nav.result}
      embedId={nav.result.embed_id}
      onClose={nav.onClose}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>

<style>
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
