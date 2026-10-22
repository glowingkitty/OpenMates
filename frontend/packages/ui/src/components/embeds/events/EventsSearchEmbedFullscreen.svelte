<!--
  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedFullscreen.svelte

  Fullscreen view for Events Search skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with search query and selected provider label when available
  - Grid of EventEmbedPreview cards (one per event)
  - Drill-down: clicking a card opens EventEmbedFullscreen overlay with sibling nav

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import { normalizeEventResult, type EventResult } from './eventResult';
  import EventEmbedPreview from './EventEmbedPreview.svelte';
  import EventEmbedFullscreen from './EventEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';

  /**
   * Normalize a raw status value to one of the valid embed status strings.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  /** Map backend provider slugs to human-readable display names. */
  function getProviderLabel(slug: string): string {
    switch (slug?.toLowerCase()) {
      case 'meetup':              return 'Meetup';
      case 'luma':                return 'Luma';
      case 'eventbrite':          return 'Eventbrite';
      case 'google_events':       return 'Google';
      case 'resident_advisor':    return 'Resident Advisor';
      case 'siegessaeule':        return 'Siegessäule';
      case 'classictic':          return 'Classictic';
      case 'berlin_philharmonic': return 'Berlin Philharmonic';
      case 'bachtrack':           return 'Bachtrack';
      default:                    return slug || '';
    }
  }

  interface Props {
    /** Raw embed data — component extracts its own fields internally */
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // Extract fields from data prop
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  // Local reactive state for streaming updates
  let localQuery    = $state('');
  let localProvider = $state('');
  let localProviders = $state<string[]>([]);
  let localStartDate = $state('');
  let localEndDate = $state('');
  let localStatus   = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue    = $derived(embedIdsOverride ?? embedIds);

  $effect(() => {
    localQuery    = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '';
    localProvider = typeof data.decodedContent?.provider === 'string'
      ? data.decodedContent.provider
      : typeof data.embedData?.provider === 'string' ? data.embedData.provider : '';
    localProviders = Array.isArray(data.decodedContent?.providers)
      ? data.decodedContent.providers as string[]
      : Array.isArray(data.embedData?.providers) ? data.embedData.providers as string[] : [];
    localStartDate = typeof data.decodedContent?.start_date === 'string'
      ? data.decodedContent.start_date
      : typeof data.embedData?.start_date === 'string' ? data.embedData.start_date : '';
    localEndDate = typeof data.decodedContent?.end_date === 'string'
      ? data.decodedContent.end_date
      : typeof data.embedData?.end_date === 'string' ? data.embedData.end_date : '';
    localStatus   = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
  });

  let query    = $derived(localQuery);
  let provider = $derived(localProvider);
  let providers = $derived(localProviders);
  let startDate = $derived(localStartDate);
  let endDate = $derived(localEndDate);

  function formatSearchDate(value: string): string {
    const dateParts = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
    const date = dateParts
      ? new Date(Date.UTC(Number(dateParts[1]), Number(dateParts[2]) - 1, Number(dateParts[3])))
      : new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      timeZone: 'UTC',
    }).format(date);
  }

  let searchRange = $derived.by(() => {
    if (startDate && endDate) return `${formatSearchDate(startDate)} - ${formatSearchDate(endDate)}`;
    if (startDate) return formatSearchDate(startDate);
    if (endDate) return formatSearchDate(endDate);
    return '';
  });
  let viaProvider = $derived.by(() => {
    const via = $text('embeds.via');
    if (providers.length > 0) {
      const labels = providers.map(getProviderLabel);
      if (labels.length <= 2) return `${via} ${labels.join(', ')}`;
      return `${via} ${labels[0]}, ${labels[1]} +${labels.length - 2}`;
    }
    if (provider && provider !== 'auto' && provider !== 'none') {
      return `${via} ${getProviderLabel(provider)}`;
    }
    return '';
  });
  let headerSubtitle = $derived.by(() => [viaProvider, searchRange].filter(Boolean).join(' · '));
  let legacyResults = $derived(extractSearchResultsFromContent(data.decodedContent));

  /**
   * Transform legacy results (from .preview.ts files) to EventResult format.
   * Assigns a synthetic embed_id so the results grid works correctly.
   */
  function transformLegacyResults(results: unknown[]): EventResult[] {
    return (results as Record<string, unknown>[]).map((result, index) => normalizeEventResult(result, `legacy-event-${index}`));
  }

  const transformToEventResult = (childEmbedId: string, content: Record<string, unknown>) => normalizeEventResult(content, childEmbedId);

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
    if (Array.isArray(c.providers)) localProviders = c.providers as string[];
    if (typeof c.start_date === 'string') localStartDate = c.start_date;
    if (typeof c.end_date === 'string') localEndDate = c.end_date;
    if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
  }
</script>

<SearchResultsTemplate
  appId="events"
  skillId="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle={headerSubtitle}
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
      data={{ decodedContent: nav.result }}
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
