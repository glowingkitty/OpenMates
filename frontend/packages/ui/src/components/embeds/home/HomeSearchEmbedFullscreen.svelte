<!--
  frontend/packages/ui/src/components/embeds/home/HomeSearchEmbedFullscreen.svelte

  Fullscreen view for Home Search skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with search query (city) and "via Multi" subtitle
  - Listing cards in a responsive grid
  - Overlay drill-down into HomeListingEmbedFullscreen

  Child embeds are automatically loaded by SearchResultsTemplate/UnifiedEmbedFullscreen.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import HomeListingEmbedPreview from './HomeListingEmbedPreview.svelte';
  import HomeListingEmbedFullscreen from './HomeListingEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';

  /**
   * Normalize a raw status value to one of the valid embed status strings.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  /**
   * Home listing result interface (transformed from child embeds).
   * Contains all fields needed for both preview cards and fullscreen view.
   */
  interface HomeListingResult {
    embed_id: string;
    title?: string;
    price_label?: string;
    size_sqm?: number;
    rooms?: number;
    address?: string;
    image_url?: string;
    url?: string;
    provider?: string;
    listing_type?: string;
    available_from?: string;
    deposit?: number;
    furnished?: boolean;
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
  let localQuery = $state('');
  let localProvider = $state('Multi');
  let localProviders = $state<string[]>([]);
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');

  $effect(() => {
    localQuery = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '';
    localProvider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Multi';
    localProviders = Array.isArray(data.decodedContent?.providers) ? data.decodedContent.providers as string[] : [];
    localStatus = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
    localErrorMessage = typeof data.decodedContent?.error === 'string' ? data.decodedContent.error as string : '';
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let providers = $derived(localProviders);
  let legacyResults = $derived(Array.isArray(data.decodedContent?.results) ? data.decodedContent.results as unknown[] : []);

  // "via {provider}" subtitle — use providers list when available for multi-source display
  let viaProvider = $derived.by(() => {
    const via = $text('embeds.via');
    if (providers.length > 0) {
      if (providers.length <= 2) {
        return `${via} ${providers.join(', ')}`;
      }
      return `${via} ${providers[0]}, ${providers[1]} +${providers.length - 2}`;
    }
    if (provider && provider !== 'Multi') {
      return `${via} ${provider}`;
    }
    return '';
  });

  /**
   * Transform raw embed content to HomeListingResult format.
   */
  function transformToHomeResult(
    embedId: string,
    content: Record<string, unknown>
  ): HomeListingResult {
    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      price_label: content.price_label as string | undefined,
      size_sqm: typeof content.size_sqm === 'number' ? content.size_sqm : undefined,
      rooms: typeof content.rooms === 'number' ? content.rooms : undefined,
      address: content.address as string | undefined,
      image_url: content.image_url as string | undefined,
      url: content.url as string | undefined,
      provider: content.provider as string | undefined,
      listing_type: content.listing_type as string | undefined,
      available_from: content.available_from as string | undefined,
      deposit: typeof content.deposit === 'number' ? content.deposit : undefined,
      furnished: typeof content.furnished === 'boolean' ? content.furnished : undefined
    };
  }

  /**
   * Transform legacy results for backwards compatibility.
   */
  function transformLegacyResults(results: unknown[]): HomeListingResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => ({
      embed_id: `legacy-${i}`,
      title: r.title as string | undefined,
      price_label: r.price_label as string | undefined,
      size_sqm: typeof r.size_sqm === 'number' ? r.size_sqm : undefined,
      rooms: typeof r.rooms === 'number' ? r.rooms : undefined,
      address: r.address as string | undefined,
      image_url: r.image_url as string | undefined,
      url: r.url as string | undefined,
      provider: r.provider as string | undefined,
      listing_type: r.listing_type as string | undefined,
      available_from: r.available_from as string | undefined,
      deposit: typeof r.deposit === 'number' ? r.deposit : undefined,
      furnished: typeof r.furnished === 'boolean' ? r.furnished : undefined
    }));
  }

  /**
   * Handle embed data updates during streaming.
   */
  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
  }) {
    if (!data.decodedContent) return;
    const s = data.status;
    if (s === 'processing' || s === 'finished' || s === 'error' || s === 'cancelled')
      localStatus = s;
    const c = data.decodedContent;
    if (typeof c.query === 'string') localQuery = c.query;
    if (typeof c.provider === 'string') localProvider = c.provider;
    if (Array.isArray(c.providers)) localProviders = c.providers as string[];
    if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
    if (typeof c.error === 'string') localErrorMessage = c.error;
  }
</script>

<SearchResultsTemplate
  appId="home"
  skillId="search"
  minCardWidth="280px"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToHomeResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage}
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
    <HomeListingEmbedPreview
      embed_id={result.embed_id}
      title={result.title}
      price_label={result.price_label}
      size_sqm={result.size_sqm}
      rooms={result.rooms}
      address={result.address}
      image_url={result.image_url}
      provider={result.provider}
      listing_type={result.listing_type}
      available_from={result.available_from}
      {onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <HomeListingEmbedFullscreen
      url={nav.result.url || ''}
      title={nav.result.title}
      price_label={nav.result.price_label}
      size_sqm={nav.result.size_sqm}
      rooms={nav.result.rooms}
      address={nav.result.address}
      image_url={nav.result.image_url}
      provider={nav.result.provider}
      listing_type={nav.result.listing_type}
      available_from={nav.result.available_from}
      deposit={nav.result.deposit}
      furnished={nav.result.furnished}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>

<style>
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="home"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/home.svg');
    mask-image: url('@openmates/ui/static/icons/home.svg');
  }
</style>
