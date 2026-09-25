import { describe, expect, it } from "vitest";
import type { WorkflowGraph, WorkflowRun } from "../../../stores/workflowWorkspaceStore";
import type { Capability } from "../workflowBuilder";
import { workflowOutputExamples, workflowUpstreamOutputs } from "../workflowOutputExamples";

const graph: WorkflowGraph = {
  version: 2,
  trigger_node_id: "trigger",
  nodes: [
    { id: "trigger", type: "schedule_trigger", config: {} },
    { id: "search", type: "app_skill_action", config: { app_id: "events", skill_id: "search" } },
    { id: "check", type: "check", config: { mode: "exact", predicate: {} } },
  ],
  edges: [
    { from: "trigger", to: "search" },
    { from: "search", to: "check" },
  ],
};

const capabilities: Capability[] = [{
  id: "events.search",
  type: "app_skill",
  enabled: true,
  title: "Search events",
  metadata: {
    app_id: "events",
    skill_id: "search",
    output_schema: {
      properties: {
        result_count: { type: "integer", example: 2 },
        results: { type: "array", items: { type: "object", properties: { title: { type: "string", example: "Example event" } } } },
      },
    },
  },
}];

function retainedRun(startedAt: number, status: string, output: Record<string, unknown>): WorkflowRun {
  return {
    id: `run-${startedAt}`,
    workflow_id: "workflow",
    version_id: "version",
    trigger_type: "schedule",
    status: "completed",
    started_at: startedAt,
    content_available: true,
    node_runs: [{
      id: `node-${startedAt}`,
      run_id: `run-${startedAt}`,
      workflow_id: "workflow",
      node_id: "search",
      node_type: "app_skill_action",
      status,
      output_summary: output,
    }],
  };
}

describe("workflowOutputExamples", () => {
  // contract-test: supporting surface=gui.web assertions=workflows.control.typed-data
  it("uses the newest successful retained node output ahead of schema examples", () => {
    const examples = workflowOutputExamples(graph, capabilities, [
      retainedRun(100, "completed", { result_count: 1, results: [{ title: "Older" }] }),
      retainedRun(300, "failed", { result_count: 99 }),
      retainedRun(200, "completed", { result_count: 4, results: [{ title: "Latest successful" }] }),
    ]);

    expect(examples.valuesByNode.search).toEqual({ result_count: 4, results: [{ title: "Latest successful" }] });
    expect(examples.sourceByNode.search).toBe("run");
  });

  // contract-test: supporting surface=gui.web assertions=workflows.control.typed-data
  it("falls back to declared schema examples when retained content is unavailable", () => {
    const examples = workflowOutputExamples(graph, capabilities, []);

    expect(examples.valuesByNode.search).toEqual({
      result_count: 2,
      results: [{ title: "Example event" }],
    });
    expect(examples.sourceByNode.search).toBe("schema");
  });

  // contract-test: supporting surface=gui.web assertions=workflows.control.typed-data,workflows.control.check
  it("passes only ancestor outputs into a node test", () => {
    expect(workflowUpstreamOutputs(graph, "check", {
      trigger: { triggered: true },
      search: { result_count: 2 },
      check: { matched: true },
      unrelated: { private: "excluded" },
    })).toEqual({ trigger: { triggered: true }, search: { result_count: 2 } });
  });
});
