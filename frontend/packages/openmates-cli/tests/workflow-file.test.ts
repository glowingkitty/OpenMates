// contract-test: supporting surface=cli assertions=workflows.portability.definition-roundtrip,workflows.portability.private-content-boundary,workflows.portability.disabled-validated-import
import test from "node:test";
import assert from "node:assert/strict";
import { buildWorkflowFile, validateWorkflowFile, workflowFileName } from "../../workflowFile.ts";

// contract-test: supporting surface=cli assertions=workflows.portability.definition-roundtrip,workflows.portability.private-content-boundary
test("portable export keeps mapped inputs, graph data and references without source IDs", () => {
  const source = {
    id: "private-workflow", title: "Morning weather", description: "Berlin forecast", run_content_retention: "none" as const,
    source_chat_id: "private-source-chat", run_history: ["private-output"],
    graph: {
      version: 1, trigger_node_id: null,
      nodes: [
        { id: "private-step-a", type: "app_skill_action", config: { app_id: "weather", skill_id: "search", input: { location: "Berlin" } }, ui: { x: 2 } },
        { id: "private-step-b", type: "send_chat_message", config: { chat_id: "private-chat", message: "Weather: {{$nodes.private-step-a.results}}" }, input_mapping: { value: "$nodes.private-step-a.results" } },
      ],
      edges: [{ from: "private-step-a", to: "private-step-b", branch: "true" }],
      variables: { value: "$nodes.private-step-a.results" }, limits: { max_steps: 10 }, ui_layout: { "private-step-a": { x: 12 } },
    },
  };
  const exported = buildWorkflowFile(source);
  assert.equal(exported.format, "openmates-workflow");
  assert.equal(exported.workflow.run_content_retention, "none");
  assert.equal(exported.workflow.graph.nodes[1].config?.message, "Weather: {{$nodes.step_1.results}}");
  assert.equal(exported.workflow.graph.nodes[1].input_mapping?.value, "$nodes.step_1.results");
  assert.deepEqual(exported.workflow.graph.ui_layout, { step_1: { x: 12 } });
  assert.deepEqual(exported.workflow.graph.limits, { max_steps: 10 });
  assert.equal(exported.workflow.graph.nodes[1].config?.destination_required, true);
  assert.ok(exported.binding_requirements.some((item) => item.type === "chat_destination"));
  assert.doesNotMatch(JSON.stringify(exported), /private-/);
  assert.equal(source.graph.nodes[1].config.chat_id, "private-chat");
  assert.deepEqual(validateWorkflowFile(exported), exported);
});

// contract-test: supporting surface=cli assertions=workflows.portability.definition-roundtrip
test("node remapping preserves authored variable names", () => {
  const document = buildWorkflowFile({ title: "Field names", graph: {
    version: 2, trigger_node_id: null,
    nodes: [{ id: "message", type: "send_chat_message", config: { title: "Update", message: "Hello" } }],
    edges: [], variables: { message: "Authored field", token_count: 5, output_summary: "Authored summary" }, ui_layout: { message: { x: 4, message: "Authored layout key" } },
  } });
  assert.deepEqual(document.workflow.graph.variables, { message: "Authored field", token_count: 5, output_summary: "Authored summary" });
  assert.deepEqual(document.workflow.graph.ui_layout, { step_1: { x: 4, message: "Authored layout key" } });
});

// contract-test: supporting surface=cli assertions=workflows.portability.definition-roundtrip
test("manual and blank saved drafts are portable", () => {
  const result = buildWorkflowFile({ title: "Draft", graph: { version: 2, trigger_node_id: null, nodes: [], edges: [] } });
  assert.equal(result.workflow.graph.version, 2);
  assert.equal(result.workflow.graph.trigger_node_id, null);
  assert.deepEqual(result.binding_requirements, []);
});

// contract-test: supporting surface=cli assertions=workflows.portability.private-content-boundary,workflows.portability.disabled-validated-import
test("private structured credentials and unsupported documents are rejected", () => {
  const document = buildWorkflowFile({ title: "Draft", graph: { version: 1, trigger_node_id: null, nodes: [], edges: [] } });
  assert.throws(() => validateWorkflowFile({ ...document, format_version: 99 }), /version/);
  assert.throws(() => validateWorkflowFile({ ...document, workflow_id: "leak" }), /Unsupported/);
  for (const key of ["api_key", "weather_api_key", "customAccessToken", "provider_secret"]) {
    assert.throws(() => buildWorkflowFile({ title: "Private", graph: {
      version: 1, trigger_node_id: null,
      nodes: [{ id: "a", type: "app_skill_action", config: { app_id: "weather", skill_id: "search", input: { [key]: "secret-value" } } }], edges: [],
    } }), /private field/);
  }
});

// contract-test: supporting surface=cli assertions=workflows.portability.disabled-validated-import
test("broken references and circular authored data fail validation", () => {
  const document = buildWorkflowFile({ title: "Draft", graph: { version: 1, trigger_node_id: null, nodes: [], edges: [] } });
  document.workflow.graph.edges = [{ from: "missing", to: "missing" }];
  assert.throws(() => validateWorkflowFile(document), /missing step/);
  document.workflow.graph.edges = [];
  const loop: Record<string, unknown> = {};
  loop.self = loop;
  document.workflow.graph.variables = loop;
  assert.throws(() => validateWorkflowFile(document), /circular/);
});

// contract-test: supporting surface=cli assertions=workflows.portability.cli-commands
test("filenames keep the workflow suffix and cannot introduce directory traversal", () => {
  assert.equal(workflowFileName("../../Morning/Weather"), "-..-Morning-Weather.workflow.yml");
  assert.equal(workflowFileName("Morning.workflow.yml"), "Morning.workflow.yml");
  assert.equal(workflowFileName("..."), "workflow.workflow.yml");
});
