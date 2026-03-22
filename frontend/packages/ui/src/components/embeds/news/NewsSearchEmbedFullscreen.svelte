<!--
  frontend/packages/ui/src/components/embeds/news/NewsSearchEmbedFullscreen.svelte
  
  Fullscreen view for News Search skill embeds.
  Uses SearchResultsTemplate for unified grid + overlay + loading pattern.
  
  Shows:
  - Header with search query and "via {provider}"
  - News article embeds in a responsive grid
  - Overlay drill-down into NewsEmbedFullscreen with sibling navigation
  
  See docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import NewsEmbedPreview from './NewsEmbedPreview.svelte';
  import NewsEmbedFullscreen from './NewsEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /**
   * News search result interface (transformed from child embeds)
   */
  interface NewsSearchResult {
    embed_id: string;
    title?: string;
    url: string;
    favicon_url?: string;
    thumbnail?: string;
    description?: string;
    extra_snippets?: string | string[];
    page_age?: string;
  }
  
  interface Props {
    query: string;
    provider: string;
    embedIds?: string | string[];
    results?: NewsSearchResult[];
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
    query,
    provider,
    embedIds,
    results: resultsProp = [],
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
  
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);
  
  /**
   * Extract nested or flat field from decoded content
   */
  function getNestedField(obj: Record<string, unknown>, ...paths: string[]): string | undefined {
    for (const path of paths) {
      if (path.includes('.')) {
        const parts = path.split('.');
        let value: unknown = obj;
        for (const part of parts) {
          if (value && typeof value === 'object' && part in (value as Record<string, unknown>)) {
            value = (value as Record<string, unknown>)[part];
          } else { value = undefined; break; }
        }
        if (typeof value === 'string' && value) return value;
      } else {
        const value = obj[path];
        if (typeof value === 'string' && value) return value;
      }
    }
    return undefined;
  }

  /**
   * Transform raw embed content to NewsSearchResult format
   */
  function transformToNewsResult(embedId: string, content: Record<string, unknown>): NewsSearchResult {
    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      url: content.url as string,
      favicon_url: getNestedField(content, 'meta_url.favicon', 'favicon_url', 'meta_url_favicon'),
      thumbnail: getNestedField(content, 'thumbnail.original', 'thumbnail', 'thumbnail_original', 'image'),
      description: (content.description as string) || (content.snippet as string),
      extra_snippets: content.extra_snippets as string | string[] | undefined,
      page_age: (content.age as string) || (content.page_age as string) || undefined
    };
  }
  
  /**
   * Transform legacy results for backwards compatibility
   */
  function transformLegacyResults(results: unknown[]): NewsSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const metaUrl = r.meta_url as Record<string, string> | undefined;
      const thumbnail = r.thumbnail as Record<string, string> | undefined;
      return {
        embed_id: `legacy-${i}`,
        title: r.title as string | undefined,
        url: r.url as string,
        favicon_url: (r.favicon_url as string) || (r.meta_url_favicon as string) || metaUrl?.favicon,
        thumbnail: (r.thumbnail_original as string) || thumbnail?.original,
        description: (r.description as string) || (r.snippet as string),
        extra_snippets: r.extra_snippets as string | string[] | undefined,
        page_age: (r.age as string) || (r.page_age as string) || undefined
      };
    });
  }
</script>

<SearchResultsTemplate
  appId="news"
  skillId="search"
  minCardWidth="260px"
  skillIconName="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={transformToNewsResult}
  legacyResults={resultsProp}
  legacyResultTransformer={transformLegacyResults}
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
    <NewsEmbedPreview
      id={result.embed_id}
      url={result.url}
      title={result.title}
      description={result.description}
      favicon={result.favicon_url}
      image={result.thumbnail}
      status="finished"
      isMobile={false}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <NewsEmbedFullscreen
      url={nav.result.url}
      title={nav.result.title}
      description={nav.result.description}
      favicon={nav.result.favicon_url}
      thumbnail={nav.result.thumbnail}
      extra_snippets={nav.result.extra_snippets}
      dataDate={nav.result.page_age}
      onClose={nav.onClose}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
    />
  {/snippet}
</SearchResultsTemplate>
