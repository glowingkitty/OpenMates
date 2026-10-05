/**
 * CLI TUI Workflow interaction tests.
 *
 * Purpose: drive the real TUI key handler with a fake terminal and fake client so
 * Workflow workspace usability is covered without flaky raw-mode PTY automation.
 * Security: uses synthetic workflow IDs and no network, API keys, or local files.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { WorkflowGraph } from "../src/client.js";

import { runTui as runProductTui } from "../src/tui.ts";
import { noStartupPrompts } from "./tuiTestServices.js";
const runTui = (client: Parameters<typeof runProductTui>[0], terminal: Parameters<typeof runProductTui>[1]) =>
  runProductTui(client, terminal, noStartupPrompts);

function workflowSummary() {
  return {
    id: "wf-rain",
    title: "Daily rain check",
    status: "active" as const,
    enabled: true,
    trigger_summary: "Manual",
    last_run_status: "completed" as const,
    run_content_retention: "last_5" as const,
    current_version_id: "v1",
    created_at: 1,
    updated_at: 2,
  };
}

function workflowDetail() {
  return {
    ...workflowSummary(),
    graph: {
      version: 1,
      trigger_node_id: "trigger",
      nodes: [
        { id: "trigger", type: "manual_trigger" as const, title: "Manual start", config: {} },
        { id: "forecast", type: "app_skill_action" as const, title: "Weather forecast", config: { app: "weather", skill: "forecast", input: { location: "Berlin" } } },
        { id: "notify", type: "send_notification" as const, title: "Notify me", config: { title: "Rain check" } },
      ],
      edges: [],
    },
  };
}

function workflowRun(status: "running" | "completed" = "completed") {
  return {
    id: status === "running" ? "run-active" : "run-1",
    workflow_id: "wf-rain",
    version_id: "v1",
    trigger_type: "manual",
    status,
    started_at: 10,
    content_retention_mode: "last_5" as const,
    content_available: true,
    content_storage: "durable" as const,
    node_runs: [
      {
        id: "node-run-1",
        run_id: "run-1",
        workflow_id: "wf-rain",
        node_id: "forecast",
        node_type: "app_skill_action" as const,
        status: "completed" as const,
        output_summary: { provider: "DWD", rainy: "false" },
      },
    ],
  };
}

class FakeTerminal {
  width = 100;
  height = 32;
  frames: string[] = [];
  keyHandler: ((chunk: string, key: Record<string, unknown>) => void) | null = null;

  enter(): void {}
  leave(): void {}
  onResize(): void {}
  render(frame: string): void { this.frames.push(frame); }
  onKey(handler: (chunk: string, key: Record<string, unknown>) => void): void { this.keyHandler = handler; }
  async suspend<T>(run: () => Promise<T>): Promise<T> { return run(); }

  press(chunk: string, key: Record<string, unknown> = {}): void {
    this.keyHandler?.(chunk, key);
  }

  latestFrame(): string {
    return this.frames.at(-1) ?? "";
  }
}

class FakeClient {
  runs = [workflowRun("completed")];
  runStarted = false;
  cancelRequested = false;
  updatePayload: unknown = null;

  hasSession(): boolean { return true; }
  beginInteractiveViewerSession(): void {}
  endInteractiveViewerSession(): void {}
  clearInteractiveChatViewer(): void {}
  async setInteractiveChatViewer(_id: string): Promise<void> {}
  async listWorkflows() { return [workflowSummary()]; }
  async getWorkflow() { return workflowDetail(); }
  async listWorkflowRuns() { return this.runs; }
  async runWorkflow() {
    this.runStarted = true;
    const run = workflowRun("running");
    this.runs = [run, ...this.runs];
    return run;
  }
  async cancelWorkflowRun() {
    this.cancelRequested = true;
    return { run_id: "run-active", status: "cancellation_requested" as const };
  }
  async updateWorkflow(_workflowId: string, payload: unknown) {
    this.updatePayload = payload;
    return workflowDetail();
  }
}

async function tick(ms = 30): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

describe("CLI TUI Workflow interaction", () => {
  // contract-test: direct surface=cli assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
  it("opens workflows, switches tabs, runs, cancels, expands, and edits node details", async () => {
    const terminal = new FakeTerminal();
    const client = new FakeClient();
    const tui = runTui(client as never, terminal as never);
    await tick();

    for (const char of "/workflows") terminal.press(char, { name: char });
    terminal.press("\r", { name: "return" });
    await tick();
    assert.match(terminal.latestFrame(), /Workflows/);
    assert.match(terminal.latestFrame(), /Daily rain check/);

    terminal.press("\r", { name: "return" });
    await tick();
    assert.match(terminal.latestFrame(), /Template · g/);
    assert.match(terminal.latestFrame(), /Weather forecast/);

    terminal.press("r", { name: "r" });
    await tick();
    assert.match(terminal.latestFrame(), /Runs · r/);
    assert.match(terminal.latestFrame(), /Run run-1 · completed/);
    assert.match(terminal.latestFrame(), /provider: DWD/);

    terminal.press("g", { name: "g" });
    terminal.press("\r", { name: "return" });
    await tick();
    assert.match(terminal.latestFrame(), /id: trigger/);

    terminal.press("x", { name: "x" });
    await tick();
    assert.equal(client.runStarted, true);
    assert.match(terminal.latestFrame(), /Started run run-active/);

    terminal.press("c", { name: "c" });
    await tick();
    assert.equal(client.cancelRequested, true);

    terminal.press("e", { name: "e" });
    await tick();
    assert.match(terminal.latestFrame(), /Editing title/);
    for (const char of "Updated title") terminal.press(char, { name: char });
    terminal.press("\r", { name: "return" });
    await tick();
    assert.match(JSON.stringify(client.updatePayload), /Updated title/);

    terminal.press("\u0003", { ctrl: true, name: "c" });
    const result = await tui;
    assert.equal(result.action, "exit");
  });

  // contract-test: direct surface=cli assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
  it("keeps run selection pinned to each recorded graph version", async () => {
    const terminal = new FakeTerminal();
    const client = new FakeClient();
    const current = { ...workflowDetail(), current_version_id: "v2", graph: { ...workflowDetail().graph, nodes: [{ id: "current", type: "manual_trigger" as const, title: "Current trigger" }], edges: [] } };
    const old = { version: 1, trigger_node_id: "old", nodes: [{ id: "old", type: "manual_trigger" as const, title: "Historical trigger" }], edges: [] };
    const oldRun = { ...workflowRun(), id: "run-old", version_id: "v1", node_runs: [{ ...workflowRun().node_runs[0], node_id: "old" }] };
    const currentRun = { ...workflowRun(), id: "run-current", version_id: "v2", node_runs: [{ ...workflowRun().node_runs[0], node_id: "current" }] };
    client.runs = [oldRun, currentRun];
    client.getWorkflow = async () => current as never;
    const versions: string[] = [];
    (client as FakeClient & { getWorkflowVersion: (id: string, version: string) => Promise<{ graph: typeof old }> }).getWorkflowVersion = async (_id, version) => {
      versions.push(version); return { graph: old };
    };
    const tui = runTui(client as never, terminal as never);
    await tick();
    for (const char of "/workflows") terminal.press(char, { name: char });
    terminal.press("\r", { name: "return" }); await tick();
    terminal.press("\r", { name: "return" }); await tick();
    terminal.press("r", { name: "r" }); await tick();
    assert.match(terminal.latestFrame(), /Historical trigger/);
    assert.doesNotMatch(terminal.latestFrame(), /Current trigger/);
    terminal.press("", { name: "down" }); await tick();
    assert.match(terminal.latestFrame(), /Current trigger/);
    assert.doesNotMatch(terminal.latestFrame(), /Historical trigger/);
    terminal.press("", { name: "up" }); await tick();
    assert.match(terminal.latestFrame(), /Historical trigger/);
    assert.deepEqual(versions, ["v1", "v1"]);
    terminal.press("\u0003", { ctrl: true, name: "c" });
    await tui;
  });

  // contract-test: direct surface=cli assertions=workflows.execution.lifecycle-visible,cli.surface.semantic-parity
  it("ignores a historical graph response after leaving the workspace", async () => {
    const terminal = new FakeTerminal();
    const client = new FakeClient();
    client.getWorkflow = async () => ({ ...workflowDetail(), current_version_id: "v2" });
    client.runs = [{ ...workflowRun(), version_id: "v1" }];
    let resolveVersion: ((value: { graph: WorkflowGraph }) => void) | undefined;
    (client as FakeClient & { getWorkflowVersion: () => Promise<unknown> }).getWorkflowVersion = () => new Promise((resolve) => { resolveVersion = resolve as typeof resolveVersion; });
    const tui = runTui(client as never, terminal as never);
    await tick();
    for (const char of "/workflows") terminal.press(char, { name: char });
    terminal.press("\r", { name: "return" }); await tick();
    terminal.press("\r", { name: "return" }); await tick();
    terminal.press("r", { name: "r" }); await tick();
    assert.match(terminal.latestFrame(), /Run graph unavailable/);
    terminal.press("\u000e", { ctrl: true, name: "n" }); await tick();
    resolveVersion?.({ graph: workflowDetail().graph }); await tick();
    assert.doesNotMatch(terminal.latestFrame(), /Run run-1/);
    terminal.press("\u0003", { ctrl: true, name: "c" });
    await tui;
  });

  // contract-test: direct surface=cli assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
  it("shows an unavailable historical graph without substituting the current template", async () => {
    const terminal = new FakeTerminal();
    const client = new FakeClient();
    client.getWorkflow = async () => ({ ...workflowDetail(), current_version_id: "v2" });
    client.runs = [{ ...workflowRun(), version_id: "v1" }];
    (client as FakeClient & { getWorkflowVersion: () => Promise<never> }).getWorkflowVersion = async () => { throw new Error("version expired"); };
    const tui = runTui(client as never, terminal as never);
    await tick();
    for (const char of "/workflows") terminal.press(char, { name: char });
    terminal.press("\r", { name: "return" }); await tick();
    terminal.press("\r", { name: "return" }); await tick();
    terminal.press("r", { name: "r" }); await tick();
    assert.match(terminal.latestFrame(), /Run graph unavailable/);
    assert.match(terminal.latestFrame(), /Could not load recorded graph/);
    assert.doesNotMatch(terminal.latestFrame(), /Weather forecast/);
    terminal.press("\u0003", { ctrl: true, name: "c" });
    await tui;
  });
});
