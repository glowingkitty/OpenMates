// Preview states for the shared workflow editor surface:
// /dev/preview/workflows/WorkflowEditorWorkspace?chrome=0[&variant=...]
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

const props = {
  workflowId: null,
  graph,
  saving: false,
  preview: null,
  partialNotice: null,
  info: null,
  review: null,
  testNow: null,
  aiAddedNodeIds: [],
  aiEditedNodeIds: [],
  onChange: (_graph: WorkflowGraph) => {},
  onSave: async (_graph: WorkflowGraph) => {},
  onDraftStateChange: (_hasDraft: boolean) => {}
};

export default props;
export const variants = {
  aiEdited: {
    ...props,
    aiAddedNodeIds: ['message'],
    aiEditedNodeIds: ['weather'],
    info: { createdDisabled: false, reminder: null, assumptions: ['Uses Berlin as the location.'], onUndoCreated: null }
  },
  preview: {
    ...props,
    preview: {
      workflow: { id: 'provisional-0', title: 'Weekly school weather brief', description: null, status: 'provisional', enabled: false, current_version_id: '', graph } as WorkflowDetail,
      phase: 'planning' as const,
      acceptedNodeCount: 1,
      baseGraph: null
    }
  },
  testNow: { ...props, workflowId: 'workflow-preview', testNow: { disabled: false, label: 'Test now', onRun: () => {} } }
};
