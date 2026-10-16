import type { WorkflowGraph } from '../../../stores/workflowWorkspaceStore';

const graph: WorkflowGraph = {
  version: 2, trigger_node_id: 'start',
  nodes: [
    { id: 'start', type: 'manual_trigger', title: 'Start', config: {} },
    { id: 'check', type: 'check', title: 'Choose activity', config: {
      mode: 'ai', result_type: 'options', selection_mode: 'single', question: 'Choose an activity for today.',
      options: [{ id: 'outdoors', label: 'Go outdoors' }, { id: 'indoors', label: 'Stay indoors' }],
    } },
  ],
  edges: [{ from: 'start', to: 'check' }],
};

const defaultProps = {
  data: { decodedContent: { workflow_id: 'workflow-chat-preview', title: 'Today’s activities', description: 'A one-time workflow saved with this chat.', lifecycle: 'chat_embed', graph } },
  embedId: 'workflow-chat-embed-preview',
  onClose: () => {},
};

export default defaultProps;
export const variants = { snapshot: defaultProps };
