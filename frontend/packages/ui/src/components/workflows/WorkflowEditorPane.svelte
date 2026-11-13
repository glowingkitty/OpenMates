<!--
  WorkflowEditorPane — the regular editor for one workflow, the same UI as the
  /workflows route: detail header, binding review, version history, the node
  editor with "Test now", and the runs tab.

  Source modes (see workflowEditorPane.ts):
  - { kind: 'saved', workflow, ... }: edits are persisted through
    workflowWorkspaceStore; enable toggle, runs, test run, export and delete.
    The /workflows route passes its AI-authoring extras through `authoring`.
  - { kind: 'draft', draft, onChange, onSave, onDraftStateChange }: an unsaved
    workflow; identity and node saves change only the caller's draft, and the
    header Save (workflow-save-draft) calls onSave.

  The caller owns navigation (URL state, close) and error presentation (onError).
  Exposed: hasUnsavedChanges(), hasPendingDraft(), saveChanges(), discardChanges(),
  resetTo(workflow, { resetIdentity }), openNodeEditor(nodeId).
-->
<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { text } from '../../i18n/translations';
  import { workflowWorkspaceStore, type WorkflowBindingRequirement, type WorkflowDetail, type WorkflowGraph } from '../../stores/workflowWorkspaceStore';
  import { graphWithMemorySnapshots } from '../../services/workflowMemorySnapshotService';
  import { downloadWorkflowFile } from '../../services/workflowFileService';
  import { workflowGraphReady, workflowIcon } from './workflowBuilder';
  import WorkflowDetailPage from './WorkflowDetailPage.svelte';
  import WorkflowBindingReview from './WorkflowBindingReview.svelte';
  import WorkflowRunHistory from './WorkflowRunHistory.svelte';
  import WorkflowVersionHistory from './WorkflowVersionHistory.svelte';
  import WorkflowEditorWorkspace from './WorkflowEditorWorkspace.svelte';
  import type { WorkflowAuthoringInfo } from './WorkflowAuthoringNotices.svelte';
  import {
    bindingRequirementsComplete,
    cloneGraph,
    maintainTemplateProjection,
    type WorkflowEditorDraft,
    type WorkflowEditorPaneState,
    type WorkflowEditorSource
  } from './workflowEditorPane';

  let { source, onClose, onError, onStateChange }: {
    source: WorkflowEditorSource;
    onClose: () => void;
    /** Report a user-facing error; null clears the previous one at the start of a request. */
    onError: (message: string | null) => void;
    onStateChange: (state: WorkflowEditorPaneState) => void;
  } = $props();

  const saved = $derived(source.kind === 'saved' ? source : null);
  const draftSource = $derived(source.kind === 'draft' ? source : null);
  const workflow = $derived(saved?.workflow ?? null);
  const authoring = $derived(saved?.authoring ?? null);
  const runs = $derived($workflowWorkspaceStore.runs);

  let editorTitle = $state('');
  let editorDescription = $state('');
  let editorGraph = $state<WorkflowGraph | null>(null);
  let editorDirty = $state(false);
  let saving = $state(false);
  let workspaceRef = $state<WorkflowEditorWorkspace | null>(null);
  let editorHasPendingDraft = $state(false);
  let identityResetSignal = $state(0);
  let lastStartedRunId = $state<string | null>(null);
  let authoringReminder = $state<string | null>(null);
  let runContentRetention: 'last_5' | 'none' = 'last_5';
  let hydratedEditorWorkflow: WorkflowDetail | null = null;
  let reminderWorkflowId: string | null = null;

  const displaySaving = $derived(saving || !!authoring?.busy);
  const editorActivationReady = $derived(
    editorGraph && workflow && bindingRequirementsComplete(workflow) ? workflowGraphReady(editorGraph, { requireSchedule: true }) : false
  );
  const savedRunReady = $derived(workflow && bindingRequirementsComplete(workflow) ? workflowGraphReady(workflow.graph) : false);
  const hasTimeTrigger = $derived(editorGraph?.nodes.some((node) => node.type === 'schedule_trigger') ?? false);
  const savedInfo = $derived<WorkflowAuthoringInfo | null>(
    authoring
      ? { ...authoring.info, reminder: authoringReminder }
      : authoringReminder ? { createdDisabled: false, reminder: authoringReminder, assumptions: [], onUndoCreated: null } : null
  );

  $effect(() => {
    const current = workflow;
    if (!current || hydratedEditorWorkflow === current || editorDirty || saving || authoring?.hydrationPaused || editorHasPendingDraft || workspaceRef?.hasPendingDraft()) return;
    resetEditor(current);
  });

  $effect(() => {
    const workflowId = workflow?.id ?? null;
    untrack(() => {
      if (workflowId === reminderWorkflowId) return;
      reminderWorkflowId = workflowId;
      authoringReminder = null;
    });
  });

  $effect(() => {
    const state: WorkflowEditorPaneState = { graphReady: source.kind === 'draft' || !!editorGraph, dirty: editorDirty, saving };
    untrack(() => onStateChange(state));
  });

  onDestroy(() => onStateChange({ graphReady: false, dirty: false, saving: false }));

  /** True while identity or graph edits (saved mode) or an open node editor hold unsaved changes. */
  export function hasUnsavedChanges(): boolean {
    return (source.kind === 'saved' && editorDirty) || hasPendingDraft();
  }

  /** True while a node editor holds unsaved step changes. */
  export function hasPendingDraft(): boolean {
    return workspaceRef?.hasPendingDraft() ?? false;
  }

  /** Save the open node editor and the pending edits; false when something stayed unsaved. */
  export async function saveChanges(): Promise<boolean> {
    if (source.kind === 'draft') return saveDraft();
    if (workspaceRef?.hasPendingDraft() && !(await workspaceRef.savePendingDraft())) return false;
    if (editorDirty) await saveSelectedWorkflow();
    if (editorDirty) return false;
    identityResetSignal += 1;
    return true;
  }

  /** Drop the open node editor and (saved mode) the unsaved identity and graph edits. */
  export function discardChanges(): void {
    workspaceRef?.discardPendingDraft();
    if (workflow) resetEditor(workflow);
    identityResetSignal += 1;
  }

  /** Re-hydrate the editor from a workflow the caller just loaded or changed. */
  export function resetTo(next: WorkflowDetail, options: { resetIdentity: boolean } = { resetIdentity: false }): void {
    resetEditor(next);
    if (options.resetIdentity) identityResetSignal += 1;
  }

  export function openNodeEditor(nodeId: string): void {
    workspaceRef?.openNodeEditor(nodeId);
  }

  function resetEditor(next: WorkflowDetail): void {
    editorTitle = next.title;
    editorDescription = next.description ?? '';
    editorGraph = cloneGraph(next.graph);
    editorDirty = false;
    runContentRetention = next.run_content_retention ?? 'last_5';
    hydratedEditorWorkflow = next;
  }

  function messageOf(cause: unknown, fallback: string): string {
    return cause instanceof Error ? cause.message : fallback;
  }

  async function refreshProjection(next: WorkflowDetail): Promise<void> {
    const warning = await maintainTemplateProjection(next);
    if (warning) onError(warning);
  }

  async function confirmBinding(requirement: WorkflowBindingRequirement): Promise<void> {
    if (!workflow || editorDirty || displaySaving || workspaceRef?.hasPendingDraft()) return;
    const node = workflow.graph.nodes.find(item => item.id === requirement.node_id);
    const input: WorkflowBindingRequirement & { chat_id?: string; new_chat?: boolean } = { ...requirement };
    if (requirement.type === 'chat_destination') {
      const chatId = String(node?.config?.chat_id ?? '').trim();
      if (chatId) input.chat_id = chatId;
      else if (String(node?.config?.title ?? '').trim()) input.new_chat = true;
      else { onError($text('workflows.builder.file_binding_chat_missing')); return; }
    }
    saving = true;
    onError(null);
    try {
      resetEditor(await workflowWorkspaceStore.completeBindingRequirement(workflow.id, input));
    } catch (bindingError) {
      onError(messageOf(bindingError, $text('workflows.builder.file_binding_failed')));
    } finally {
      saving = false;
    }
  }

  async function setEnabled(enabled: boolean): Promise<void> {
    if (!workflow) return;
    saving = true;
    onError(null);
    try {
      const updated = await workflowWorkspaceStore.setWorkflowEnabled(workflow.id, enabled);
      resetEditor(updated);
      authoring?.onSaved(updated);
    } catch (saveError) {
      onError(messageOf(saveError, 'Failed to update workflow.'));
    } finally {
      saving = false;
    }
  }

  async function runWorkflow(): Promise<void> {
    if (!saved || displaySaving || !savedRunReady) return;
    const target = saved;
    saving = true;
    onError(null);
    try {
      const run = await workflowWorkspaceStore.runWorkflow(target.workflow.id);
      lastStartedRunId = run.id;
      target.onOpenRun(run.id);
    } catch (runError) {
      onError(messageOf(runError, 'Failed to run workflow.'));
    } finally {
      saving = false;
    }
  }

  async function deleteWorkflow(): Promise<void> {
    if (!saved || !window.confirm(`Delete “${saved.workflow.title}”? This cannot be undone.`)) return;
    const target = saved;
    saving = true;
    onError(null);
    try {
      await workflowWorkspaceStore.deleteWorkflow(target.workflow.id);
      target.onDeleted();
    } catch (deleteError) {
      onError(messageOf(deleteError, 'Failed to delete workflow.'));
    } finally {
      saving = false;
    }
  }

  async function saveSelectedWorkflow(): Promise<void> {
    if (!workflow || !editorGraph) return;
    saving = true;
    onError(null);
    try {
      const updated = await workflowWorkspaceStore.patchWorkflow(workflow.id, {
        title: editorTitle.trim() || workflow.title,
        description: editorDescription.trim(),
        graph: editorGraph,
        run_content_retention: runContentRetention
      });
      resetEditor(updated);
      authoring?.onSaved(updated);
      saving = false;
      await refreshProjection(updated);
    } catch (saveError) {
      onError(messageOf(saveError, 'Failed to save workflow.'));
    } finally {
      saving = false;
    }
  }

  async function saveNodeGraph(graph: WorkflowGraph): Promise<void> {
    if (!workflow) throw new Error('Workflow unavailable');
    const current = workflow;
    saving = true;
    onError(null);
    authoringReminder = null;
    try {
      const updated = await workflowWorkspaceStore.patchWorkflow(current.id, {
        graph: await graphWithMemorySnapshots(graph),
        title: editorTitle.trim() || current.title,
        description: editorDescription,
        icon: workflowIcon(editorTitle, current.icon, graph)
      });
      authoringReminder = updated.authoring_warnings?.map((warning) => warning.message).join(' ') || null;
      resetEditor(updated);
      identityResetSignal += 1;
      authoring?.onSaved(updated);
      await refreshProjection(updated);
    } finally {
      // Failures propagate unreported: the node editor shows them inline, and
      // reporting here too would raise a second, generic notification.
      saving = false;
    }
  }

  async function updateWorkflowIdentity(title: string, description: string): Promise<void> {
    if (!workflow) return;
    const current = workflow;
    saving = true;
    try {
      const updated = await workflowWorkspaceStore.patchWorkflow(current.id, {
        title: title.trim(),
        description,
        graph: editorGraph ?? current.graph,
        run_content_retention: runContentRetention
      });
      resetEditor(updated);
      authoring?.onSaved(updated);
      await refreshProjection(updated);
    } finally {
      saving = false;
    }
  }

  async function handleVersionRestored(restored: WorkflowDetail): Promise<void> {
    resetEditor(restored);
    identityResetSignal += 1;
    authoring?.onSaved(restored);
    await refreshProjection(restored);
  }

  function exportWorkflow(): void {
    if (!workflow) return;
    try {
      downloadWorkflowFile(workflow);
    } catch (exportError) {
      onError(messageOf(exportError, $text('workflows.builder.file_export_failed')));
    }
  }

  function updateEditorGraph(graph: WorkflowGraph): void {
    editorGraph = graph;
    editorDirty = true;
  }

  function updateDraft(patch: Partial<WorkflowEditorDraft>): void {
    if (source.kind !== 'draft') return;
    source.onChange({ ...source.draft, ...patch });
  }

  async function keepNodeInDraft(graph: WorkflowGraph): Promise<void> {
    updateDraft({ graph });
  }

  async function saveDraft(): Promise<boolean> {
    if (source.kind !== 'draft' || source.saving) return false;
    if (workspaceRef?.hasPendingDraft() && !(await workspaceRef.savePendingDraft())) return false;
    // Read the source again: saving the open node editor updated the caller's draft.
    if (source.kind !== 'draft') return false;
    await source.onSave(source.draft);
    return true;
  }
</script>

{#if draftSource}
  {@const draft = draftSource.draft}
  <WorkflowDetailPage
    state="draft"
    title={draft.title}
    description={draft.description}
    category={draft.category}
    icon={workflowIcon(draft.title, draft.icon, draft.graph)}
    saving={draftSource.saving}
    canSave={!!draft.title.trim() && !draftSource.preview}
    onDraftIdentity={(title, description) => updateDraft({ title, description })}
    onSaveDraft={() => void saveDraft()}
    onOpenHome={onClose}
  />
  <div id="tabpanel-template" data-testid="workflow-template-panel" role="tabpanel" aria-label="Workflow template">
    <WorkflowEditorWorkspace
      bind:this={workspaceRef}
      workflowId={null}
      graph={draft.graph}
      saving={draftSource.saving}
      preview={draftSource.preview}
      partialNotice={draftSource.partialNotice}
      info={draftSource.info}
      review={null}
      testNow={null}
      aiAddedNodeIds={draftSource.aiAddedNodeIds}
      aiEditedNodeIds={draftSource.aiEditedNodeIds}
      onChange={(graph) => updateDraft({ graph })}
      onSave={keepNodeInDraft}
      onDraftStateChange={draftSource.onDraftStateChange}
    />
  </div>
{:else if saved}
  {@const current = saved.workflow}
  {@const runsView = saved.activeTab === 'runs'}
  {#key `${current.id}:${identityResetSignal}`}
    <WorkflowDetailPage
      state="saved"
      title={editorTitle || current.title}
      description={editorDescription}
      category={current.category ?? 'general_knowledge'}
      icon={workflowIcon(current.title, current.icon, editorGraph ?? undefined)}
      createdAt={current.created_at}
      nextRunAt={current.next_run_at}
      enabled={current.enabled}
      canEnable={editorActivationReady && !editorDirty}
      canRun={savedRunReady}
      {lastStartedRunId}
      activeTab={saved.activeTab}
      saving={displaySaving}
      onTabChange={saved.onTabChange}
      onToggleEnabled={() => setEnabled(!workflow?.enabled)}
      onUpdateIdentity={updateWorkflowIdentity}
      onDraftIdentity={(title, description) => {
        editorTitle = title;
        editorDescription = description;
        editorDirty = true;
      }}
      onRunWorkflow={runWorkflow}
      onDeleteWorkflow={deleteWorkflow}
      onOpenHome={onClose}
      onOpenShare={saved.onShare}
      onExport={exportWorkflow}
      onOpenRuns={() => saved?.onTabChange('runs')}
      runsHref={saved.runsHref}
    />
  {/key}
  {#if !runsView && current.binding_requirements?.length}
    <WorkflowBindingReview requirements={current.binding_requirements} completed={current.completed_binding_requirements ?? []} graph={editorGraph ?? current.graph} saving={displaySaving} hasUnsavedChanges={editorDirty || !!workspaceRef?.hasPendingDraft()} onEdit={(nodeId) => workspaceRef?.openNodeEditor(nodeId)} onConfirm={confirmBinding} />
  {/if}

  {#if runsView}
    <WorkflowRunHistory
      workflow={current}
      {runs}
      selectedRunId={saved.selectedRunId}
      onSelectRun={(runId) => saved?.onOpenRun(runId)}
      editorHref={saved.editorHref}
      onOpenEditor={saved.onOpenEditor}
    />
  {:else}
    <div id="tabpanel-template" data-testid="workflow-template-panel" role="tabpanel" aria-label="Workflow template">
      <WorkflowVersionHistory
        workflow={current}
        disabled={displaySaving}
        onRequestNavigation={saved.onRequestNavigation}
        onRestored={handleVersionRestored}
      >
        {#if editorGraph}
          <WorkflowEditorWorkspace
            bind:this={workspaceRef}
            workflowId={current.id}
            graph={editorGraph}
            saving={displaySaving}
            preview={authoring?.preview ?? null}
            partialNotice={authoring?.partialNotice ?? null}
            info={savedInfo}
            review={authoring?.review ?? null}
            testNow={hasTimeTrigger && !authoring?.testNowHidden ? { disabled: displaySaving || editorDirty || !savedRunReady, label: $text('workflows.builder.test_now'), onRun: () => void runWorkflow() } : null}
            aiAddedNodeIds={authoring?.aiAddedNodeIds ?? []}
            aiEditedNodeIds={authoring?.aiEditedNodeIds ?? []}
            onChange={updateEditorGraph}
            onSave={saveNodeGraph}
            onDraftStateChange={(hasDraft) => { editorHasPendingDraft = hasDraft; }}
          />
        {/if}
      </WorkflowVersionHistory>
    </div>
  {/if}
{/if}

<style>
  #tabpanel-template {
    box-sizing: border-box;
    width: min(60rem, calc(100% - 4rem));
    margin: 0 auto;
    padding-top: 2.5rem;
    border-radius: var(--radius-16);
    background: var(--color-grey-0);
  }
  #tabpanel-template :global(.graph-panel) {
    width: 100%;
    margin-block: 0;
  }
  @media (max-width: 730px) {
    #tabpanel-template {
      width: calc(100% - 1rem);
    }
  }
</style>
