import type { WorkflowGraph, WorkflowBindingRequirement } from '../../stores/workflowWorkspaceStore';

const graph: WorkflowGraph = {
  version: 2, trigger_node_id: 'step_1',
  nodes: [
    { id: 'step_1', type: 'schedule_trigger', title: 'Every morning', config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } } },
    { id: 'step_2', type: 'send_chat_message', title: 'Send report', config: { title: 'Morning report', message: 'Your report', destination_required: true } },
  ],
  edges: [{ from: 'step_1', to: 'step_2' }],
};
const requirements: WorkflowBindingRequirement[] = [
  { type: 'schedule', node_id: 'step_1' },
  { type: 'chat_destination', node_id: 'step_2' },
];

const defaultProps = {
  requirements, completed: [] as WorkflowBindingRequirement[], graph,
  saving: false, hasUnsavedChanges: false,
  onEdit: (nodeId: string) => { window.dispatchEvent(new CustomEvent('workflow-preview-edit-binding', { detail: nodeId })); },
  onConfirm: (requirement: WorkflowBindingRequirement) => { window.dispatchEvent(new CustomEvent('workflow-preview-confirm-binding', { detail: requirement.node_id })); },
};

export default defaultProps;
export const variants = {
  unsaved: { ...defaultProps, hasUnsavedChanges: true },
  partial: { ...defaultProps, completed: [requirements[0]] },
};
