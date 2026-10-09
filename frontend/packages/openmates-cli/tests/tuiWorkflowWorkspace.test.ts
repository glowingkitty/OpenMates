import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { WorkflowCapability, WorkflowDetail, WorkflowGraph, WorkflowRunDetail } from "../src/client.js";
import { cells, lineText, type TuiLine } from "../src/tuiText.js";
import { buildWorkflowNodeForm, loadWorkflowRunGraph, orderedWorkflowNodes, renderWorkflowCarousel, renderWorkflowIdentity, renderWorkflowPreviewCard, renderWorkflowWorkspace, submitWorkflowNodeForm, workflowIdentityColor, workflowNodeColor } from "../src/tuiWorkflowWorkspace.js";

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
const textOf = (lines: TuiLine[]) => lines.map(lineText).join("\n");

describe("workflow workspace", () => {
  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity
  it("centers selected Workflow cards with trigger, status, and bounded rows", () => {
    const workflows = [{ ...workflow, title: "First", category: "science" }, { ...workflow, id: "second", title: "Forecast", category: "finance",
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
    assert.equal((rows[0] as Exclude<typeof rows[number], string>).spans?.find((span) => span.bold)?.background, workflowIdentityColor(workflows[1]));
    const backgrounds = new Set(rows.flatMap(line => typeof line === 'string' ? [] : line.spans?.map(span => span.background).filter(Boolean) ?? []));
    for (const card of workflows) assert.ok(backgrounds.has(workflowIdentityColor(card)));
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
    assert.match(textOf(identity), /雨の/);
    assert.match(textOf(identity), /日 ☔️/);
    assert.ok(identity.every((line) => cells(lineText(line)) <= 18));
    assert.equal(workflowIdentityColor(named), "#DE1E66");
    assert.equal(workflowIdentityColor({ ...named, category: "finance" }), "#119106");
    assert.ok(identity.every((line) => typeof line !== "string" && line.background === "#DE1E66"));
    const template = renderWorkflowWorkspace(named, { width: 28, tab: "graph" });
    const runs = renderWorkflowWorkspace(named, { width: 28, tab: "runs" });
    assert.ok(template.every((line) => cells(lineText(line)) <= 28));
    assert.ok(runs.every((line) => cells(lineText(line)) <= 28));
    assert.match(textOf(template), /Template · g/);
    assert.match(textOf(template), /Runs · r/);
    assert.match(textOf(template), /╔═+/);
    assert.match(textOf(runs), /Runs · r/);
  });
  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity,workflows-ui.template.centered-in-place-editor
  it("shows actual branch edges despite reordered node storage", () => {
    assert.deepEqual(orderedWorkflowNodes(graph).slice(0, 2).map((node) => node.id), ["start", "condition"]);
    const lines = renderWorkflowWorkspace(workflow, { width: 100, tab: "graph", selectedNodeIndex: 1, expandedNodeId: "condition" });
    const text = textOf(lines);
    assert.match(text, /> Check/);
    assert.match(text, /Is it raining\?/);
    assert.match(text, /→ \[true\] Rain notice/);
    assert.match(text, /→ \[false\] Dry notice/);
    assert.ok(text.indexOf("manual trigger") < text.indexOf("Check"));
    assert.ok(text.indexOf("Check") < text.indexOf("end"));
    assert.match(text, /Template graph/);
    assert.match(text, /│\s+╭─ Step details/);
    assert.match(text, /e Edit title · E Edit config/);
    assert.doesNotMatch(text, /\bTest action\b|\bSave\b/);
    const narrow = textOf(renderWorkflowWorkspace(workflow, { width: 32, tab: "graph" }));
    assert.match(narrow, /→ \[true\] Rain notice/);
    assert.match(narrow, /→ \[false\] Dry notice/);
    const narrowExpanded = textOf(renderWorkflowWorkspace(workflow, { width: 32, tab: "graph", expandedNodeId: "condition" }));
    assert.match(narrowExpanded, /╭─ Step details/);
    assert.doesNotMatch(narrowExpanded, /\n\n╭─ Step details/);
    assert.match(narrowExpanded, /expression: rainy/);
    const unicodeWorkflow = { ...workflow, title: "雨の日 ☔️ forecast" };
    const unicodeLines = renderWorkflowWorkspace(unicodeWorkflow, { width: 12, tab: "graph" });
    assert.ok(unicodeLines.every((line) => cells(lineText(line)) <= 12));
    assert.match(textOf(unicodeLines), /☔️/);
    assert.doesNotMatch(text, /Start[^\n]*\n[^\n]*→ Done/);
  });

  // contract-test: direct surface=cli assertions=workflows.surface.semantic-parity,workflows-ui.template.centered-in-place-editor
  it("shows empty check continuations without inventing graph edges", () => {
    const checkGraph: WorkflowGraph = {
      version: 1, trigger_node_id: "check", nodes: [{ id: "check", type: "check", title: "Rain check", config: { predicate: { left: "rain", op: "gt", right: 0 } } }], edges: [],
    };
    const text = textOf(renderWorkflowWorkspace({ ...workflow, graph: checkGraph }, { width: 52, tab: "graph" }));
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
    const text = textOf(renderWorkflowWorkspace(workflow, { width: 100, tab: "runs", run, runs: [run], runGraph: loaded, expandedNodeId: "old" }));
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

  // contract-test: direct surface=cli assertions=workflows-ui.runs.timeline-execution-detail
  it("keeps the selected retained run and upcoming graph visible in Runs", () => {
    const next = Math.floor(Date.now() / 1000) + 3600;
    const scheduled = { ...workflow, next_run_at: next };
    const retained = textOf(renderWorkflowWorkspace(scheduled, { width: 90, tab: "runs", runs: [run], selectedRunIndex: 0, runGraph: oldGraph }));
    assert.match(retained, /Next · .* upcoming/);
    assert.match(retained, /Selected run run-1 · completed/);
    assert.match(retained, /Original start/);
    const upcoming = textOf(renderWorkflowWorkspace(scheduled, { width: 90, tab: "runs", runs: [], selectedRunIndex: -1 }));
    assert.match(upcoming, /Upcoming run/);
    assert.match(upcoming, /manual trigger/);
    assert.doesNotMatch(upcoming, /Run graph unavailable/);
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

  // contract-test: direct surface=cli assertions=workflows-ui.template.centered-in-place-editor,workflows.surface.semantic-parity
  it("edits nested capability fields with types and required validation", async () => {
    const action = { id: "skill", type: "app_skill_action" as const, title: "Search stays", config: {
      app_id: "travel", skill_id: "search_stays", input: { requests: [{ query: "Berlin", nights: 2, flexible: false }], vendor_hint: "keep" }, vendor_extension: { a: 1 },
    } };
    const source: WorkflowDetail = { ...workflow, graph: { ...graph, nodes: [...graph.nodes, action] } };
    const capability: WorkflowCapability = { type: "app_skill", id: "travel.search_stays", title: "Search stays", enabled: true,
      metadata: { app_id: "travel", skill_id: "search_stays", input_schema: { type: "object", required: ["requests"], properties: {
        requests: { type: "array", items: { type: "object", required: ["query"], properties: {
          query: { type: "string", title: "Destination" }, nights: { type: "integer", minimum: 1 }, flexible: { type: "boolean" },
        } } },
      } } } };
    const form = buildWorkflowNodeForm(source, action, [capability]);
    assert.equal(form.fields.find((field) => field.name === "config.input.requests.0.query")?.label, "requests 1 / Destination *");
    assert.equal(form.fields.find((field) => field.name === "config.input.requests.0.nights")?.valueType, "integer");
    assert.ok(form.fields.some((field) => field.label === "Advanced input JSON"));
    form.fields.find((field) => field.name === "config.input.requests.0.query")!.value = "Munich";
    form.fields.find((field) => field.name === "config.input.requests.0.nights")!.value = "3";
    form.fields.find((field) => field.name === "config.input.requests.0.flexible")!.value = "true";
    let submitted: WorkflowGraph | undefined;
    const client = { updateWorkflow: async (_id: string, payload: { graph: WorkflowGraph }) => { submitted = payload.graph; return { ...source, graph: payload.graph }; } };
    await submitWorkflowNodeForm(client as never, source, form);
    assert.deepEqual(submitted?.nodes.find((node) => node.id === "skill")?.config?.input, { requests: [{ query: "Munich", nights: 3, flexible: true }], vendor_hint: "keep" });
    assert.deepEqual(submitted?.nodes.find((node) => node.id === "skill")?.config?.vendor_extension, { a: 1 });
    assert.deepEqual(submitted?.edges, graph.edges);
    form.fields.find((field) => field.name === "config.input.requests.0.query")!.value = "";
    await assert.rejects(submitWorkflowNodeForm(client as never, source, form), /Destination \*: This field is required/);
    form.fields.find((field) => field.name === "config.input.requests.0.query")!.value = "Paris";
    form.fields.find((field) => field.name === "config.input.requests.0.nights")!.value = "0";
    await assert.rejects(submitWorkflowNodeForm(client as never, source, form), /at least 1/);
  });

  // contract-test: direct surface=cli assertions=workflows-ui.template.centered-in-place-editor
  it("exposes events search request, date and provider fields at each nested path", async () => {
    const action = { id: "events", type: "app_skill_action" as const, config: {
      app_id: "events", skill_id: "search", input: { requests: [{ query: "Meetup", location: "Berlin", count: 3,
        start_date: { ref: "$nodes.start.output.date" }, end_date: "2026-10-31", providers: ["Meetup"] }] },
    } };
    const source: WorkflowDetail = { ...workflow, graph: { ...graph, nodes: [...graph.nodes, action] } };
    const capability: WorkflowCapability = { type: "app_skill", id: "events.search", title: "Search", enabled: true,
      metadata: { app_id: "events", skill_id: "search", input_schema: { type: "object", properties: { requests: { type: "array", items: {
        type: "object", properties: {
          query: { type: "string" }, location: { type: "string" }, count: { type: "integer", minimum: 1, maximum: 50 },
          start_date: { type: "string" }, end_date: { type: "string" }, providers: { type: "array", items: { type: "string", enum: ["Meetup", "Luma"] } },
        },
      } } } } } };
    const form = buildWorkflowNodeForm(source, action, [capability]);
    const paths = form.fields.map((field) => field.name);
    for (const path of ["query", "location", "count", "start_date", "end_date", "providers.0"])
      assert.ok(paths.includes(`config.input.requests.0.${path}`), path);
    assert.equal(form.fields.find((field) => field.name === "config.input.requests.0.start_date")?.valueType, "object");
    form.fields.find((field) => field.name === "config.input.requests.0.providers.0")!.value = "Luma";
    const client = { updateWorkflow: async (_id: string, payload: { graph: WorkflowGraph }) => ({ ...source, graph: payload.graph }) };
    const saved = await submitWorkflowNodeForm(client as never, source, form);
    const request = ((saved.graph.nodes.find((node) => node.id === "events")?.config?.input as Record<string, unknown>).requests as Record<string, unknown>[])[0]!;
    assert.deepEqual(request.start_date, { ref: "$nodes.start.output.date" });
    assert.deepEqual(request.providers, ["Luma"]);
    assert.equal(workflowNodeColor(action), "#a20000");
  });

  // contract-test: direct surface=cli assertions=workflows-ui.template.centered-in-place-editor
  it("offers schedule, exact check, AI check and message fields without flattening their stored config", async () => {
    const schedule = { id: "time", type: "schedule_trigger" as const, config: { schedule: { type: "weekly", time: "09:00", weekdays: ["monday"], timezone: "Europe/Berlin", internal: "keep" } } };
    const exact = { id: "exact", type: "check" as const, config: { mode: "exact", predicate: { left: "$nodes.weather.output.rain", op: "gt", right: 0 }, internal: "keep" } };
    const ai = { id: "ai-check", type: "check" as const, config: { mode: "ai", question: "Will it rain?", selected_inputs: ["rain"] } };
    const message = { id: "message", type: "send_chat_message" as const, config: { title: "Forecast", message: "Bring a coat", chat_id: "chat-1" } };
    const source: WorkflowDetail = { ...workflow, graph: { ...graph, nodes: [...graph.nodes, schedule, exact, ai, message] } };
    const scheduleForm = buildWorkflowNodeForm(source, schedule);
    assert.deepEqual(scheduleForm.fields.filter((field) => field.name.startsWith("config.schedule.")).map((field) => field.name),
      ["config.schedule.type", "config.schedule.at", "config.schedule.minute", "config.schedule.time", "config.schedule.weekdays", "config.schedule.timezone"]);
    scheduleForm.fields.find((field) => field.name === "config.schedule.time")!.value = "11:30";
    const client = { updateWorkflow: async (_id: string, payload: { graph: WorkflowGraph }) => ({ ...source, graph: payload.graph }) };
    const saved = await submitWorkflowNodeForm(client as never, source, scheduleForm);
    assert.deepEqual(saved.graph.nodes.find((node) => node.id === "time")?.config?.schedule, { type: "weekly", time: "11:30", weekdays: ["monday"], timezone: "Europe/Berlin", internal: "keep" });
    scheduleForm.fields.find((field) => field.name === "config.schedule.type")!.value = "hourly";
    scheduleForm.fields.find((field) => field.name === "config.schedule.minute")!.value = "15";
    const hourly = await submitWorkflowNodeForm(client as never, source, scheduleForm);
    assert.deepEqual(hourly.graph.nodes.find((node) => node.id === "time")?.config?.schedule, { type: "hourly", minute: 15, timezone: "Europe/Berlin", internal: "keep" });
    const checkForm = buildWorkflowNodeForm(source, exact);
    checkForm.fields.find((field) => field.name === "config.mode")!.value = "ai";
    checkForm.fields.find((field) => field.name === "config.question")!.value = "Will it rain?";
    const aiSaved = await submitWorkflowNodeForm(client as never, source, checkForm);
    assert.equal(aiSaved.graph.nodes.find((node) => node.id === "exact")?.config?.question, "Will it rain?");
    assert.ok(buildWorkflowNodeForm(source, exact).fields.some((field) => field.name === "config.predicate.left"));
    assert.ok(buildWorkflowNodeForm(source, ai).fields.some((field) => field.name === "config.question"));
    assert.ok(buildWorkflowNodeForm(source, message).fields.some((field) => field.name === "config.chat_id"));
  });
});
