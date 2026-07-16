<!--
  frontend/packages/ui/src/components/embeds/tasks/TaskSearchEmbedFullscreen.svelte
  Fullscreen parent view for tasks.search embeds.
  Reuses the shared search grid and child overlay navigation pattern.
  Child cards use snapshots; child fullscreen upgrades to live data when possible.
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
  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : 'Search tasks');
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
  skillId="search"
  skillIconName="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle="Matching tasks"
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
  {query}
>
  {#snippet resultCard({ result, onSelect })}
    <TaskEmbedPreview id={result.embed_id} taskId={result.task_id} shortId={result.short_id} title={result.title} description={result.description} status={result.status} assignee={result.assignee ?? result.assignee_type} onFullscreen={onSelect} />
  {/snippet}
  {#snippet childFullscreen(nav)}
    <TaskEmbedFullscreen data={{ decodedContent: nav.result }} embedId={nav.result.embed_id} hasPreviousEmbed={nav.hasPrevious} hasNextEmbed={nav.hasNext} onNavigatePrevious={nav.onPrevious} onNavigateNext={nav.onNext} onClose={nav.onClose} />
  {/snippet}
</SearchResultsTemplate>
