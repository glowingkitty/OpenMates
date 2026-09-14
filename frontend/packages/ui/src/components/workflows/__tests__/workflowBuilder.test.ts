import { test } from "node:test";
import assert from "node:assert/strict";
import {
  insertNode,
  messageDestinationConfig,
  workflowGraphReady,
  outputsBefore,
  workflowIcon,
  normalizeSchema,
  schemaDefault,
  type Capability,
} from "../workflowBuilder.ts";
import {
  dailyWeatherNewsGraph,
  weeklyEventsGraph,
  hourlyApartmentsGraph,
} from "../workflowExamples.ts";
import type {
  WorkflowGraph,
  WorkflowNode,
} from "../../../stores/workflowWorkspaceStore.ts";
const capabilities: Capability[] = [
  {
    id: "news.search",
    type: "app_skill",
    title: "Search",
    enabled: true,
    metadata: {
      app_id: "news",
      skill_id: "search",
      output_schema: { properties: { results: { type: "array" } } },
    },
  },
];
const node = (
  id: string,
  type: WorkflowNode["type"] = "app_skill_action",
): WorkflowNode => ({
  id,
  type,
  config:
    type === "app_skill_action" ? { app_id: "news", skill_id: "search" } : {},
});
const graph: WorkflowGraph = {
  version: 2,
  trigger_node_id: "trigger",
  nodes: [
    node("trigger", "schedule_trigger"),
    node("news"),
    node("check", "check"),
    node("yes"),
    node("no"),
    node("message", "send_chat_message"),
  ],
  edges: [
    { from: "trigger", to: "news" },
    { from: "news", to: "check" },
    { from: "check", to: "yes", branch: "yes" },
    { from: "check", to: "no", branch: "no" },
    { from: "check", to: "message" },
  ],
};

// contract-test: supporting surface=gui.web assertions=workflows.control.typed-data,workflows.control.check,workflows-ui.mvp.authoring
test("new true-branch action cannot bind future or sibling-branch results", () => {
  const outputs = outputsBefore(graph, "draft", capabilities, { after: "yes" });
  assert.deepEqual(outputs.map((output) => output.nodeId).sort(), [
    "check",
    "news",
    "yes",
  ]);
  assert.equal(
    outputs.find((output) => output.nodeId === "check")?.schema.type,
    "boolean",
  );
});
// contract-test: supporting surface=gui.web assertions=workflows.control.check,workflows-ui.mvp.authoring
test("inserting a true-branch action preserves the else and continuation paths", () => {
  const updated = insertNode(graph, node("new"), {
    after: "check",
    branch: "yes",
  });
  assert(
    updated.edges.some(
      (edge) =>
        edge.from === "check" && edge.to === "new" && edge.branch === "yes",
    ),
  );
  assert(
    updated.edges.some(
      (edge) => edge.from === "new" && edge.to === "yes" && !edge.branch,
    ),
  );
  assert(
    updated.edges.some(
      (edge) =>
        edge.from === "check" && edge.to === "no" && edge.branch === "no",
    ),
  );
  assert(
    updated.edges.some(
      (edge) => edge.from === "check" && edge.to === "message" && !edge.branch,
    ),
  );
  assert.equal(graph.nodes.length, 6);
});
// contract-test: supporting surface=gui.web assertions=workflows.activation.reachable-side-effect,workflows-ui.mvp.authoring
test("adding a trigger after configuring an action keeps the action intact", () => {
  const action = node("news");
  const draft: WorkflowGraph = {
    version: 2,
    trigger_node_id: null,
    nodes: [action],
    edges: [],
  };
  const updated = insertNode(draft, node("trigger", "schedule_trigger"), {
    after: "news",
  });
  assert.equal(updated.trigger_node_id, "trigger");
  assert.deepEqual(updated.edges, [{ from: "trigger", to: "news" }]);
  assert.equal(updated.nodes[1], action);
});
// contract-test: supporting surface=gui.web assertions=workflows.schedule.recurrence,workflows.control.filter,workflows-ui.message-and-budget,workflows-ui.identity.automatic-category-icon
test("video starters use relative weekly dates and delivered-only lists without Filters", () => {
  const daily = dailyWeatherNewsGraph(),
    weekly = weeklyEventsGraph(),
    hourly = hourlyApartmentsGraph();
  assert.equal(
    (daily.nodes[0].config?.schedule as { time: string }).time,
    "09:00",
  );
  const events = (
    weekly.nodes[1].config?.input as { requests: Record<string, unknown>[] }
  ).requests[0];
  assert.deepEqual(events.start_date, {
    $date: "next_week_start",
    format: "datetime",
  });
  const apartments = (
    hourly.nodes[1].config?.input as { requests: Record<string, unknown>[] }
  ).requests[0];
  assert.equal(apartments.max_price_eur, 1200);
  assert.equal(apartments.min_rooms, undefined);
  assert.equal(
    (hourly.nodes[2].config?.blocks as { only_new_results: boolean }[])[0]
      .only_new_results,
    true,
  );
  assert.equal(workflowIcon("Apartment search", "help-circle"), "house");
  assert(
    [...daily.nodes, ...weekly.nodes, ...hourly.nodes].every(
      (node) =>
        !["send_email_notification", "filter", "ai_action"].includes(node.type),
    ),
  );
});

// contract-test: supporting surface=gui.web assertions=workflows.control.typed-data,workflows-ui.mvp.authoring
test("nullable weather outputs remain typed comparisons", () => {
  assert.equal(
    normalizeSchema({ type: ["number", "null"] } as never).type,
    "number",
  );
  assert.equal(
    normalizeSchema({ anyOf: [{ type: "boolean" }, { type: "null" }] }).type,
    "boolean",
  );
});

// contract-test: supporting surface=gui.web assertions=workflows.activation.reachable-side-effect,workflows-ui.schedule.preview
test("manual execution accepts a complete unscheduled graph but activation requires a schedule", () => {
  const unscheduled: WorkflowGraph = {
    ...graph,
    trigger_node_id: null,
    nodes: graph.nodes.filter((node) => node.id !== "trigger"),
    edges: graph.edges.filter((edge) => edge.from !== "trigger"),
  };
  assert.equal(workflowGraphReady(unscheduled), true);
  assert.equal(
    workflowGraphReady(unscheduled, { requireSchedule: true }),
    false,
  );
  assert.equal(workflowGraphReady(graph), true);
  assert.equal(workflowGraphReady(graph, { requireSchedule: true }), true);
  const manualTrigger: WorkflowGraph = {
    ...graph,
    nodes: graph.nodes.map((node) =>
      node.id === "trigger" ? { ...node, type: "manual_trigger" } : node,
    ),
  };
  assert.equal(workflowGraphReady(manualTrigger), true);
  assert.equal(
    workflowGraphReady(manualTrigger, { requireSchedule: true }),
    false,
  );
});

// contract-test: supporting surface=gui.web assertions=workflows.activation.reachable-side-effect
test("manual execution rejects multiple disconnected starting nodes", () => {
  const disconnected: WorkflowGraph = {
    version: 2,
    trigger_node_id: null,
    nodes: [node("first", "send_chat_message"), node("second")],
    edges: [],
  };
  assert.equal(workflowGraphReady(disconnected), false);
  assert.equal(
    workflowGraphReady(disconnected, { requireSchedule: true }),
    false,
  );
});

// contract-test: supporting surface=gui.web assertions=workflows.activation.reachable-side-effect
test("neither manual execution nor activation accepts a draft without a reachable result", () => {
  for (const draft of [
    { version: 2, trigger_node_id: null, nodes: [], edges: [] },
    {
      ...graph,
      nodes: graph.nodes.filter((node) => node.id !== "message"),
      edges: graph.edges.filter((edge) => edge.to !== "message"),
    },
    { ...graph, edges: graph.edges.filter((edge) => edge.to !== "message") },
  ] satisfies WorkflowGraph[]) {
    assert.equal(workflowGraphReady(draft), false);
    assert.equal(workflowGraphReady(draft, { requireSchedule: true }), false);
  }
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.control.typed-data
test("app skill object defaults can be edited independently from reactive schema metadata", () => {
  const values = {
    location: "Berlin",
    dates: ["today"],
    options: { rain: true },
  };
  const reactiveDefault = new Proxy(values, {});
  assert.throws(() => structuredClone(reactiveDefault), {
    name: "DataCloneError",
  });
  const result = schemaDefault({
    type: "object",
    default: reactiveDefault,
  }) as typeof values;
  assert.deepEqual(result, values);
  result.dates.push("tomorrow");
  result.options.rain = false;
  assert.deepEqual(values, {
    location: "Berlin",
    dates: ["today"],
    options: { rain: true },
  });
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring,workflows.message.standard
test("choosing a new chat omits the destination in preview and saved JSON without changing message content", () => {
  const existing = { chat_id: "existing-chat", title: "Weather", message: "Take an umbrella.", blocks: [] };
  for (const destination of [undefined, null]) {
    const next = messageDestinationConfig(existing, destination);
    assert.deepEqual(JSON.parse(JSON.stringify(next)), { title: "Weather", message: "Take an umbrella.", blocks: [] });
    assert.equal(existing.chat_id, "existing-chat");
  }
  assert.equal(messageDestinationConfig(existing, "another-chat").chat_id, "another-chat");
});
