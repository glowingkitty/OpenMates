// Preview states for the chat workflow side panel shell:
// /dev/preview/workflows/WorkflowSidePanelView?chrome=0[&variant=...]
import type { WorkflowDetail, WorkflowGraph } from '../../stores/workflowWorkspaceStore';

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

const previewWorkflow = {
  id: 'provisional-0',
  title: 'Weekly school weather brief',
  description: 'Summarize Monday weather before school.',
  status: 'provisional',
  enabled: false,
  current_version_id: '',
  graph
} as WorkflowDetail;

const editor = {
  workflowId: null,
  graph,
  preview: null,
  info: { createdDisabled: false, reminder: null, assumptions: ['Uses Berlin as the location.'], onUndoCreated: null },
  review: null,
  aiAddedNodeIds: [],
  aiEditedNodeIds: [],
  onChange: (_graph: WorkflowGraph) => {},
  onSave: async (_graph: WorkflowGraph) => {},
  onDraftStateChange: (_hasDraft: boolean) => {}
};

const props = {
  fullscreen: false,
  saved: false,
  title: 'Weekly school weather brief',
  status: null,
  stop: null,
  error: null,
  editor,
  saving: false,
  canSave: true,
  onTitleInput: (_title: string) => {},
  onSave: () => {},
  onClose: () => {}
};

export default props;
export const variants = {
  authoring: {
    ...props,
    canSave: false,
    status: 'Drafting your workflow…',
    stop: { requested: false, label: 'Stop', onStop: () => {} },
    editor: { ...editor, info: null, preview: { workflow: previewWorkflow, phase: 'validating' as const, acceptedNodeCount: 2, baseGraph: null } }
  },
  saved: { ...props, saved: true, canSave: false, editor: { ...editor, workflowId: 'workflow-preview', info: null } },
  error: { ...props, editor: null, canSave: false, title: '', error: { message: 'The workflow draft could not be generated.', onRetry: () => {} } },
  fullscreen: { ...props, fullscreen: true }
};
