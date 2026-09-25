import type {
  WorkflowGraph,
  WorkflowNodeRun,
  WorkflowRun,
} from "../../stores/workflowWorkspaceStore";
import { exampleValue } from "./workflowValuePresentation";
import {
  capabilityFor,
  type Capability,
  type Insertion,
} from "./workflowBuilder";

export type WorkflowOutputExampleSource = "run" | "schema";

export type WorkflowOutputExamples = {
  valuesByNode: Record<string, Record<string, unknown>>;
  sourceByNode: Record<string, WorkflowOutputExampleSource>;
};

function outputRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length ? record : null;
}

function schemaExample(capability: Capability | undefined): Record<string, unknown> | null {
  const schema = capability?.metadata.output_schema;
  if (!schema) return null;
  const rootExample = outputRecord(exampleValue(schema));
  if (rootExample) return rootExample;
  const entries = Object.entries(schema.properties ?? {})
    .map(([key, child]) => [key, exampleValue(child)] as const)
    .filter(([, value]) => value !== undefined);
  return entries.length ? Object.fromEntries(entries) : null;
}

function completedNodeRunsNewestFirst(runs: WorkflowRun[]): WorkflowNodeRun[] {
  return [...runs]
    .sort((left, right) =>
      (right.started_at ?? right.finished_at ?? 0) -
      (left.started_at ?? left.finished_at ?? 0),
    )
    .flatMap((run) => run.node_runs ?? [])
    .filter((nodeRun) => nodeRun.status === "completed");
}

/**
 * Resolve examples without inventing user data. Retained successful output wins;
 * otherwise the app's declared schema example is used.
 */
export function workflowOutputExamples(
  graph: WorkflowGraph,
  capabilities: Capability[],
  runs: WorkflowRun[],
): WorkflowOutputExamples {
  const valuesByNode: Record<string, Record<string, unknown>> = {};
  const sourceByNode: Record<string, WorkflowOutputExampleSource> = {};

  for (const node of graph.nodes) {
    const example = schemaExample(capabilityFor(node, capabilities));
    if (example) {
      valuesByNode[node.id] = example;
      sourceByNode[node.id] = "schema";
    }
  }

  for (const nodeRun of completedNodeRunsNewestFirst(runs)) {
    if (sourceByNode[nodeRun.node_id] === "run") continue;
    const output = outputRecord(nodeRun.output_summary);
    if (!output) continue;
    valuesByNode[nodeRun.node_id] = output;
    sourceByNode[nodeRun.node_id] = "run";
  }

  return { valuesByNode, sourceByNode };
}

/** Keep a step test scoped to data available before that node in the graph. */
export function workflowUpstreamOutputs(
  graph: WorkflowGraph,
  nodeId: string,
  outputs: Record<string, Record<string, unknown>>,
  insertion?: Insertion | null,
): Record<string, Record<string, unknown>> {
  const ancestors = new Set<string>();
  const visit = (id: string): void => {
    for (const edge of graph.edges.filter((candidate) => candidate.to === id)) {
      if (ancestors.has(edge.from)) continue;
      ancestors.add(edge.from);
      visit(edge.from);
    }
  };

  if (graph.nodes.some((node) => node.id === nodeId)) visit(nodeId);
  else if (insertion?.after) {
    ancestors.add(insertion.after);
    visit(insertion.after);
  }

  return Object.fromEntries(
    Array.from(ancestors)
      .filter((ancestor) => outputs[ancestor])
      .map((ancestor) => [ancestor, outputs[ancestor]]),
  );
}
