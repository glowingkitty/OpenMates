import { workflowApiRequest, type WorkflowDetail, type WorkflowNode } from '../stores/workflowWorkspaceStore';

export type WorkflowInputChange = {
  workflow_id: string;
  added_node_ids: string[];
  edited_node_ids: string[];
  removed_nodes: Array<{ id: string; title: string }>;
};

export type WorkflowInputSession = {
  session_id: string;
  status: string;
  message?: string | null;
  error?: string | null;
  error_code?: string | null;
  workflow?: WorkflowDetail | null;
  preview_workflow?: WorkflowDetail | null;
  // The batch service will populate these only after its atomic commit.
  workflows?: WorkflowDetail[];
  changes?: WorkflowInputChange[];
  assumptions?: string[];
  undo_available?: boolean;
  mutations?: Array<{ type: 'create_workflow' | 'update_workflow' | 'link_workflow_to_project'; target_id: string; before?: { graph?: { nodes?: WorkflowNode[] } } | null; after?: { graph?: { nodes?: WorkflowNode[] } } | null }>;
};

export function committedWorkflows(session: WorkflowInputSession): WorkflowDetail[] {
  if (session.status !== 'executed') return [];
  return session.workflows ?? (session.workflow ? [session.workflow] : []);
}

export function workflowNodeChanges(before: WorkflowNode[], after: WorkflowNode[]): Omit<WorkflowInputChange, 'workflow_id'> {
  const previous = new Map(before.map(node => [node.id, node]));
  const current = new Map(after.map(node => [node.id, node]));
  return {
    added_node_ids: after.filter(node => !previous.has(node.id)).map(node => node.id),
    edited_node_ids: after.filter(node => {
      const old = previous.get(node.id);
      return old !== undefined && JSON.stringify(old) !== JSON.stringify(node);
    }).map(node => node.id),
    removed_nodes: before.filter(node => !current.has(node.id)).map(node => ({ id: node.id, title: node.title || node.type.replaceAll('_', ' ') }))
  };
}

export async function submitWorkflowInstruction(text: string, selectedWorkflowId?: string): Promise<WorkflowInputSession> {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>('/v1/workflows/input', {
    method: 'POST',
    body: JSON.stringify({ text, input_type: 'text', selected_workflow_id: selectedWorkflowId ?? null, timezone, optimistic_save: true })
  });
  return result.session;
}

export async function undoWorkflowInstruction(sessionId: string): Promise<WorkflowInputSession> {
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}/undo`, {
    method: 'POST', body: '{}'
  });
  return result.session;
}

export async function getWorkflowInstruction(sessionId: string): Promise<WorkflowInputSession> {
  const result = await workflowApiRequest<{ session: WorkflowInputSession }>(`/v1/workflows/input/${encodeURIComponent(sessionId)}`);
  return result.session;
}
