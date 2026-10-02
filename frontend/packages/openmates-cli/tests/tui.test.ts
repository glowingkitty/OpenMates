// contract-test-file: infrastructure
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
  renderMessageContent,
} from "../src/tuiRenderer.ts";
import { parseMessageSegments } from "../src/messageSegments.ts";

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
  it("renders embed references as compact cards while preserving ordinary JSON code", () => {
    const reference = '```json\n{"type":"app_skill_use","embed_id":"embed-one","app_id":"web","skill_id":"search","query":"Cargo planes"}\n```';
    const code = '```json\n{"a":true}\n```';
    const content = `Before\n${reference}\nAfter\n${code}`;
    const lines = renderMessageContent(content, 80).join("\n");
    assert.match(lines, /web\/search · Cargo planes/);
    assert.match(lines, /\/embed embed-one/);
    assert.match(lines, /Before/);
    assert.match(lines, /After/);
    assert.match(lines, /\{"a":true\}/);
    assert.doesNotMatch(lines, /app_skill_use|"embed_id"/);
    assert.equal(parseMessageSegments(content).find((segment) => segment.type === "embed")?.value, "embed-one");
    const resolved = renderMessageContent(reference, 80, new Map([["embed-one", {
      id:"embed-one",embedId:"embed-one",type:"app_skill_use",textPreview:null,content:{query:"Stored query",status:"finished"},appId:null,skillId:null,createdAt:null,
    }]])).join("\n");
    assert.match(resolved, /web\/search · Stored query/);
    assert.doesNotMatch(resolved, /app_skill_use|"embed_id"/);
  });

  it("defaults to the web workspace home with inspiration greeting and chat composer", () => {
    const state = createInitialTuiState();
    const frame = renderTuiFrame(state, 100, 40);
    assert.match(frame, /DAILY INSPIRATION/);
    assert.match(frame, /Hey there!/);
    assert.match(frame, /What do you need help with\?/);
    assert.match(frame, /> Ask anything/);
    assert.ok(frame.indexOf("DAILY INSPIRATION") < frame.indexOf("Hey there!"));
  });

  it("top-anchors inspiration on short terminals", () => {
    assert.match(renderTuiFrame(createInitialTuiState(), 72, 14), /DAILY INSPIRATION/);
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
    state.screen = "workflows"; state.workspace="workflows"; state.focus="content";
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
    assert.match(listFrame, /Daily rain check/);
    assert.match(listFrame, /Enabled/);
    assert.match(listFrame, /completed/);

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

    const detailFrame = renderTuiFrame(state, 100, 40);

    assert.match(detailFrame, /Workflow: Daily rain check/);
    assert.match(detailFrame, /Template · g/);
    assert.match(detailFrame, /> \[manual trigger\]/);
    assert.match(detailFrame, /Manual start/);
    assert.match(detailFrame, /\[app skill\]/);
    assert.match(detailFrame, /Weather forecast/);
    assert.match(detailFrame, /g template {3}r runs/);

    state.workflowTab = "runs";
    state.selectedWorkflowNodeIndex = 1;

    const runsFrame = renderTuiFrame(state, 100, 46);

    assert.match(runsFrame, /Runs · r/);
    assert.match(runsFrame, /> run-1 · completed/);
    assert.match(runsFrame, /Run run-1 · completed/);
    assert.match(runsFrame, /> \[app skill\]/);
    assert.match(runsFrame, /Weather forecast/);
    assert.match(runsFrame, /completed/);
    assert.match(runsFrame, /Output/);
    assert.match(runsFrame, /provider: DWD/);
    assert.match(runsFrame, /rainy: false/);
  });

  it("renders task workspace list and detail actions", () => {
    const state = createInitialTuiState();
    state.screen = "tasks"; state.workspace="tasks"; state.focus="content";
    state.tasks = [
      {
        taskId: "task-1",
        shortId: "OM-6",
        title: "Ship CLI tasks",
        description: "Cover terminal commands",
        tags: [],
        labels: [],
        priorityLevel: "none",
        blockedReason: "",
        readOnly: false,
        latestInstruction: "",
        status: "in_progress",
        assigneeType: "openmates",
        assigneeIdentity: "openmates",
        assigneeHash: null,
        primaryChatId: "chat-1",
        linkedProjectIds: [],
        planId: null,
        dueAt: null,
        priority: 0,
        position: 1,
        queueState: "active",
        blockedReasonCode: null,
        aiExecutionState: "running",
        version: 1,
        encrypted: {} as never,
      },
    ];

    const listFrame = renderTuiFrame(state, 96, 24);
    assert.match(listFrame, /Tasks/);
    assert.match(listFrame, /› Ship CLI tasks/);
    assert.match(listFrame, /OM-6/);
    assert.match(listFrame, /Enter open/);

    state.screen = "task";
    state.activeTask = state.tasks[0] ?? null;
    const detailFrame = renderTuiFrame(state, 96, 24);
    assert.match(detailFrame, /Ship CLI tasks/);
    assert.match(detailFrame, /OM-6.*In progress/);
    assert.match(detailFrame, /Cover terminal commands/);
    assert.match(detailFrame, /c create/);
    assert.match(detailFrame, /e edit/);
    assert.match(detailFrame, /x delete/);
    assert.match(detailFrame, /r reorder/);
    assert.match(detailFrame, /s start/);
    assert.match(detailFrame, /d done/);
    assert.match(detailFrame, /b block/);
    assert.match(detailFrame, /u unblock/);
    assert.match(detailFrame, /k skip/);
  });
});
