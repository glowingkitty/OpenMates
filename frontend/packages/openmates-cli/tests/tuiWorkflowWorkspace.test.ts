import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { WorkflowDetail, WorkflowGraph, WorkflowRunDetail } from "../src/client.js";
import { cells } from "../src/tuiText.js";
import { buildWorkflowNodeForm, loadWorkflowRunGraph, renderWorkflowCarousel, renderWorkflowIdentity, renderWorkflowPreviewCard, renderWorkflowWorkspace, submitWorkflowNodeForm } from "../src/tuiWorkflowWorkspace.js";
import { PRIMARY_GRADIENT } from "../../appGradientTheme.js";

const graph: WorkflowGraph = {
  version: 1,
  trigger_node_id: "start",
  nodes: [
    { id: "finish", type: "end", title: "Done" },
    { id: "no", type: "send_notification", title: "Dry notice", config: { title: "Dry" } },
    { id: "start", type: "manual_trigger", title: "Start" },
    { id: "yes", type: "send_notification", title: "Rain notice", config: { title: "Rain" } },
    { id: "condition", type: "decision", title: "Is it raining?", config: { expression: "rainy" } },
  ],
  edges: [
    { from: "start", to: "condition" },
    { from: "condition", to: "yes", branch: "true" },
    { from: "condition", to: "no", branch: "false" },
    { from: "yes", to: "finish" },
    { from: "no", to: "finish" },
  ],
};

const workflow: WorkflowDetail = {
  id: "wf-1", title: "Forecast", status: "active", enabled: true,
  current_version_id: "v2", created_at: 1, updated_at: 2, graph,
};

const oldGraph: WorkflowGraph = {
  version: 1, trigger_node_id: "old", nodes: [
    { id: "old", type: "manual_trigger", title: "Original start" },
    { id: "old-end", type: "end", title: "Original end" },
  ], edges: [{ from: "old", to: "old-end" }],
};
const run: WorkflowRunDetail = {
  id: "run-1", workflow_id: "wf-1", version_id: "v1", trigger_type: "manual", status: "completed",
  node_runs: [{ id: "nr-1", run_id: "run-1", workflow_id: "wf-1", node_id: "old", node_type: "manual_trigger", status: "completed", output_summary: { rainy: true } }],
  output_summary: { outcome: "sent" },
};

describe("workflow workspace", () => {
  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity
  it("centers selected Workflow cards with trigger, status, and bounded rows", () => {
    const workflows = [{ ...workflow, title: "First" }, { ...workflow, id: "second", title: "Forecast",
      description: "Weather report", trigger_summary: "Daily 09:00", last_run_status: "completed" as const },
    { ...workflow, id: "third", title: "Third", enabled: false }];
    const lines = renderWorkflowCarousel(workflows, 110, 1, true);
    const rows = lines.slice(0, 7);
    const text = rows.map((line) => typeof line === "string" ? line : line.text).join("\n");
    assert.equal(lines.length, 9);
    assert.match(text, /First[\s\S]*Forecast[\s\S]*Third/);
    assert.match(text, /Weather report/);
    assert.match(text, /Daily 09:00/);
    assert.match(text, /Enabled · Last: completed/);
    assert.equal((rows[0] as Exclude<typeof rows[number], string>).text.indexOf("╭", 20), 37);
    assert.equal((rows[0] as Exclude<typeof rows[number], string>).spans?.find((span) => span.bold)?.background, PRIMARY_GRADIENT.start);
    assert.match(String(lines.at(-1)), /Workflow 2 of 3 · ←\/→ choose workflow · Enter open/);
    for (const width of [1, 4, 17, 36]) {
      const narrow = renderWorkflowCarousel(workflows, width, 1, false);
      assert.equal(narrow.length, width < 4 ? 3 : 9);
      assert.ok(narrow.every((line) => cells(typeof line === "string" ? line : line.text) <= width));
    }
  });
  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity,workflows-ui.workspace.continue-priority
  it("renders a selectable workflow preview card", () => {
    const lines = renderWorkflowPreviewCard({ ...workflow, trigger_summary: "Every day at 09:00", last_run_status: "completed" }, { width: 44, selected: true });
    assert.match(lines.join("\n"), /> Forecast/);
    assert.match(lines.join("\n"), /Enabled · Every day at 09:00/);
    assert.match(lines.join("\n"), /Last run: completed/);
    assert.ok(lines.every((line) => cells(line) <= 44));
  });
  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity,workflows-ui.detail.stable-visual-header,workflows-ui.detail.shared-template-runs-tabs
  it("keeps identity and outlined keyboard tabs inside narrow Unicode cell widths", () => {
    const named = { ...workflow, title: "雨の日 ☔️ forecast", description: "Berlin weather" };
    const identity = renderWorkflowIdentity(named, { width: 18 });
    assert.match(identity.join("\n"), /雨の/);
    assert.match(identity.join("\n"), /日 ☔️/);
    assert.ok(identity.every((line) => cells(line) <= 18));
    const template = renderWorkflowWorkspace(named, { width: 28, tab: "graph" });
    const runs = renderWorkflowWorkspace(named, { width: 28, tab: "runs" });
    assert.ok(template.every((line) => cells(line) <= 28));
    assert.ok(runs.every((line) => cells(line) <= 28));
    assert.match(template.join("\n"), /Template · g/);
    assert.match(template.join("\n"), /Runs · r/);
    assert.match(template.join("\n"), /╔═+/);
    assert.match(runs.join("\n"), /Runs · r/);
  });
  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity,workflows-ui.template.centered-in-place-editor
  it("shows actual branch edges despite reordered node storage", () => {
    const lines = renderWorkflowWorkspace(workflow, { width: 100, tab: "graph", selectedNodeIndex: 4, expandedNodeId: "condition" });
    const text = lines.join("\n");
    assert.match(text, /> \[decision\]/);
    assert.match(text, /Is it raining\?/);
    assert.match(text, /→ \[true\] Rain notice/);
    assert.match(text, /→ \[false\] Dry notice/);
    assert.ok(text.indexOf("[manual trigger]") < text.indexOf("[decision]"));
    assert.ok(text.indexOf("[decision]") < text.indexOf("[end]"));
    assert.match(text, /╭─ Template graph/);
    assert.match(text, /│\s+╭─ Step details/);
    assert.match(text, /e Edit title · E Edit config/);
    assert.doesNotMatch(text, /\bTest action\b|\bSave\b/);
    const narrow = renderWorkflowWorkspace(workflow, { width: 32, tab: "graph" }).join("\n");
    assert.match(narrow, /→ \[true\] Rain notice/);
    assert.match(narrow, /→ \[false\] Dry notice/);
    const narrowExpanded = renderWorkflowWorkspace(workflow, { width: 32, tab: "graph", expandedNodeId: "condition" }).join("\n");
    assert.match(narrowExpanded, /╭─ Step details/);
    assert.doesNotMatch(narrowExpanded, /\n\n╭─ Step details/);
    assert.match(narrowExpanded, /expression: rainy/);
    const unicodeWorkflow = { ...workflow, title: "雨の日 ☔️ forecast" };
    const unicodeLines = renderWorkflowWorkspace(unicodeWorkflow, { width: 12, tab: "graph" });
    assert.ok(unicodeLines.every((line) => cells(line) <= 12));
    assert.match(unicodeLines.join("\n"), /☔️/);
    assert.doesNotMatch(text, /Start[^\n]*\n[^\n]*→ Done/);
  });

  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity,workflows-ui.template.centered-in-place-editor
  it("shows empty check continuations without inventing graph edges", () => {
    const checkGraph: WorkflowGraph = {
      version: 1, trigger_node_id: "check", nodes: [{ id: "check", type: "check", title: "Rain check", config: { predicate: { left: "rain", op: "gt", right: 0 } } }], edges: [],
    };
    const text = renderWorkflowWorkspace({ ...workflow, graph: checkGraph }, { width: 52, tab: "graph" }).join("\n");
    assert.match(text, /If true: no step/);
    assert.match(text, /Else: no step/);
    assert.doesNotMatch(text, /then →/);
  });

  // contract-test: direct surface=cli assertions=workflows.execution.lifecycle-visible,workflows-ui.runs.timeline-execution-detail
  it("loads and renders the recorded historical version", async () => {
    let requested = "";
    const client = { getWorkflowVersion: async (_id: string, version: string) => { requested = version; return { graph: oldGraph }; } };
    const loaded = await loadWorkflowRunGraph(client as never, workflow, run);
    assert.equal(requested, "v1");
    const text = renderWorkflowWorkspace(workflow, { width: 100, tab: "runs", run, runs: [run], runGraph: loaded, expandedNodeId: "old" }).join("\n");
    assert.match(text, /Original start/);
    assert.match(text, /Original end/);
    assert.match(text, /Run output/);
    assert.match(text, /rainy: true/);
    assert.match(text, /Recorded step · read-only/);
    assert.doesNotMatch(text, /E Edit config/);
    assert.doesNotMatch(text, /\{"rainy":true\}/);
    assert.doesNotMatch(text, /Rain notice/);
    assert.equal(await loadWorkflowRunGraph({ getWorkflowVersion: async () => { throw new Error("current version must use loaded graph"); } } as never, workflow, { ...run, version_id: "v2" }), graph);
    await assert.rejects(loadWorkflowRunGraph(client as never, workflow, { ...run, workflow_id: "other" }), /does not belong/);
  });

  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity,workflows-ui.template.explicit-guarded-save
  it("edits typed simple config and preserves unknown fields and graph IDs", async () => {
    const source: WorkflowDetail = {
      ...workflow, graph: { ...graph, nodes: graph.nodes.map((node) => node.id === "no"
        ? { ...node, config: { title: "Dry", urgency: 2, enabled: true, vendor_extension: { channel: "private" } } }
        : node) },
    };
    const node = source.graph.nodes.find((candidate) => candidate.id === "no")!;
    const form = buildWorkflowNodeForm(source, node);
    assert.equal(form.contextId, "no");
    assert.ok(form.fields.some((field) => field.name === "config.title"));
    form.fields.find((field) => field.name === "title")!.value = "No rain";
    form.fields.find((field) => field.name === "config.title")!.value = "No umbrella";
    form.fields.find((field) => field.name === "config.urgency")!.value = "3";
    form.fields.find((field) => field.name === "config.enabled")!.value = "false";
    let submitted: WorkflowGraph | undefined;
    const client = { updateWorkflow: async (_id: string, payload: { graph: WorkflowGraph }) => { submitted = payload.graph; return { ...source, graph: payload.graph }; } };
    const result = await submitWorkflowNodeForm(client as never, source, form);
    assert.deepEqual(result.graph.nodes.map((item) => item.id), graph.nodes.map((item) => item.id));
    assert.deepEqual(result.graph.edges, graph.edges);
    assert.deepEqual(submitted?.nodes.find((item) => item.id === "no")?.config, {
      title: "No umbrella", urgency: 3, enabled: false, vendor_extension: { channel: "private" },
    });
    assert.equal(source.graph.nodes.find((item) => item.id === "no")?.title, "Dry notice");
    form.fields.find((field) => field.name === "config.urgency")!.value = "not-a-number";
    await assert.rejects(submitWorkflowNodeForm(client as never, source, form), /valid number/);
  });
});
