import { test, expect } from 'vitest';
import type { WorkflowGraph, WorkflowNode } from '../../../stores/workflowWorkspaceStore';
import { canMoveWorkflowNode, moveWorkflowNode, moveWorkflowNodeTo } from '../workflowReordering';

const node = (id: string, type: WorkflowNode['type'] = 'app_skill_action', config: WorkflowNode['config'] = {}): WorkflowNode => ({ id, type, config });
const graph: WorkflowGraph = {
  version: 2,
  trigger_node_id: 'trigger',
  nodes: [node('trigger', 'schedule_trigger'), node('a'), node('b'), node('c'), node('send', 'send_chat_message')],
  edges: [
    { from: 'trigger', to: 'a' },
    { from: 'a', to: 'b' },
    { from: 'b', to: 'c' },
    { from: 'c', to: 'send' },
  ],
};
const links = (value: WorkflowGraph) => value.edges.map(edge => `${edge.from}->${edge.to}`).sort();

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring
test('adjacent controls change graph order without moving the trigger', () => {
  expect(canMoveWorkflowNode(graph, 'a', 'up')).toBe(false);
  expect(canMoveWorkflowNode(graph, 'b', 'up')).toBe(true);
  const moved = moveWorkflowNode(graph, 'b', 'up');
  expect(moved).not.toBeNull();
  expect(moved!.nodes.map(item => item.id)).toEqual(['trigger', 'b', 'a', 'c', 'send']);
  expect(links(moved!)).toEqual(['a->c', 'b->a', 'c->send', 'trigger->b']);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring
test('dragging across multiple steps keeps their continuation connected', () => {
  const moved = moveWorkflowNodeTo(graph, 'c', 'a');
  expect(moved).not.toBeNull();
  expect(moved!.nodes.map(item => item.id)).toEqual(['trigger', 'c', 'a', 'b', 'send']);
  expect(links(moved!)).toEqual(['a->b', 'b->send', 'c->a', 'trigger->c']);
  expect(moveWorkflowNodeTo(graph, 'c', 'c')).toBeNull();
});

// contract-test: supporting surface=gui.web assertions=workflows.control.typed-data,workflows-ui.mvp.authoring
test('moves cannot put a referenced output after its consumer', () => {
  const dependent: WorkflowGraph = {
    ...graph,
    nodes: graph.nodes.map(item => item.id === 'b'
      ? { ...item, config: { input: { prompt: 'Use {{steps.a.answer}} and $nodes.a.output.summary' } } }
      : item),
  };
  expect(canMoveWorkflowNode(dependent, 'b', 'up')).toBe(false);
  expect(moveWorkflowNodeTo(dependent, 'b', 'a')).toBeNull();
  expect(moveWorkflowNodeTo(dependent, 'a', 'b')).toBeNull();
});

// contract-test: supporting surface=gui.web assertions=workflows.control.check,workflows-ui.mvp.authoring
test('branch labels remain attached while moving within one branch', () => {
  const branched: WorkflowGraph = {
    ...graph,
    nodes: [node('trigger', 'schedule_trigger'), node('check', 'check'), node('yes'), node('next'), node('no')],
    edges: [
      { from: 'trigger', to: 'check' },
      { from: 'check', to: 'yes', branch: 'yes' },
      { from: 'yes', to: 'next' },
      { from: 'check', to: 'no', branch: 'no' },
    ],
  };
  const moved = moveWorkflowNode(branched, 'next', 'up');
  expect(moved).not.toBeNull();
  expect(moved!.edges.find(edge => edge.branch === 'yes')).toEqual({ from: 'check', to: 'next', branch: 'yes' });
  expect(moved!.edges.find(edge => edge.from === 'next')).toEqual({ from: 'next', to: 'yes' });
  expect(canMoveWorkflowNode(branched, 'yes', 'up')).toBe(false);
  expect(moveWorkflowNodeTo(branched, 'no', 'yes')).toBeNull();
});
