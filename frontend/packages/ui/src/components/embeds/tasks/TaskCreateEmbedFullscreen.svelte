<!--
  frontend/packages/ui/src/components/embeds/tasks/TaskCreateEmbedFullscreen.svelte
  Fullscreen parent view for tasks.create embeds.
  Uses SearchResultsTemplate so child task drilldown matches other app skills.
  Child fullscreen attempts live editable task detail, with snapshot fallback.
-->

<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import TaskEmbedPreview from './TaskEmbedPreview.svelte';
  import TaskEmbedFullscreen from './TaskEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';
  import { normalizeTaskLegacyResults, normalizeTaskResult, type TaskEmbedResult } from './taskEmbedData';

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

  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();

  let status = $derived((data.embedData?.status ?? data.decodedContent?.status ?? 'finished') as 'processing' | 'finished' | 'error' | 'cancelled');
  let query = $derived(typeof data.decodedContent?.instruction === 'string' ? data.decodedContent.instruction : typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : 'Created tasks');
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  function legacyResultsFromContent(content: Record<string, unknown> | undefined): TaskEmbedResult[] | undefined {
    if (!content) return undefined;
    const results = extractSearchResultsFromContent(content, ['results', 'preview_results']);
    return results.length > 0 ? normalizeTaskLegacyResults(results) : undefined;
  }

  let legacyResults = $derived(legacyResultsFromContent(data.decodedContent));
</script>

<SearchResultsTemplate
  appId="tasks"
  skillId="create"
  skillIconName="task"
  embedHeaderTitle={query}
  embedHeaderSubtitle="Created tasks"
  {onClose}
  currentEmbedId={embedId}
  {embedIds}
  childEmbedTransformer={normalizeTaskResult}
  {legacyResults}
  legacyResultTransformer={normalizeTaskLegacyResults}
  {initialChildEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  skeletonCount={4}
  minCardWidth="260px"
  {status}
>
  {#snippet resultCard({ result, onSelect })}
    <TaskEmbedPreview id={result.embed_id} taskId={result.task_id} shortId={result.short_id} title={result.title} description={result.description} status={result.status} assignee={result.assignee ?? result.assignee_type} onFullscreen={onSelect} />
  {/snippet}
  {#snippet childFullscreen(nav)}
    <TaskEmbedFullscreen data={{ decodedContent: nav.result }} embedId={nav.result.embed_id} hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext} onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} onClose={nav.onClose} />
  {/snippet}
</SearchResultsTemplate>
