<!--
  WorkflowSidePanel — workflow editor that opens next to the chat.

  ActiveChat mounts it for the current `workflowSidePanel` request
  (stores/workflowSidePanelStore.ts): side by side with a 400px chat column at
  >= 1024px, fullscreen over the chat below that. Keyed by the request object,
  so every openWorkflowSidePanel(...) call starts a fresh panel.

  Opening:
  - mode 'create' + instruction: runs the shared AI authoring stream in draft-only
    mode and shows the draft being generated. Nothing is persisted.
  - mode 'update' + workflowId + instruction: loads the saved workflow, then
    generates an unsaved draft of the change from it.
  - mode 'update' + workflowId + instruction '' (chat history deep link): loads
    and shows the saved workflow in the editor; no AI authoring starts, e.g.
    openWorkflowSidePanel({ chatId, recommendationId, mode: 'update', workflowId, instruction: '' }).
  Draft-only authoring needs the Rust core (VITE_OPENMATES_RUST_CORE=1); without
  it a request with an instruction shows an "unavailable" error instead.

  Saving creates (create) or patches (update) the workflow through
  workflowWorkspaceStore and calls reportWorkflowSidePanelSaved exactly once per
  opened request; the panel stays open on the saved workflow. Closing with
  unsaved changes (or while generating) asks Stay / Discard / Save; closing
  discards the draft.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { text } from '../../i18n/translations';
  import { activeTeamId } from '../../stores/teamStore';
  import { workflowWorkspaceStore, type WorkflowDetail, type WorkflowGraph } from '../../stores/workflowWorkspaceStore';
  import { reportWorkflowSidePanelSaved, type WorkflowSidePanelRequest } from '../../stores/workflowSidePanelStore';
  import { stopWorkflowInstruction, workflowNodeChanges, type WorkflowInputChange } from '../../services/workflowInputService';
  import { graphWithMemorySnapshots } from '../../services/workflowMemorySnapshotService';
  import { upsertWorkflowTemplateProjection } from '../../services/workflowTemplateService';
  import { workflowIcon } from './workflowBuilder';
  import { runWorkflowAuthoring } from './workflowAuthoringRun';
  import { blankWorkflowGraph, draftFromSession, draftFromWorkflow, previewFromStreamEvent, saveTarget, shouldStartAuthoring, type WorkflowPanelDraft } from './workflowSidePanelDraft';
  import WorkflowSidePanelView, { type WorkflowSidePanelEditor, type WorkflowSidePanelError } from './WorkflowSidePanelView.svelte';
  import WorkflowUnsavedGuard from './WorkflowUnsavedGuard.svelte';

  /** Draft-only authoring is decided in the Rust core Worker; flag-off builds have no draft path. */
  const DRAFT_AUTHORING = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

  let { request, fullscreen, onClose }: {
    request: WorkflowSidePanelRequest;
    fullscreen: boolean;
    onClose: () => void;
  } = $props();

  type PanelPhase = 'loading' | 'authoring' | 'editing' | 'error';

  let phase = $state<PanelPhase>('loading');
  let base = $state<WorkflowDetail | null>(null);
  let draft = $state<WorkflowPanelDraft | null>(null);
  let dirty = $state(false);
  let saving = $state(false);
  let nodeDraftOpen = $state(false);
  let guardOpen = $state(false);
  let panelError = $state<WorkflowSidePanelError | null>(null);
  let authoringPhase = $state<string>('planning');
  let streamPreview = $state<WorkflowDetail | null>(null);
  let acceptedNodeCount = $state(0);
  let stopRequested = $state(false);
  let assumptions = $state<string[]>([]);
  let partialNotice = $state<string | null>(null);
  let aiChange = $state<WorkflowInputChange | null>(null);
  let view = $state<WorkflowSidePanelView | null>(null);
  let sessionId: string | null = null;
  let controller: AbortController | null = null;
  let savedReported = false;
  let alive = true;
  let runToken = 0;

  const tr = (key: string) => $text(`workflows.side_panel.${key}`);

  onMount(() => {
    void openPanel();
    return () => {
      alive = false;
      controller?.abort();
    };
  });

  /** Keep transport details (HTTP codes, error codes) out of product copy. */
  function userMessage(cause: unknown, fallbackKey: string): string {
    const message = cause instanceof Error ? cause.message : '';
    return !message || /HTTP \d{3}|^WORKFLOW_[A-Z_]+$/.test(message) ? $text(fallbackKey) : message;
  }

  async function openPanel(): Promise<void> {
    panelError = null;
    if (request.mode === 'update') {
      if (!request.workflowId) {
        console.error('[WorkflowSidePanel] Update request without a workflowId');
        panelError = { message: tr('load_failed'), onRetry: null };
        phase = 'error';
        return;
      }
      phase = 'loading';
      try {
        const workflow = await workflowWorkspaceStore.selectWorkflow(request.workflowId);
        if (!alive) return;
        base = workflow;
        draft = draftFromWorkflow(workflow);
        dirty = false;
      } catch (loadError) {
        if (!alive) return;
        console.error('[WorkflowSidePanel] Failed to load workflow:', loadError);
        panelError = { message: userMessage(loadError, 'workflows.side_panel.load_failed'), onRetry: () => void openPanel() };
        phase = 'error';
        return;
      }
    }
    if (shouldStartAuthoring(request)) await generateDraft();
    else phase = 'editing';
  }

  function failAuthoring(message: string): void {
    panelError = { message, onRetry: () => void generateDraft() };
    phase = draft ? 'editing' : 'error';
  }

  async function generateDraft(): Promise<void> {
    if (!DRAFT_AUTHORING) {
      console.error('[WorkflowSidePanel] Draft-only workflow authoring requires VITE_OPENMATES_RUST_CORE=1');
      panelError = { message: tr('draft_unavailable'), onRetry: null };
      phase = draft ? 'editing' : 'error';
      return;
    }
    const token = ++runToken;
    const generation = workflowWorkspaceStore.getGeneration();
    const teamId = get(activeTeamId);
    const isCurrent = () => alive && token === runToken && get(activeTeamId) === teamId && workflowWorkspaceStore.isCurrentGeneration(generation);
    const startingFrom = base;
    phase = 'authoring';
    panelError = null;
    authoringPhase = 'planning';
    streamPreview = null;
    acceptedNodeCount = 0;
    stopRequested = false;
    partialNotice = null;
    aiChange = null;
    sessionId = null;
    const authoringController = new AbortController();
    controller = authoringController;
    try {
      const session = await runWorkflowAuthoring({
        instruction: request.instruction.trim(),
        workflowId: startingFrom?.id,
        idempotencyKey: crypto.randomUUID(),
        signal: authoringController.signal,
        draftOnly: true
      }, {
        isCurrent,
        isStopRequested: () => stopRequested,
        onStarted: (startedId) => {
          sessionId = startedId;
          if (stopRequested) void acknowledgeStop(startedId);
        },
        onProgress: (event) => { authoringPhase = event.phase; },
        onPreview: (event) => {
          streamPreview = previewFromStreamEvent(event, startingFrom);
          acceptedNodeCount = event.accepted_node_count ?? event.graph.nodes.length;
        },
        onStreamSettled: () => { controller = null; },
        onPending: (pending) => {
          sessionId = pending.session_id;
          streamPreview = pending.preview_workflow ?? streamPreview;
        }
      });
      if (!session) return;
      const result = draftFromSession(session, startingFrom);
      if (result.kind === 'error') {
        console.error('[WorkflowSidePanel] Authoring did not return a draft:', session.status, session.error_code ?? null);
        failAuthoring(result.message || $text('workflows.builder.ai_failed'));
        return;
      }
      draft = result.draft;
      assumptions = result.assumptions;
      partialNotice = session.partial_reason ? session.partial_warning || session.message || null : null;
      aiChange = startingFrom ? { workflow_id: startingFrom.id, ...workflowNodeChanges(startingFrom.graph.nodes, result.draft.graph.nodes) } : null;
      dirty = true;
      phase = 'editing';
    } catch (cause) {
      if (!isCurrent()) return;
      if (cause instanceof DOMException && cause.name === 'AbortError' && !stopRequested) return;
      console.error('[WorkflowSidePanel] Draft authoring failed:', cause);
      failAuthoring(userMessage(cause, 'workflows.builder.ai_failed'));
    } finally {
      if (isCurrent()) {
        controller = null;
        streamPreview = null;
        stopRequested = false;
      }
    }
  }

  async function acknowledgeStop(id: string): Promise<void> {
    try {
      await stopWorkflowInstruction(id);
      controller?.abort();
    } catch (cause) {
      console.error('[WorkflowSidePanel] Could not stop draft authoring:', cause);
      stopRequested = false;
      panelError = { message: userMessage(cause, 'workflows.builder.ai_failed'), onRetry: null };
    }
  }

  function stopAuthoring(): void {
    if (phase !== 'authoring' || stopRequested) return;
    stopRequested = true;
    if (sessionId) void acknowledgeStop(sessionId);
  }

  function updateGraph(graph: WorkflowGraph): void {
    if (!draft) return;
    draft = { ...draft, graph };
    dirty = true;
  }

  async function keepNodeInDraft(graph: WorkflowGraph): Promise<void> {
    updateGraph(graph);
  }

  function updateTitle(title: string): void {
    if (!draft) return;
    draft = { ...draft, title };
    dirty = true;
  }

  async function saveWorkflow(): Promise<boolean> {
    if (!draft || saving || phase !== 'editing') return false;
    if (view?.hasPendingDraft() && !(await view.savePendingDraft())) return false;
    const content = draft;
    const target = saveTarget(request, base?.id ?? null);
    saving = true;
    panelError = null;
    try {
      const graph = await graphWithMemorySnapshots(content.graph);
      const title = content.title.trim() || base?.title || $text('workflows.builder.processing');
      const icon = workflowIcon(title, content.icon, graph);
      const workflow = target.workflowId
        ? await workflowWorkspaceStore.patchWorkflow(target.workflowId, { title, description: content.description.trim(), graph, icon })
        : await workflowWorkspaceStore.createWorkflow({ title, description: content.description.trim(), category: content.category, icon, graph, enabled: false, runContentRetention: 'last_5' });
      if (!savedReported) {
        savedReported = true;
        reportWorkflowSidePanelSaved({ chatId: request.chatId, recommendationId: request.recommendationId, workflowId: workflow.id, title: workflow.title, action: target.action });
      }
      if (!alive) return true;
      base = workflow;
      draft = draftFromWorkflow(workflow);
      dirty = false;
      aiChange = null;
      assumptions = [];
      partialNotice = null;
      try {
        await upsertWorkflowTemplateProjection(workflow);
      } catch (projectionError) {
        console.error('[WorkflowSidePanel] Template projection update failed:', projectionError);
        const detail = projectionError instanceof Error ? projectionError.message : 'Could not update the encrypted workflow template projection.';
        if (alive) panelError = { message: `Workflow saved, but its shareable template was not updated: ${detail}`, onRetry: null };
      }
      return true;
    } catch (saveError) {
      console.error('[WorkflowSidePanel] Failed to save workflow:', saveError);
      if (alive) panelError = { message: userMessage(saveError, 'workflows.side_panel.save_failed'), onRetry: null };
      return false;
    } finally {
      if (alive) saving = false;
    }
  }

  function hasUnsavedWork(): boolean {
    return phase === 'authoring' || dirty || nodeDraftOpen || !!view?.hasPendingDraft();
  }

  function closeNow(): void {
    guardOpen = false;
    runToken += 1;
    controller?.abort();
    if (phase === 'authoring' && sessionId) {
      // Release the server-side draft run; nothing of it is persisted.
      void stopWorkflowInstruction(sessionId).catch((cause) => console.error('[WorkflowSidePanel] Could not stop draft authoring on close:', cause));
    }
    onClose();
  }

  function requestClose(): void {
    if (hasUnsavedWork()) guardOpen = true;
    else closeNow();
  }

  const canSave = $derived(phase === 'editing' && !!draft && (dirty || nodeDraftOpen) && !!draft.title.trim());

  const statusMessage = $derived(
    phase === 'loading' ? tr('loading')
      : phase === 'authoring' ? (stopRequested ? $text('workflows.builder.ai_stopping') : tr('generating'))
        : null
  );

  const editor = $derived.by<WorkflowSidePanelEditor | null>(() => {
    const handlers = { onChange: updateGraph, onSave: keepNodeInDraft, onDraftStateChange: (hasDraft: boolean) => { nodeDraftOpen = hasDraft; } };
    if (phase === 'authoring') {
      const previewWorkflow: WorkflowDetail = streamPreview ?? {
        id: base?.id ?? 'provisional-0',
        title: base?.title ?? $text('workflows.builder.processing'),
        description: base?.description ?? null,
        category: base?.category ?? 'general_knowledge',
        icon: base?.icon,
        status: 'provisional',
        enabled: base?.enabled ?? false,
        current_version_id: '',
        graph: base?.graph ?? blankWorkflowGraph()
      };
      const previewPhase = authoringPhase === 'validating' || authoringPhase === 'retrying_node' || authoringPhase === 'saving' ? authoringPhase : 'planning';
      return {
        workflowId: base?.id ?? null, graph: previewWorkflow.graph,
        preview: { workflow: previewWorkflow, phase: previewPhase, acceptedNodeCount, baseGraph: base?.graph ?? null },
        info: null, review: null, aiAddedNodeIds: [], aiEditedNodeIds: [], ...handlers
      };
    }
    if (!draft) return null;
    const showInfo = assumptions.length > 0 || !!partialNotice;
    return {
      workflowId: base?.id ?? null,
      graph: draft.graph,
      preview: null,
      info: showInfo ? { createdDisabled: false, reminder: partialNotice, assumptions, onUndoCreated: null } : null,
      review: null,
      aiAddedNodeIds: aiChange?.added_node_ids ?? [],
      aiEditedNodeIds: aiChange?.edited_node_ids ?? [],
      ...handlers
    };
  });
</script>

<WorkflowSidePanelView
  bind:this={view}
  {fullscreen}
  saved={!!base && !dirty}
  title={phase === 'authoring' ? (streamPreview?.title ?? draft?.title ?? '') : (draft?.title ?? '')}
  status={statusMessage}
  stop={phase === 'authoring' ? { requested: stopRequested, label: stopRequested ? $text('workflows.builder.ai_stopping') : $text('workflows.builder.stop'), onStop: stopAuthoring } : null}
  error={panelError}
  {editor}
  {saving}
  {canSave}
  onTitleInput={updateTitle}
  onSave={() => void saveWorkflow()}
  onClose={requestClose}
/>

{#if guardOpen}
  <WorkflowUnsavedGuard
    saving={saving || !canSave}
    onStay={() => { guardOpen = false; }}
    onDiscard={() => { view?.discardPendingDraft(); closeNow(); }}
    onSave={() => void saveWorkflow().then((saved) => { if (saved) closeNow(); })}
  />
{/if}
