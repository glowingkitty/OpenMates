import type { WorkflowGraph } from '../../stores/workflowWorkspaceStore';
import templates from './workflowTemplates.json';

export type WorkflowTemplate = {
  id: string;
  title: string;
  summary: string;
  category: string;
  icon: string;
  graph: WorkflowGraph;
};

/** Fresh graph instances keep editing one owner's copy from changing the catalog. */
export function workflowTemplateGraph(id: string): WorkflowGraph | null {
  const template = workflowTemplates.find((item) => item.id === id);
  return template ? structuredClone(template.graph) : null;
}

export const workflowTemplates = templates as unknown as WorkflowTemplate[];
