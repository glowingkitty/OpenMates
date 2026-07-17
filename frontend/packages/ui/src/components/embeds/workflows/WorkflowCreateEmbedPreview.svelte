<!--
  frontend/packages/ui/src/components/embeds/workflows/WorkflowCreateEmbedPreview.svelte
  Parent preview for workflows.create-or-modify app-skill embeds.
  It shows the instruction and count/status, deferring child hydration to fullscreen.
  This matches the existing search-style parent-child embed pattern.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { extractSearchResultsFromContent, getParentPreviewResultState, normalizeEmbedIdList } from '../embedPreviewHydration';
  import type { WorkflowEmbedResult } from './workflowEmbedData';

  interface Props {
    id: string;
    query?: string;
    instruction?: string;
    title?: string;
    status: 'processing' | 'finished' | 'error';
    results?: unknown;
    resultCount?: number;
    childEmbedIds?: string[] | string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let { id, query = '', instruction = '', title = '', status, results = [], resultCount, childEmbedIds = [], taskId, isMobile = false, onFullscreen }: Props = $props();

  function normalizePreviewResults(value: unknown): WorkflowEmbedResult[] {
    if (Array.isArray(value) && value.length > 0) return value as WorkflowEmbedResult[];
    return extractSearchResultsFromContent({ results_toon: value }, ['results', 'preview_results']) as WorkflowEmbedResult[];
  }

  let previewResults = $derived(normalizePreviewResults(results));
  let childIds = $derived(normalizeEmbedIdList(childEmbedIds));
  let resultState = $derived(getParentPreviewResultState({ status, previewResultCount: previewResults.length, resultCount, childEmbedIds: childIds }));
  let displayCount = $derived(resultCount ?? (previewResults.length > 0 ? previewResults.length : childIds.length));
  let displayInstruction = $derived(instruction || query || title || 'Create workflow');
  let summary = $derived.by(() => {
    if (status !== 'finished') return 'Building workflow...';
    if (resultState === 'known_zero_results' && title) return 'Workflow created';
    if (resultState === 'known_zero_results') return 'No workflow created';
    if (resultState === 'missing_preview_metadata') return 'Open to view workflow';
    return `${displayCount} workflow${displayCount === 1 ? '' : 's'} created or updated`;
  });

  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (!data.decodedContent) return;
    const content = data.decodedContent;
    if (typeof content.query === 'string') query = content.query;
    if (typeof content.instruction === 'string') instruction = content.instruction;
    if (typeof content.title === 'string') title = content.title;
    if (typeof content.result_count === 'number') resultCount = content.result_count;
    results = content.results || content.preview_results || [];
    childEmbedIds = content.embed_ids as string | string[] | undefined ?? childEmbedIds;
  }

  function handleStop() {
    // Workflow creation is not cancellable from the preview card.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="workflows"
  skillId="create-or-modify"
  skillIconName="workflow"
  {status}
  skillName="Create workflow"
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  showSkillIcon={true}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="workflow-parent-preview" data-testid="workflow-create-embed-preview">
      <div class="query">{displayInstruction}</div>
      <div class="meta">{summary}</div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .workflow-parent-preview { display: flex; width: 100%; min-width: 0; flex-direction: column; justify-content: center; gap: var(--spacing-3); }
  .query { overflow: hidden; color: var(--color-font-primary); font-size: var(--font-size-sm); font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
  .meta { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
</style>
