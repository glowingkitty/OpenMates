import type { WorkflowDetail, WorkflowRun } from '../../stores/workflowWorkspaceStore';

const workflow = {
  id: 'preview-workflow', title: 'Weekly report', status: 'active', enabled: false,
  current_version_id: 'preview-version', graph: {
    version: 2, trigger_node_id: 'trigger',
    nodes: [{ id: 'trigger', type: 'manual_trigger', title: 'Start', config: {} }], edges: [],
  },
} as WorkflowDetail;

const runs = [
  { id: 'latest-run', workflow_id: workflow.id, version_id: 'preview-version', status: 'completed', trigger_type: 'manual', started_at: 1_760_000_000 },
  { id: 'older-run', workflow_id: workflow.id, version_id: 'preview-version', status: 'completed', trigger_type: 'manual', started_at: 1_750_000_000 },
] as WorkflowRun[];

const callbacks = {
  onSelectRun: (runId: string) => window.dispatchEvent(new CustomEvent('workflow-preview-select-run', { detail: runId })),
  onOpenEditor: () => {},
};

export default { workflow, runs, selectedRunId: 'older-run', editorHref: '/#workflow-id=preview-workflow', ...callbacks };
export const variants = {
  missing: { workflow, runs, selectedRunId: 'missing-run', editorHref: '/#workflow-id=preview-workflow', ...callbacks },
};
