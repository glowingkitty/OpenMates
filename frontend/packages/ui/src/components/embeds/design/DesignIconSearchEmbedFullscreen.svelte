<!--
  frontend/packages/ui/src/components/embeds/design/DesignIconSearchEmbedFullscreen.svelte

  Fullscreen view for Design app icon search results.
  Uses the shared search result template to load and browse child icon embeds.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import DesignIconResultEmbedPreview from './DesignIconResultEmbedPreview.svelte';
  import DesignIconResultEmbedFullscreen from './DesignIconResultEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';

  interface DesignIconResult {
    embed_id: string;
    icon_id?: string;
    prefix?: string;
    name?: string;
    display_name?: string;
    collection_name?: string;
    license_title?: string;
    svg_path?: string;
  }

  interface Props {
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

  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

  function asString(value: unknown): string | undefined {
    return typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined;
  }

  function normalizeEmbedIds(value: unknown): string | string[] | undefined {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.filter((id): id is string => typeof id === 'string');
    return undefined;
  }

  function transformToIconResult(embedId: string, content: Record<string, unknown>): DesignIconResult {
    return {
      embed_id: asString(content.embed_id) || embedId,
      icon_id: asString(content.icon_id),
      prefix: asString(content.prefix),
      name: asString(content.name),
      display_name: asString(content.display_name),
      collection_name: asString(content.collection_name),
      license_title: asString(content.license_title),
      svg_path: asString(content.svg_path),
    };
  }

  function transformLegacyResults(results: unknown[]): DesignIconResult[] {
    const transformed: DesignIconResult[] = [];
    for (let i = 0; i < results.length; i += 1) {
      const item = results[i] as Record<string, unknown>;
      if (!item || typeof item !== 'object') continue;
      if (Array.isArray(item.results)) {
        for (let j = 0; j < item.results.length; j += 1) {
          const child = item.results[j] as Record<string, unknown>;
          if (child && typeof child === 'object') transformed.push(transformToIconResult(`legacy-${i}-${j}`, child));
        }
      } else {
        transformed.push(transformToIconResult(`legacy-${i}`, item));
      }
    }
    return transformed;
  }

  let embedIds = $derived(normalizeEmbedIds(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids));
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);
  let localQuery = $state('Icons');
  let localProvider = $state('Iconify');
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state('');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let storeResolved = $state(false);

  $effect(() => {
    if (!storeResolved) {
      localQuery = typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : 'Icons';
      localProvider = typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Iconify';
      localResults = extractSearchResultsFromContent(data.decodedContent);
      localStatus = normalizeStatus(data.embedData?.status ?? data.decodedContent?.status);
      localErrorMessage = typeof data.decodedContent?.error === 'string' ? data.decodedContent.error : '';
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(embedIdsOverride ?? embedIds);
  let legacyResults = $derived(localResults);
  let headerSubtitle = $derived(`via ${provider}`);

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') storeResolved = true;

    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) embedIdsOverride = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results;
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }
</script>

<SearchResultsTemplate
  appId="design"
  skillId="search_icons"
  maxGridWidth="1000px"
  embedHeaderTitle={query}
  embedHeaderSubtitle={headerSubtitle}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToIconResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  status={localStatus}
  errorMessage={localErrorMessage || 'Icon search failed.'}
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
    <DesignIconResultEmbedPreview
      id={result.embed_id}
      icon_id={result.icon_id}
      prefix={result.prefix}
      name={result.name}
      display_name={result.display_name}
      collection_name={result.collection_name}
      license_title={result.license_title}
      svg_path={result.svg_path}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen({ result, onClose: onChildClose, hasPrevious, hasNext, onPrevious, onNext })}
    <DesignIconResultEmbedFullscreen
      data={{ decodedContent: { ...result }, attrs: {}, embedData: {} }}
      embedId={result.embed_id}
      onClose={onChildClose}
      hasPreviousEmbed={hasPrevious}
      hasNextEmbed={hasNext}
      onNavigatePrevious={onPrevious}
      onNavigateNext={onNext}
    />
  {/snippet}
</SearchResultsTemplate>
