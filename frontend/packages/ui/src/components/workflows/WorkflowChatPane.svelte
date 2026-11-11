<!--
  WorkflowChatPane — the regular workflow editor opened from a chat
  recommendation (replaces the former chat-only side panel).

  ActiveChat mounts it for the current `workflowSidePanel` request
  (stores/workflowSidePanelStore.ts): right of the 400px chat column at
  >= 1024px, covering the chat below that. Keyed by the request object, so every
  openWorkflowSidePanel(...) call starts a fresh pane.

  Opening:
  - mode 'create' + instruction: runs the shared AI authoring stream in draft-only
    mode (WorkflowProvisionalView with Stop while it runs), then shows the unsaved
    draft in WorkflowEditorPane ('draft'). Nothing is persisted.
  - mode 'update' + workflowId + instruction: loads the saved workflow, then
    generates an unsaved draft of the change from it.
  - mode 'update' + workflowId + instruction '' (chat history deep link): loads
    and shows the saved workflow in the editor; no AI authoring starts, e.g.
    openWorkflowSidePanel({ chatId, recommendationId, mode: 'update', workflowId, instruction: '' }).
  Draft-only authoring needs the Rust core (VITE_OPENMATES_RUST_CORE=1); without
  it a request with an instruction shows an "unavailable" error instead.

  Save (workflow-save-draft) creates (create) or patches (update) the workflow
  through workflowWorkspaceStore and calls reportWorkflowSidePanelSaved exactly
  once per opened request; the same pane then selects the saved workflow and
  shows it in saved mode, where it can be enabled and tested in place. Closing
  (or switching tabs) with unsaved changes, or while generating, asks
  Stay / Discard / Save; closing discards the draft.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { text } from '../../i18n/translations';
  import { activeTeamId } from '../../stores/teamStore';
  import { notificationStore } from '../../stores/notificationStore';
  import { workflowWorkspaceStore, type WorkflowDetail } from '../../stores/workflowWorkspaceStore';
  import { reportWorkflowSidePanelSaved, type WorkflowSidePanelRequest } from '../../stores/workflowSidePanelStore';
  import { stopWorkflowInstruction, workflowNodeChanges, type WorkflowInputChange } from '../../services/workflowInputService';
  import { graphWithMemorySnapshots } from '../../services/workflowMemorySnapshotService';
  import { workflowIcon } from './workflowBuilder';
  import { runWorkflowAuthoring } from './workflowAuthoringRun';
  import { maintainTemplateProjection, type WorkflowEditorSource } from './workflowEditorPane';
  import { blankWorkflowGraph, draftFromSession, previewFromStreamEvent, saveTarget, shouldStartAuthoring, type WorkflowPanelDraft } from './workflowChatDraft';
  import WorkflowChatPaneLayout, { type WorkflowChatPaneError, type WorkflowChatPaneStage } from './WorkflowChatPaneLayout.svelte';
  import WorkflowUnsavedGuard from './WorkflowUnsavedGuard.svelte';

  /** Draft-only authoring is decided in the Rust core Worker; flag-off builds have no draft path. */
  const DRAFT_AUTHORING = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

  let { request, fullscreen, onClose }: {
    request: WorkflowSidePanelRequest;
    fullscreen: boolean;
    onClose: () => void;
  } = $props();

  type PaneView = 'loading' | 'authoring' | 'draft' | 'saved' | 'error';

  let view = $state<PaneView>('loading');
  /** The saved workflow the pane edits or updates (update mode, or after the first save). */
  let base = $state<WorkflowDetail | null>(null);
  let draft = $state<WorkflowPanelDraft | null>(null);
  let saving = $state(false);
  let paneError = $state<WorkflowChatPaneError | null>(null);
  let authoringPhase = $state<string>('planning');
  let streamPreview = $state<WorkflowDetail | null>(null);
  let acceptedNodeCount = $state(0);
  let stopRequested = $state(false);
  let assumptions = $state<string[]>([]);
  let partialNotice = $state<string | null>(null);
  let aiChange = $state<WorkflowInputChange | null>(null);
  let activeTab = $state<'template' | 'runs'>('template');
  let selectedRunId = $state<string | null>(null);
  /** Action waiting on the unsaved-changes guard (close or a tab switch). */
  let pendingAction = $state<(() => void) | null>(null);
  let layout = $state<WorkflowChatPaneLayout | null>(null);
  let sessionId: string | null = null;
  let controller: AbortController | null = null;
  let savedReported = false;
  let alive = true;
  let runToken = 0;

  const tr = (key: string) => $text(`workflows.side_panel.${key}`);

  /** Saved mode follows the store, so enable/run/save updates show at once. */
  const savedWorkflow = $derived(base ? ($workflowWorkspaceStore.detailsById[base.id] ?? base) : null);

  onMount(() => {
    void openPane();
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

  async function openPane(): Promise<void> {
    paneError = null;
    if (request.mode === 'update') {
      if (!request.workflowId) {
        console.error('[WorkflowChatPane] Update request without a workflowId');
        paneError = { message: tr('load_failed'), onRetry: null };
        view = 'error';
        return;
      }
      view = 'loading';
      try {
        const workflow = await workflowWorkspaceStore.selectWorkflow(request.workflowId);
        if (!alive) return;
        base = workflow;
      } catch (loadError) {
        if (!alive) return;
        console.error('[WorkflowChatPane] Failed to load workflow:', loadError);
        paneError = { message: userMessage(loadError, 'workflows.side_panel.load_failed'), onRetry: () => void openPane() };
        view = 'error';
        return;
      }
    }
    if (shouldStartAuthoring(request)) await generateDraft();
    else view = 'saved';
  }

  /** Authoring ended without a draft: keep the saved workflow (update) or show the error. */
  function failAuthoring(message: string, canRetry: boolean): void {
    paneError = { message, onRetry: canRetry ? () => void generateDraft() : null };
    view = base ? 'saved' : 'error';
  }

  async function generateDraft(): Promise<void> {
    if (!DRAFT_AUTHORING) {
      console.error('[WorkflowChatPane] Draft-only workflow authoring requires VITE_OPENMATES_RUST_CORE=1');
      failAuthoring(tr('draft_unavailable'), false);
      return;
    }
    const token = ++runToken;
    const generation = workflowWorkspaceStore.getGeneration();
    const teamId = get(activeTeamId);
    const isCurrent = () => alive && token === runToken && get(activeTeamId) === teamId && workflowWorkspaceStore.isCurrentGeneration(generation);
    const startingFrom = base;
    view = 'authoring';
    paneError = null;
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
        draftOnly: true,
        // Charges of this authoring run are billed to the chat (and turn) it came from.
        sourceChatId: request.chatId,
        sourceMessageId: request.sourceMessageId
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
        console.error('[WorkflowChatPane] Authoring did not return a draft:', session.status, session.error_code ?? null);
        failAuthoring(result.message || $text('workflows.builder.ai_failed'), true);
        return;
      }
      draft = result.draft;
      assumptions = result.assumptions;
      partialNotice = session.partial_reason ? session.partial_warning || session.message || null : null;
      aiChange = startingFrom ? { workflow_id: startingFrom.id, ...workflowNodeChanges(startingFrom.graph.nodes, result.draft.graph.nodes) } : null;
      view = 'draft';
    } catch (cause) {
      if (!isCurrent()) return;
      if (cause instanceof DOMException && cause.name === 'AbortError' && !stopRequested) return;
      console.error('[WorkflowChatPane] Draft authoring failed:', cause);
      failAuthoring(userMessage(cause, 'workflows.builder.ai_failed'), true);
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
      console.error('[WorkflowChatPane] Could not stop draft authoring:', cause);
      stopRequested = false;
      paneError = { message: userMessage(cause, 'workflows.builder.ai_failed'), onRetry: null };
    }
  }

  function stopAuthoring(): void {
    if (view !== 'authoring' || stopRequested) return;
    stopRequested = true;
    if (sessionId) void acknowledgeStop(sessionId);
  }

  /** Persist the draft, report the save once, then show the saved workflow in place. */
  async function saveDraft(content: WorkflowPanelDraft): Promise<void> {
    if (saving || view !== 'draft') return;
    const target = saveTarget(request, base?.id ?? null);
    saving = true;
    paneError = null;
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
      if (!alive) return;
      base = workflow;
      draft = null;
      aiChange = null;
      assumptions = [];
      partialNotice = null;
      activeTab = 'template';
      selectedRunId = null;
      view = 'saved';
      saving = false;
      await selectSaved(workflow);
    } catch (saveError) {
      console.error('[WorkflowChatPane] Failed to save workflow:', saveError);
      if (alive) paneError = { message: userMessage(saveError, 'workflows.side_panel.save_failed'), onRetry: null };
    } finally {
      if (alive) saving = false;
    }
  }

  /** Select the saved workflow (detail and runs for saved mode) and refresh its shareable template. */
  async function selectSaved(workflow: WorkflowDetail): Promise<void> {
    try {
      await workflowWorkspaceStore.selectWorkflow(workflow.id);
    } catch (selectError) {
      console.error('[WorkflowChatPane] Could not load the saved workflow:', selectError);
      if (alive) paneError = { message: userMessage(selectError, 'workflows.side_panel.load_failed'), onRetry: null };
    }
    const warning = await maintainTemplateProjection(workflow);
    if (warning) {
      console.error('[WorkflowChatPane] Template projection update failed:', warning);
      if (alive) paneError = { message: warning, onRetry: null };
    }
  }

  function hasUnsavedWork(): boolean {
    return view === 'authoring' || view === 'draft' || !!layout?.hasUnsavedChanges();
  }

  function closeNow(): void {
    pendingAction = null;
    runToken += 1;
    controller?.abort();
    if (view === 'authoring' && sessionId) {
      // Release the server-side draft run; nothing of it is persisted.
      void stopWorkflowInstruction(sessionId).catch((cause) => console.error('[WorkflowChatPane] Could not stop draft authoring on close:', cause));
    }
    onClose();
  }

  /** Run `action` now, or after the guard when the editor holds unsaved work. */
  function guarded(action: () => void): void {
    if (hasUnsavedWork()) pendingAction = action;
    else action();
  }

  async function saveAndContinue(): Promise<void> {
    const action = pendingAction;
    if (!action || !layout) return;
    const savedAll = await layout.saveChanges();
    if (savedAll && !hasUnsavedWork()) {
      pendingAction = null;
      action();
    }
  }

  function discardAndContinue(): void {
    const action = pendingAction;
    layout?.discardChanges();
    pendingAction = null;
    action?.();
  }

  function openTab(tab: 'template' | 'runs'): void {
    activeTab = tab;
    if (tab === 'template') selectedRunId = null;
  }

  function shareWorkflow(): void {
    notificationStore.info($text('workflows.builder.sharing_soon'), 4000, true, 'workflow-sharing-soon');
  }

  const reportError = (message: string | null) => { paneError = message ? { message, onRetry: null } : null; };

  const canSaveDraft = $derived(view === 'draft' && !!draft?.title.trim());

  const stage = $derived.by<WorkflowChatPaneStage>(() => {
    if (view === 'authoring') {
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
      const phase = authoringPhase === 'validating' || authoringPhase === 'retrying_node' || authoringPhase === 'saving' ? authoringPhase : 'planning';
      return {
        kind: 'authoring',
        workflow: previewWorkflow,
        phase,
        acceptedNodeCount,
        message: stopRequested ? $text('workflows.builder.ai_stopping') : tr('generating'),
        stop: { requested: stopRequested, label: stopRequested ? $text('workflows.builder.ai_stopping') : $text('workflows.builder.stop'), onStop: stopAuthoring }
      };
    }
    let source: WorkflowEditorSource | null = null;
    if (view === 'draft' && draft) {
      const showInfo = assumptions.length > 0 || !!partialNotice;
      source = {
        kind: 'draft',
        draft,
        saving,
        preview: null,
        partialNotice: null,
        info: showInfo ? { createdDisabled: false, reminder: partialNotice, assumptions, onUndoCreated: null } : null,
        aiAddedNodeIds: aiChange?.added_node_ids ?? [],
        aiEditedNodeIds: aiChange?.edited_node_ids ?? [],
        onChange: (next) => { draft = next; },
        onSave: saveDraft,
        onDraftStateChange: () => {}
      };
    } else if (view === 'saved' && savedWorkflow) {
      const workflowId = savedWorkflow.id;
      source = {
        kind: 'saved',
        workflow: savedWorkflow,
        activeTab,
        selectedRunId,
        runsHref: `/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=runs`,
        editorHref: `/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=details`,
        onTabChange: (tab) => guarded(() => openTab(tab)),
        onOpenRun: (runId) => { activeTab = 'runs'; selectedRunId = runId; },
        onOpenEditor: () => openTab('template'),
        onShare: shareWorkflow,
        onDeleted: closeNow,
        onRequestNavigation: (action) => guarded(() => void action()),
        authoring: null
      };
    }
    if (source) return { kind: 'editor', source, onError: reportError, onStateChange: () => {} };
    return { kind: 'message', title: base?.title ?? $text('workflows.builder.workflow'), message: view === 'loading' ? tr('loading') : null };
  });
</script>

<WorkflowChatPaneLayout bind:this={layout} {fullscreen} {stage} error={paneError} onClose={() => guarded(closeNow)} />

{#if pendingAction}
  <WorkflowUnsavedGuard
    saving={saving || view === 'authoring' || (view === 'draft' && !canSaveDraft)}
    onStay={() => { pendingAction = null; }}
    onDiscard={discardAndContinue}
    onSave={() => void saveAndContinue()}
  />
{/if}
