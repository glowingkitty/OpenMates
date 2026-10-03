<!--
  frontend/packages/ui/src/components/embeds/workflows/WorkflowEmbedFullscreen.svelte
  Child fullscreen for workflow result embeds.
  It attempts live workflow store loading for editable title/description and
  uses the decoded snapshot in preview/example contexts.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../../i18n/translations';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import WorkspaceDetailHeader from '../../workspace/WorkspaceDetailHeader.svelte';
  import WorkflowGraphRenderer from '../../workflows/WorkflowGraphRenderer.svelte';
  import { workflowDetailAdapter } from '../../workspace/detailMetadataAdapters';
  import { workflowApiRequest, workflowWorkspaceStore, type WorkflowDetail, type WorkflowGraph } from '../../../stores/workflowWorkspaceStore';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { normalizeWorkflowResult, workflowStatusLabel } from './workflowEmbedData';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let { data, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext }: Props = $props();

  let snapshot = $derived(normalizeWorkflowResult(embedId || 'workflow', data.decodedContent ?? {}));
  let workflow = $state<WorkflowDetail | null>(null);
  let liveLoadFailed = $state(false);
  let savingCopy = $state(false);
  let savedCopy = $state<WorkflowDetail | null>(null);
  let saveError = $state('');
  let copyKey = crypto.randomUUID();
  const tr = (key: string) => $text(`workflows.builder.${key}`);
  let workflowId = $derived(snapshot.workflow_id || snapshot.embed_id);
  let title = $derived(workflow?.title || snapshot.title || 'Untitled workflow');
  let description = $derived(workflow?.description || snapshot.description || '');
  let metadata = $derived(workflow?.trigger_summary || snapshot.trigger_summary || workflowStatusLabel(workflow?.status || snapshot.status, workflow?.enabled ?? snapshot.enabled));
  let graph = $derived(workflow?.graph ?? snapshot.graph);
  let chatOwned = $derived((workflow?.lifecycle ?? snapshot.lifecycle) === 'chat_embed');
  let openHref = $derived(`/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=details`);
  let copyHref = $derived(`/#workflow-id=${encodeURIComponent(savedCopy?.id ?? '')}&workflow-tab=details`);
  let runsHref = $derived(`/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=runs`);

  onMount(() => {
    if (!workflowId || workflowId.startsWith('legacy-')) return;
    void workflowApiRequest<{ workflow: WorkflowDetail }>(`/v1/workflows/${encodeURIComponent(workflowId)}`).then((data) => {
      workflow = data.workflow;
      workflowWorkspaceStore.upsertWorkflow(data.workflow);
    }).catch((error) => {
      liveLoadFailed = true;
      console.debug('[WorkflowEmbedFullscreen] Live workflow load unavailable, using snapshot:', error);
    });
  });

  async function saveTitle(value: string): Promise<void> {
    if (!workflow) throw new Error('Workflow is not available for editing.');
    workflow = await workflowDetailAdapter.saveTitle(workflow, value);
  }

  async function saveDescription(value: string): Promise<void> {
    if (!workflow) throw new Error('Workflow is not available for editing.');
    workflow = await workflowDetailAdapter.saveDescription(workflow, value);
  }
  async function saveReusable(): Promise<void> {
    if (!workflow || !chatOwned || savingCopy) return;
    savingCopy = true;
    saveError = '';
    try {
      savedCopy = await workflowWorkspaceStore.saveAsReusableWorkflow(workflow.id, copyKey);
    } catch (error) {
      saveError = error instanceof Error ? error.message : tr('chat_copy_failed');
    } finally {
      savingCopy = false;
    }
  }
</script>

<UnifiedEmbedFullscreen
  testId="workflow-embed-fullscreen"
  appId="workflows"
  skillId="workflow"
  skillIconName="workflow"
  embedHeaderTitle={title}
  embedHeaderSubtitle={metadata}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet content()}
    <div class="workflow-detail-shell" data-testid="workflow-embed-fullscreen-content">
      <WorkspaceDetailHeader
        {title}
        {description}
        {metadata}
        category="productivity"
        icon="workflow"
        writable={!!workflow && !chatOwned}
        embedded={true}
        alignment="start"
        titleTestId="workflow-embed-title"
        descriptionTestId="workflow-embed-description"
        onSaveTitle={saveTitle}
        onSaveDescription={saveDescription}
      />
      <nav class="workflow-embed-actions" aria-label={tr('chat_actions')} data-testid="workflow-chat-embed-actions">
        <a href={openHref} data-testid="workflow-chat-open">{tr('chat_open_workflow')}</a>
        {#if chatOwned && !savedCopy}<button type="button" data-testid="workflow-chat-save-reusable" disabled={!workflow || savingCopy} onclick={() => void saveReusable()}>{tr(savingCopy ? 'saving' : 'chat_save_reusable')}</button>{/if}
        {#if savedCopy}<a href={copyHref} data-testid="workflow-chat-saved-copy">{tr('chat_open_saved_copy')}</a>{/if}
        {#if workflow || snapshot.workflow_id}<a href={runsHref} data-testid="workflow-chat-runs">{tr('run_history')}</a>{/if}
      </nav>
      {#if saveError}<p class="save-error" role="alert">{saveError}</p>{/if}
      {#if graph}<WorkflowGraphRenderer {graph} readOnly testId="workflow-chat-graph" onChange={(_graph: WorkflowGraph) => {}}/>{/if}
      {#if liveLoadFailed}
        <p class="snapshot-note">{tr('chat_snapshot_note')}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .workflow-detail-shell {
    width: min(860px, calc(100% - 32px));
    margin: 0 auto;
    padding: var(--spacing-12) 0 120px;
  }

  .snapshot-note {
    margin: var(--spacing-8) 0 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }
  .workflow-embed-actions { display:flex; flex-wrap:wrap; gap:var(--spacing-4); margin:var(--spacing-8) 0; }
  .workflow-embed-actions a,.workflow-embed-actions button { display:inline-flex; align-items:center; min-height:2.5rem; padding:.5rem 1rem; border:1px solid var(--color-grey-30); border-radius:var(--radius-full); background:var(--color-grey-10); color:var(--color-font-primary); font:inherit; font-size:var(--font-size-small); cursor:pointer; text-decoration:none; }
  .workflow-embed-actions button:disabled { opacity:.5; cursor:default; }
  .workflow-embed-actions :is(a,button):focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  .save-error { color:var(--color-error); }
  .workflow-detail-shell :global([data-testid='workflow-chat-graph']) { width:100%; max-width:none; }
</style>
