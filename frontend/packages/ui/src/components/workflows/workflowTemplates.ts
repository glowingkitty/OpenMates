import type { WorkflowGraph } from '../../stores/workflowWorkspaceStore';
import templates from './workflowTemplates.json';

export type WorkflowTemplate = {
  id: string;
  title: string;
  summary: string;
  description?: string;
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

/** The catalog graph is cloned before applying the owner's language. */
export function websiteChangesGraph(copy: {
  question: string;
  summaryPrompt: string;
  messageTitle: string;
}): WorkflowGraph {
  const graph = workflowTemplateGraph('website-changes');
  if (!graph) throw new Error('Website changes template is missing');
  for (const node of graph.nodes) {
    if (node.id === 'check') node.config = { ...node.config, question: copy.question };
    if (node.id === 'summary') node.config = { ...node.config, input: { ...(node.config?.input as Record<string, unknown>), prompt: copy.summaryPrompt } };
    if (node.id === 'message') node.config = { ...node.config, title: copy.messageTitle };
  }
  return graph;
}
