<script lang="ts">
  import { onMount } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '../../../i18n/translations';
  import WorkflowRunHistory from '../../workflows/WorkflowRunHistory.svelte';
  import { workflowWorkspaceStore, type WorkflowDetail, type WorkflowRunDetail } from '../../../stores/workflowWorkspaceStore';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  let { data, onClose }: { data: EmbedFullscreenRawData; onClose: () => void } = $props();
  const workflowId = $derived(String(data.decodedContent?.workflow_id ?? ''));
  const runId = $derived(String(data.decodedContent?.run_id ?? ''));
  let workflow = $state<WorkflowDetail | null>(null);
  let run = $state<WorkflowRunDetail | null>(null);
  let loading = $state(true);

  onMount(() => {
    let disposed = false;
    if (!workflowId || !runId) { loading = false; return; }
    void Promise.all([
      workflowWorkspaceStore.selectWorkflow(workflowId),
      workflowWorkspaceStore.getWorkflowRun(workflowId, runId),
    ]).then(([loadedWorkflow, loadedRun]) => {
      if (!disposed) { workflow = loadedWorkflow; run = loadedRun; }
    }).catch(() => {
      // Run data is owner scoped and may have expired or been deleted.
    }).finally(() => { if (!disposed) loading = false; });
    return () => { disposed = true; };
  });
</script>

<UnifiedEmbedFullscreen
  testId="workflow-run-embed-fullscreen"
  appId="workflows"
  skillId="run"
  skillIconName="workflow"
  embedHeaderTitle={workflow?.title ?? $text('workflows.run_embed.title')}
  embedHeaderSubtitle={$text('workflows.run_embed.detail')}
  currentEmbedId={runId}
  {onClose}
>
  {#snippet content()}
    <div class="run-detail">
      {#if workflow && run}
        <WorkflowRunHistory
          {workflow}
          runs={[run]}
          selectedRunId={runId}
          onSelectRun={() => {}}
          editorHref={`/workflows#workflow-id=${encodeURIComponent(workflowId)}`}
          onOpenEditor={() => { window.location.href = `/workflows#workflow-id=${encodeURIComponent(workflowId)}`; }}
        />
      {:else if loading}
        <p data-testid="workflow-run-embed-loading">{$text('workflows.run_embed.loading')}</p>
      {:else}
        <p data-testid="workflow-run-embed-unavailable">{$text('workflows.run_embed.unavailable')}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .run-detail { width:min(100%, 860px); margin:auto; padding:var(--spacing-6); box-sizing:border-box; }
  p { color:var(--color-font-secondary); }
</style>
