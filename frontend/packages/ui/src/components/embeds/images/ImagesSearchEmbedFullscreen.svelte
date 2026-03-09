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
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';

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

  interface Props {
    query: string;
    provider: string;
    embedIds?: string | string[];
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
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

  // Local reactive state for streaming
  let localQuery    = $state('');
  let localProvider = $state('Brave');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue    = $derived(embedIdsOverride ?? embedIds);

  $effect(() => {
    localQuery    = queryProp    || '';
    localProvider = providerProp || 'Brave';
  });

  let query    = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedHeaderSubtitle = $derived(`${$text('embeds.via')} ${provider}`);

  /** Proxy an external image URL */
  function proxyUrl(url: string | undefined): string | undefined {
    if (!url) return undefined;
    return proxyImage(url);
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
