<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DSearchEmbedFullscreen.svelte

  Fullscreen grid for models3d.search parent embeds. It loads child result
  embeds on explicit open and keeps all result cards preview-only.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import Model3DResultEmbedPreview from './Model3DResultEmbedPreview.svelte';
  import Model3DResultEmbedFullscreen from './Model3DResultEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';

  interface Model3DResult {
    embed_id: string;
    title?: string;
    provider?: string;
    creator_name?: string;
    source_page_url?: string;
    preview_image_url?: string;
    thumbnail_url?: string;
    license?: string;
    files_count?: number | null;
    is_free?: boolean | null;
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

  let status = $derived((data.embedData?.status ?? data.decodedContent?.status ?? 'finished') as 'processing' | 'finished' | 'error' | 'cancelled');
  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : $text('app_skills.models3d.search'));
  let provider = $derived(typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : 'Printables');
  let embedHeaderSubtitle = $derived(`${$text('embeds.via')} ${provider}`);
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  function normalizePreviewResults(content: Record<string, unknown> | undefined): Model3DResult[] | undefined {
    if (!content) return undefined;
    const results = extractSearchResultsFromContent(content, ['results', 'preview_results']);
    return results.length > 0 ? results.map((result, index) => ({ embed_id: `legacy-model-${index}`, ...result })) as Model3DResult[] : undefined;
  }

  function transformToModelResult(childEmbedId: string, content: Record<string, unknown>): Model3DResult {
    return {
      embed_id: childEmbedId,
      title: content.title as string | undefined,
      provider: content.provider as string | undefined,
      creator_name: content.creator_name as string | undefined,
      source_page_url: content.source_page_url as string | undefined,
      preview_image_url: content.preview_image_url as string | undefined,
      thumbnail_url: content.thumbnail_url as string | undefined,
      license: content.license as string | undefined,
      files_count: content.files_count as number | null | undefined,
      is_free: content.is_free as boolean | null | undefined,
    };
  }

  function transformLegacyResults(results: unknown[]): Model3DResult[] {
    return (results as Array<Record<string, unknown>>).map((result, index) => transformToModelResult(`legacy-model-${index}`, result));
  }

  let legacyResults = $derived(normalizePreviewResults(data.decodedContent));
</script>

<SearchResultsTemplate
  appId="models3d"
  skillId="search"
  skillIconName="search"
  showSkillIcon={true}
  embedHeaderTitle={query}
  {embedHeaderSubtitle}
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={transformToModelResult}
  {legacyResults}
  legacyResultTransformer={transformLegacyResults}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  skeletonCount={6}
  minCardWidth="260px"
  {status}
>
  {#snippet resultCard({ result, onSelect })}
    <Model3DResultEmbedPreview
      id={result.embed_id}
      title={result.title}
      provider={result.provider}
      creatorName={result.creator_name}
      sourcePageUrl={result.source_page_url}
      previewImageUrl={result.preview_image_url}
      thumbnailUrl={result.thumbnail_url}
      license={result.license}
      filesCount={result.files_count}
      isFree={result.is_free}
      onFullscreen={onSelect}
    />
  {/snippet}

  {#snippet childFullscreen(nav)}
    <Model3DResultEmbedFullscreen
      data={{ decodedContent: nav.result }}
      embedId={nav.result.embed_id}
      hasPreviousEmbed={nav.hasPrevious}
      hasNextEmbed={nav.hasNext}
      onNavigatePrevious={nav.onPrevious}
      onNavigateNext={nav.onNext}
      onClose={nav.onClose}
    />
  {/snippet}
</SearchResultsTemplate>
