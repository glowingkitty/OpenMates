import type { WorkflowGraph, WorkflowNode } from '../../stores/workflowWorkspaceStore';
import { isCheck, isTrigger } from './workflowBuilder';

type Direction = 'up' | 'down';

function referencesNode(value: unknown, nodeId: string): boolean {
  if (typeof value === 'string') return value.includes(`$nodes.${nodeId}.`) || value.includes(`steps.${nodeId}.`);
  if (Array.isArray(value)) return value.some(item => referencesNode(item, nodeId));
  if (value && typeof value === 'object') return Object.values(value).some(item => referencesNode(item, nodeId));
  return false;
}

function adjacent(graph: WorkflowGraph, nodeId: string, direction: Direction): [WorkflowNode, WorkflowNode] | null {
  const edge = direction === 'up'
    ? graph.edges.find(item => item.to === nodeId)
    : graph.edges.find(item => item.from === nodeId && !item.branch);
  if (!edge) return null;
  const upper = graph.nodes.find(item => item.id === edge.from);
  const lower = graph.nodes.find(item => item.id === edge.to);
  if (!upper || !lower) return null;
  if (isTrigger(upper) || isTrigger(lower) || isCheck(upper) || isCheck(lower)) return null;
  if (upper.type === 'end' || lower.type === 'end') return null;
  if (graph.trigger_node_id === upper.id || graph.trigger_node_id === lower.id) return null;
  const upperIncoming = graph.edges.filter(item => item.to === upper.id);
  const lowerIncoming = graph.edges.filter(item => item.to === lower.id);
  const upperOutgoing = graph.edges.filter(item => item.from === upper.id);
  const lowerOutgoing = graph.edges.filter(item => item.from === lower.id);
  if (upperIncoming.length > 1 || lowerIncoming.length !== 1 || upperOutgoing.length !== 1 || lowerOutgoing.length > 1) return null;
  if (upperOutgoing[0] !== edge || edge.branch || lowerOutgoing.some(item => item.branch)) return null;
  if (referencesNode(lower.config, upper.id)) return null;
  return [upper, lower];
}

export function canMoveWorkflowNode(graph: WorkflowGraph, nodeId: string, direction: Direction): boolean {
  return adjacent(graph, nodeId, direction) !== null;
}

export function moveWorkflowNode(graph: WorkflowGraph, nodeId: string, direction: Direction): WorkflowGraph | null {
  const pair = adjacent(graph, nodeId, direction);
  if (!pair) return null;
  const [upper, lower] = pair;
  const before = graph.edges.find(item => item.to === upper.id);
  const after = graph.edges.find(item => item.from === lower.id);
  const nodes = graph.nodes.filter(item => item.id !== lower.id);
  nodes.splice(nodes.findIndex(item => item.id === upper.id), 0, lower);
  return {
    ...graph,
    nodes,
    edges: [
      ...graph.edges.filter(item => item !== before && item.from !== upper.id && item.from !== lower.id),
      ...(before ? [{ ...before, to: lower.id }] : []),
      { from: lower.id, to: upper.id },
      ...(after ? [{ ...after, from: upper.id }] : []),
    ],
  };
}

/** Drop on a node inserts immediately before it when dragging up, or after it when dragging down. */
export function moveWorkflowNodeTo(graph: WorkflowGraph, sourceId: string, targetId: string): WorkflowGraph | null {
  if (sourceId === targetId) return null;
  for (const direction of ['up', 'down'] as const) {
    let current = graph;
    const seen = new Set<string>();
    while (!seen.has(JSON.stringify(current.edges))) {
      seen.add(JSON.stringify(current.edges));
      const neighbor = direction === 'up'
        ? current.edges.find(item => item.to === sourceId)?.from
        : current.edges.find(item => item.from === sourceId && !item.branch)?.to;
      if (!neighbor) break;
      const next = moveWorkflowNode(current, sourceId, direction);
      if (!next) break;
      current = next;
      if (neighbor === targetId) return current;
    }
  }
  return null;
}

/** Insert at the connector after a node. A drop in the current slot is a no-op. */
export function moveWorkflowNodeAfter(graph: WorkflowGraph, sourceId: string, afterId: string): WorkflowGraph | null {
  if (sourceId === afterId) return null;
  const next = graph.edges.find(edge => edge.from === afterId && !edge.branch)?.to;
  if (next === sourceId) return null;
  let cursor = sourceId;
  const visited = new Set<string>();
  while (!visited.has(cursor)) {
    if (cursor === afterId) return moveWorkflowNodeTo(graph, sourceId, afterId);
    visited.add(cursor);
    const edge = graph.edges.find(item => item.from === cursor && !item.branch);
    if (!edge) break;
    cursor = edge.to;
  }
  return next ? moveWorkflowNodeTo(graph, sourceId, next) : null;
}
