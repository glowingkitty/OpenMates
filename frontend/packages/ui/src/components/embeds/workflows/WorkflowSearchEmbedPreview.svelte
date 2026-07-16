<!--
  frontend/packages/ui/src/components/embeds/workflows/WorkflowSearchEmbedPreview.svelte
  Parent preview for workflows.search app-skill embeds.
  It stays snapshot-only and opens the shared child grid in fullscreen.
  Child workflow fullscreens handle live workspace data when available.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { extractSearchResultsFromContent, getParentPreviewResultState, normalizeEmbedIdList } from '../embedPreviewHydration';
  import type { WorkflowEmbedResult } from './workflowEmbedData';

  interface Props {
    id: string;
    query?: string;
    status: 'processing' | 'finished' | 'error';
    results?: unknown;
    resultCount?: number;
    childEmbedIds?: string[] | string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let { id, query = '', status, results = [], resultCount, childEmbedIds = [], taskId, isMobile = false, onFullscreen }: Props = $props();

  function normalizePreviewResults(value: unknown): WorkflowEmbedResult[] {
    if (Array.isArray(value) && value.length > 0) return value as WorkflowEmbedResult[];
    return extractSearchResultsFromContent({ results_toon: value }, ['results', 'preview_results']) as WorkflowEmbedResult[];
  }

  let previewResults = $derived(normalizePreviewResults(results));
  let childIds = $derived(normalizeEmbedIdList(childEmbedIds));
  let resultState = $derived(getParentPreviewResultState({ status, previewResultCount: previewResults.length, resultCount, childEmbedIds: childIds }));
  let displayCount = $derived(resultCount ?? (previewResults.length > 0 ? previewResults.length : childIds.length));
  let displayQuery = $derived(query || 'Search workflows');
  let summary = $derived.by(() => {
    if (status !== 'finished') return 'Searching workflows...';
    if (resultState === 'known_zero_results') return 'No matching workflows';
    if (resultState === 'missing_preview_metadata') return 'Open to view matching workflows';
    return `Found ${displayCount} workflow${displayCount === 1 ? '' : 's'}`;
  });

  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (!data.decodedContent) return;
    const content = data.decodedContent;
    if (typeof content.query === 'string') query = content.query;
    if (typeof content.result_count === 'number') resultCount = content.result_count;
    results = content.results || content.preview_results || [];
    childEmbedIds = content.embed_ids as string | string[] | undefined ?? childEmbedIds;
  }

  function handleStop() {
    // Workflow search is not cancellable from the preview card.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="workflows"
  skillId="search"
  skillIconName="search"
  {status}
  skillName="Search workflows"
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  showSkillIcon={true}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="workflow-parent-preview" data-testid="workflow-search-embed-preview">
      <div class="query">{displayQuery}</div>
      <div class="meta">{summary}</div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .workflow-parent-preview { display: flex; width: 100%; min-width: 0; flex-direction: column; justify-content: center; gap: var(--spacing-3); }
  .query { overflow: hidden; color: var(--color-font-primary); font-size: var(--font-size-sm); font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
  .meta { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
</style>
