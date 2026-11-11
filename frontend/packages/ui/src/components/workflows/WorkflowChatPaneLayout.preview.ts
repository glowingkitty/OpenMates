// Preview states of the workflow editor shown in a chat (WorkflowChatPane):
// /dev/preview/workflows/WorkflowChatPaneLayout?chrome=0[&variant=authoring|draft|saved|error|fullscreen]
// WorkflowChatPane itself starts AI authoring or loads a workflow on mount, so
// its presentational layout is previewed; no network is needed (version 1 keeps
// version history offline). Default: the unsaved AI draft beside the chat.
import type { WorkflowDetail, WorkflowGraph } from '../../stores/workflowWorkspaceStore';
import type { WorkflowEditorDraft, WorkflowEditorPaneState } from './workflowEditorPane';

const graph: WorkflowGraph = {
  version: 2,
  trigger_node_id: 'schedule',
  nodes: [
    { id: 'schedule', type: 'schedule_trigger', title: 'Monday at 09:00', config: { schedule: { type: 'weekly', weekdays: ['monday'], time: '09:00', timezone: 'Europe/Berlin' } } },
    { id: 'weather', type: 'app_skill_action', title: 'Get weather', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin' } } },
    { id: 'message', type: 'send_chat_message', title: 'Send summary', config: { title: 'Weather', message: 'Weather summary' } }
  ],
  edges: [{ from: 'schedule', to: 'weather' }, { from: 'weather', to: 'message' }]
};

const workflow: WorkflowDetail = {
  id: 'workflow-preview',
  title: 'Weekly school weather brief',
  description: 'Summarize Monday weather before school.',
  category: 'general_knowledge',
  icon: 'cloud-sun',
  status: 'active',
  enabled: false,
  current_version_id: 'version-1',
  version: 1,
  created_at: Date.now() / 1000 - 3600,
  graph
};

const draft: WorkflowEditorDraft = {
  title: workflow.title,
  description: workflow.description ?? '',
  category: 'general_knowledge',
  icon: 'cloud-sun',
  graph
};

const emit = (name: string, detail?: unknown) => window.dispatchEvent(new CustomEvent(name, { detail }));

const editorCallbacks = {
  onError: (_message: string | null) => {},
  onStateChange: (_state: WorkflowEditorPaneState) => {}
};

const draftStage = {
  kind: 'editor' as const,
  ...editorCallbacks,
  source: {
    kind: 'draft' as const,
    draft,
    saving: false,
    preview: null,
    partialNotice: null,
    info: { createdDisabled: false, reminder: null, assumptions: ['Uses Berlin as the location.'], onUndoCreated: null },
    aiAddedNodeIds: [],
    aiEditedNodeIds: [],
    onChange: (next: WorkflowEditorDraft) => emit('workflow-preview-draft-change', { title: next.title }),
    onSave: (next: WorkflowEditorDraft) => emit('workflow-preview-save-draft', { title: next.title }),
    onDraftStateChange: (_hasDraft: boolean) => {}
  }
};

const savedStage = {
  kind: 'editor' as const,
  ...editorCallbacks,
  source: {
    kind: 'saved' as const,
    workflow,
    activeTab: 'template' as const,
    selectedRunId: null,
    runsHref: '#runs',
    editorHref: '#details',
    onTabChange: (_tab: 'template' | 'runs') => {},
    onOpenRun: (_runId: string | null) => {},
    onOpenEditor: () => {},
    onShare: () => {},
    onDeleted: () => {},
    onRequestNavigation: (action: () => void | Promise<void>) => { void action(); },
    authoring: null
  }
};

const props = {
  fullscreen: false,
  stage: draftStage,
  error: null,
  onClose: () => emit('workflow-preview-close')
};

export default props;
export const variants = {
  authoring: {
    ...props,
    stage: {
      kind: 'authoring' as const,
      workflow: { ...workflow, id: 'provisional-0', status: 'provisional', current_version_id: '', graph: { ...graph, nodes: graph.nodes.slice(0, 2), edges: graph.edges.slice(0, 1) } },
      phase: 'validating' as const,
      acceptedNodeCount: 2,
      message: 'Generating the workflow draft…',
      stop: { requested: false, label: 'Stop', onStop: () => emit('workflow-preview-stop') }
    }
  },
  draft: props,
  saved: { ...props, stage: savedStage },
  error: {
    ...props,
    stage: { kind: 'message' as const, title: 'Workflow', message: null },
    error: { message: 'The workflow draft could not be generated.', onRetry: () => emit('workflow-preview-retry') }
  },
  fullscreen: { ...props, fullscreen: true }
};
