<!--
  frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedFullscreen.svelte

  Fullscreen view for Images Search skill embeds (images/search).
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.

  Shows:
  - Header with search query and "via {provider}"
  - Grid of ImageResultEmbedPreview cards (now always using UnifiedEmbedPreview)
  - Drill-down: clicking a card opens ImageResultEmbedFullscreen overlay

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import ImageResultEmbedPreview from './ImageResultEmbedPreview.svelte';
  import ImageResultEmbedFullscreen from './ImageResultEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';

  /**
   * Normalize a raw status value to one of the valid embed status strings.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  /**
   * Single image result (child embed content schema).
   */
  interface ImageResult {
    embed_id: string;
    title?: string;
    source_page_url?: string;
    image_url?: string;
    thumbnail_url?: string;
    source?: string;
    favicon_url?: string;
  }

  /**
   * Legacy result shape for dev-preview / backwards compatibility.
   * Fields mirror the child embed content schema but without embed_id.
   */
  interface LegacyImageResult {
    title?: string;
    source_page_url?: string;
    image_url?: string;
    thumbnail_url?: string;
    source?: string;
    favicon_url?: string;
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
  let statusProp = $derived(normalizeStatus(data.embedData?.status ?? data.decodedContent?.status));
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let resultsProp = $derived(
    Array.isArray(data.decodedContent?.results)
      ? data.decodedContent.results as LegacyImageResult[]
      : undefined
  );

  // Local reactive state for streaming
  let localQuery    = $state('');
  let localProvider = $state('Brave');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue    = $derived(embedIdsOverride ?? embedIds);

  $effect(() => {
    localQuery    = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : '';
    localProvider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Brave';
  });

  let query    = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedHeaderSubtitle = $derived(`${$text('embeds.via')} ${provider}`);

  /** Proxy an external image URL — cap at 1024px for grid cards */
  function proxyUrl(url: string | undefined): string | undefined {
    if (!url) return undefined;
    return proxyImage(url, MAX_WIDTH_HEADER_IMAGE);
  }

  /**
   * Transform raw decoded child embed content into a typed ImageResult.
   */
  function transformToImageResult(childEmbedId: string, content: Record<string, unknown>): ImageResult {
    return {
      embed_id:        childEmbedId,
      title:           content.title           as string | undefined,
      source_page_url: content.source_page_url as string | undefined,
      image_url:       content.image_url       as string | undefined,
      thumbnail_url:   content.thumbnail_url   as string | undefined,
      source:          content.source          as string | undefined,
      favicon_url:     content.favicon_url     as string | undefined,
    };
  }

  /**
   * Handle embed data updates (e.g. embed_ids arriving mid-stream).
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.decodedContent) {
      const c = data.decodedContent;
      if (c.query)     localQuery    = c.query    as string;
      if (c.provider)  localProvider = c.provider as string;
      if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
    }
  }

  /**
   * Transform legacy/direct results array into typed ImageResult objects.
   * Assigns a synthetic embed_id from index so the grid works correctly.
   */
  function transformLegacyResults(results: unknown[]): ImageResult[] {
    return (results as LegacyImageResult[]).map((r, i) => ({
      embed_id: `legacy-image-${i}`,
      title: r.title,
      source_page_url: r.source_page_url,
      image_url: r.image_url,
      thumbnail_url: r.thumbnail_url,
      source: r.source,
      favicon_url: r.favicon_url,
    }));
  }

  /** Legacy results from direct prop (used in dev preview when no embedIds available) */
  let legacyResults = $derived(resultsProp && resultsProp.length > 0 ? resultsProp : undefined);
</script>

<SearchResultsTemplate
  appId="images"
  skillId="search"
  skillIconName="search"
  showSkillIcon={true}
  embedHeaderTitle={query}
  {embedHeaderSubtitle}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToImageResult}
  legacyResults={legacyResults}
  legacyResultTransformer={transformLegacyResults}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  minCardWidth="180px"
  skeletonCount={8}
  status={statusProp}
>
  {#snippet resultCard({ result, onSelect })}
    <ImageResultEmbedPreview
      id={result.embed_id}
      title={result.title}
      sourceDomain={result.source}
      thumbnailUrl={proxyUrl(result.thumbnail_url || result.image_url)}
      faviconUrl={result.favicon_url}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <ImageResultEmbedFullscreen
      title={nav.result.title}
      sourceDomain={nav.result.source}
      sourcePageUrl={nav.result.source_page_url}
      imageUrl={proxyUrl(nav.result.image_url || nav.result.thumbnail_url)}
      thumbnailUrl={proxyUrl(nav.result.thumbnail_url || nav.result.image_url)}
      faviconUrl={nav.result.favicon_url}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
      onClose={nav.onClose}
    />
  {/snippet}
</SearchResultsTemplate>
