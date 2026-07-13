/**
 * CLI TUI unit contracts.
 *
 * These tests cover pure rendering and default-mode selection without opening a
 * real raw-mode terminal.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { defaultModeForStreams } from "../src/tui.ts";
import {
  createInitialTuiState,
  programmaticQuickstart,
  rankExamples,
  renderTuiFrame,
} from "../src/tuiRenderer.ts";

describe("CLI TUI defaults", () => {
  it("launches TUI only when stdin and stdout are interactive", () => {
    assert.equal(defaultModeForStreams({ isTTY: true } as NodeJS.ReadStream, { isTTY: true } as NodeJS.WriteStream), "tui");
    assert.equal(defaultModeForStreams({ isTTY: false } as NodeJS.ReadStream, { isTTY: true } as NodeJS.WriteStream), "quickstart");
    assert.equal(defaultModeForStreams({ isTTY: true } as NodeJS.ReadStream, { isTTY: false } as NodeJS.WriteStream), "quickstart");
  });

  it("prints programmatic quickstart commands for scripts", () => {
    const output = programmaticQuickstart();
    assert.match(output, /openmates chats new "Explain SQLite strict tables"/);
    assert.match(output, /openmates chats new "Review @\.\/src\/app\.ts"/);
    assert.match(output, /openmates embeds show <embed-id>/);
    assert.match(output, /openmates workflows list/);
    assert.match(output, /openmates --help/);
  });
});

describe("CLI TUI renderer", () => {
  it("renders the start screen with logo copy, examples, file hints, and input footer", () => {
    const state = createInitialTuiState();
    const frame = renderTuiFrame(state, 100, 28);
    assert.match(frame, /AI team mates\./);
    assert.match(frame, /For everyday tasks & learning\./);
    assert.match(frame, /With privacy & safety by design\./);
    assert.match(frame, /Check example chats via \/examples/);
    assert.match(frame, /@\.\/notes\.md/);
    assert.match(frame, /> Ask anything/);
  });

  it("top-anchors the start screen on short terminals so the logo is visible", () => {
    const state = createInitialTuiState();

    const frame = renderTuiFrame(state, 72, 14);

    assert.match(frame, /OPENMATES|AI team mates/);
  });

  it("renders example transcripts with the normal input footer", () => {
    const state = createInitialTuiState();
    state.screen = "example";
    state.activeExample = {
      chat: {
        id: "example-test",
        shortId: "example-test",
        slug: "example-test",
        title: "Example Test",
        summary: "A test example",
        updatedAt: null,
        category: "software_development",
        mateName: null,
        source: "example",
      },
      messages: [
        {
          id: "m1",
          chatId: "example-test",
          role: "user",
          content: "Build a small app",
          senderName: "User",
          category: null,
          modelName: null,
          createdAt: 1,
          embedIds: [],
        },
        {
          id: "m2",
          chatId: "example-test",
          role: "assistant",
          content: "Here is a compact plan.",
          senderName: null,
          category: "software_development",
          modelName: "test-model",
          createdAt: 2,
          embedIds: [],
        },
      ],
      followUpSuggestions: [],
    };

    const frame = renderTuiFrame(state, 88, 24);
    assert.match(frame, /Example chat: Example Test/);
    assert.match(frame, /Build a small app/);
    assert.match(frame, /Here is a compact plan/);
    assert.match(frame, /> Continue from this example/);
  });

  it("ranks matching examples before unrelated examples", () => {
    const ranked = rankExamples(
      [
        {
          id: "travel",
          shortId: "travel",
          slug: "flights-berlin-bangkok",
          title: "Flights from Berlin to Bangkok",
          summary: "Travel connection search",
          updatedAt: null,
          category: "travel",
          mateName: null,
          source: "example",
        },
        {
          id: "code",
          shortId: "code",
          slug: "svelte-runes-docs",
          title: "Svelte Runes Docs",
          summary: "Find Svelte 5 docs and explain component usage",
          updatedAt: null,
          category: "software_development",
          mateName: null,
          source: "example",
        },
      ],
      ["software development"],
    );

    assert.equal(ranked[0]?.id, "code");
  });

  it("keeps the selected example visible when navigating below the first page", () => {
    const state = createInitialTuiState();
    state.screen = "examples";
    state.selectedIndex = 15;
    state.examples = Array.from({ length: 25 }, (_, index) => ({
      id: `example-${index}`,
      shortId: `example-${index}`,
      slug: `example-${index}`,
      title: `Example ${index}`,
      summary: `Summary ${index}`,
      updatedAt: null,
      category: "test",
      mateName: null,
      source: "example" as const,
    }));

    const frame = renderTuiFrame(state, 80, 24);

    assert.match(frame, /> 16\. Example 15/);
  });

  it("renders workflow list and workflow run output summaries", () => {
    const state = createInitialTuiState();
    state.screen = "workflows";
    state.workflows = [
      {
        id: "wf-rain",
        title: "Daily rain check",
        status: "active",
        enabled: true,
        trigger_summary: "Manual",
        last_run_status: "completed",
        run_content_retention: "last_5",
        current_version_id: "v1",
        created_at: 1,
        updated_at: 2,
      },
    ];

    const listFrame = renderTuiFrame(state, 96, 24);

    assert.match(listFrame, /Workflows/);
    assert.match(listFrame, /> Daily rain check \(enabled\) last: completed/);
    assert.match(listFrame, /wf-rain/);
    assert.match(listFrame, /Enter open/);

    state.screen = "workflow";
    state.activeWorkflow = {
      ...(state.workflows[0] ?? {
        id: "wf-rain",
        title: "Daily rain check",
        status: "active" as const,
        enabled: true,
        current_version_id: "v1",
        created_at: 1,
        updated_at: 2,
      }),
      graph: {
        version: 1,
        trigger_node_id: "trigger",
        nodes: [
          { id: "trigger", type: "manual_trigger", title: "Manual start", config: {} },
          { id: "forecast", type: "app_skill_action", title: "Weather forecast", config: { app: "weather", skill: "forecast", input: { location: "Berlin" } } },
          { id: "notify", type: "send_notification", title: "Notify me", config: { title: "Rain check" } },
        ],
        edges: [],
      },
    };
    state.workflowRuns = [
      {
        id: "run-1",
        workflow_id: "wf-rain",
        version_id: "v1",
        trigger_type: "manual",
        status: "completed",
        started_at: 10,
        content_retention_mode: "last_5",
        content_available: true,
        content_storage: "durable",
        node_runs: [
          {
            id: "node-run-1",
            run_id: "run-1",
            workflow_id: "wf-rain",
            node_id: "forecast",
            node_type: "app_skill",
            status: "completed",
            output_summary: { provider: "DWD", rainy: "false" },
          },
        ],
      },
    ];

    const detailFrame = renderTuiFrame(state, 100, 28);

    assert.match(detailFrame, /Workflow: Daily rain check/);
    assert.match(detailFrame, /\[Graph\] {2}Runs/);
    assert.match(detailFrame, /> \[manual trigger\] Manual start/);
    assert.match(detailFrame, /\[app skill\] Weather forecast/);
    assert.match(detailFrame, /g graph {3}r runs/);

    state.workflowTab = "runs";
    state.selectedWorkflowNodeIndex = 1;

    const runsFrame = renderTuiFrame(state, 100, 32);

    assert.match(runsFrame, /Graph {2}\[Runs\]/);
    assert.match(runsFrame, /> run-1 {2}completed/);
    assert.match(runsFrame, /Run graph: run-1 \(completed\)/);
    assert.match(runsFrame, /> \[app skill\] Weather forecast \[completed\]/);
    assert.match(runsFrame, /output: provider=DWD, rainy=false/);
  });
});
