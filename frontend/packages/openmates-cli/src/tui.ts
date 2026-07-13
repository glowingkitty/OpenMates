/*
 * OpenMates CLI interactive terminal chat UI.
 *
 * Purpose: provide the default no-argument chat-first terminal experience.
 * Architecture: lightweight state machine over OpenMatesClient and pure render
 * helpers; no external TUI framework.
 * Security: signup leaves raw-mode UI before hidden prompts; file references use
 * existing chat command contracts outside this minimal v1 send path.
 * Tests: frontend/packages/openmates-cli/tests/tui.test.ts
 */

import { createInterface } from "node:readline/promises";
import { stdin as nodeStdin, stdout as nodeStdout } from "node:process";

import type { OpenMatesClient, WorkflowSummary } from "./client.js";
import type { StreamEvent } from "./ws.js";
import { getExampleChatConversation, listExampleChats } from "./exampleChats.js";
import { buildExampleContinuationHistory } from "./tuiExampleContinuation.js";
import { TuiTerminal, type TerminalKey } from "./tuiTerminal.js";
import {
  createInitialTuiState,
  programmaticQuickstart,
  rankExamples,
  renderTuiFrame,
  TUI_INTERESTS,
  type TuiState,
} from "./tuiRenderer.js";

export type CliDefaultMode = "tui" | "quickstart";
export type TuiResult = { action: "exit" | "signup" };

export function defaultModeForStreams(input: NodeJS.ReadStream, output: NodeJS.WriteStream): CliDefaultMode {
  return input.isTTY === true && output.isTTY === true ? "tui" : "quickstart";
}

export function printProgrammaticQuickstart(): void {
  process.stdout.write(programmaticQuickstart());
}

export async function runTui(
  client: OpenMatesClient,
  terminal = new TuiTerminal(),
): Promise<TuiResult> {
  const state = createInitialTuiState();
  hydrateExamples(state);
  let resolveResult: ((result: TuiResult) => void) | null = null;
  let renderTimer: NodeJS.Timeout | null = null;

  const render = () => {
    if (renderTimer) return;
    renderTimer = setTimeout(() => {
      renderTimer = null;
      terminal.render(renderTuiFrame(state, terminal.width, terminal.height));
    }, 16);
  };

  const finish = (result: TuiResult) => {
    if (renderTimer) clearTimeout(renderTimer);
    renderTimer = null;
    terminal.leave();
    resolveResult?.(result);
  };

  terminal.enter();
  terminal.onResize(render);
  terminal.onKey((chunk, key) => {
    void handleKey({ chunk, key, state, client, terminal, render, finish });
  });
  render();

  return new Promise<TuiResult>((resolve) => {
    resolveResult = resolve;
  });
}

async function handleKey(params: {
  chunk: string;
  key: TerminalKey;
  state: TuiState;
  client: OpenMatesClient;
  terminal: TuiTerminal;
  render: () => void;
  finish: (result: TuiResult) => void;
}): Promise<void> {
  const { chunk, key, state, client, terminal, render, finish } = params;
  if (key.ctrl && key.name === "c") {
    finish({ action: "exit" });
    return;
  }
  if (key.name === "escape") {
    state.screen = state.screen === "workflow" ? "workflows" : "start";
    state.input = "";
    render();
    return;
  }
  if (state.screen === "workflow" && !state.input && !key.ctrl && !key.meta) {
    if (chunk === "r") {
      await runActiveWorkflow({ state, client, render });
      return;
    }
    if (chunk === "u") {
      await refreshActiveWorkflowRuns({ state, client, render });
      return;
    }
    if (chunk === "c") {
      await cancelLatestWorkflowRun({ state, client, render });
      return;
    }
  }
  if (key.name === "up") {
    moveSelectionOrScroll(state, -1);
    render();
    return;
  }
  if (key.name === "down") {
    moveSelectionOrScroll(state, 1);
    render();
    return;
  }
  if (key.name === "pageup") {
    state.scrollOffset += 10;
    render();
    return;
  }
  if (key.name === "pagedown") {
    state.scrollOffset = Math.max(0, state.scrollOffset - 10);
    render();
    return;
  }
  if (key.name === "home") {
    state.scrollOffset = 10_000;
    render();
    return;
  }
  if (key.name === "end") {
    state.scrollOffset = 0;
    render();
    return;
  }
  if (key.name === "backspace") {
    state.input = state.input.slice(0, -1);
    render();
    return;
  }
  if (key.name === "space" && state.screen === "interests") {
    toggleInterest(state);
    render();
    return;
  }
  if (key.name === "return") {
    await handleEnter({ state, client, terminal, render, finish });
    return;
  }
  if (state.screen === "workflow" || state.screen === "workflows") {
    return;
  }
  if (!key.ctrl && !key.meta && chunk && chunk >= " ") {
    state.input += chunk;
    render();
  }
}

async function handleEnter(params: {
  state: TuiState;
  client: OpenMatesClient;
  terminal: TuiTerminal;
  render: () => void;
  finish: (result: TuiResult) => void;
}): Promise<void> {
  const { state, client, terminal, render, finish } = params;
  if (state.screen === "interests") {
    openExamples(state);
    render();
    return;
  }
  if (state.screen === "examples") {
    const selected = state.examples[state.selectedIndex];
    if (selected) openExample(state, selected.slug);
    render();
    return;
  }
  if (state.screen === "workflows") {
    const selected = state.workflows[state.selectedIndex];
    if (selected) await openWorkflowDetail({ state, client, workflow: selected, render });
    render();
    return;
  }

  const text = state.input.trim();
  if (!text) return;
  state.input = "";
  if (text.startsWith("/")) {
    await handleCommand({ command: text, state, client, terminal, render, finish });
    return;
  }
  await sendTuiMessage({ message: text, state, client, render });
}

async function handleCommand(params: {
  command: string;
  state: TuiState;
  client: OpenMatesClient;
  terminal: TuiTerminal;
  render: () => void;
  finish: (result: TuiResult) => void;
}): Promise<void> {
  const { command, state, client, terminal, render, finish } = params;
  const [name, arg] = command.split(/\s+/, 2);
  if (name === "/exit" || name === "/quit") {
    finish({ action: "exit" });
    return;
  }
  if (name === "/help") {
    state.screen = "help";
    render();
    return;
  }
  if (name === "/examples") {
    state.screen = state.selectedInterests.length > 0 ? "examples" : "interests";
    render();
    return;
  }
  if (name === "/workflows") {
    await openWorkflowList({ state, client, render });
    return;
  }
  if (name === "/workflow") {
    if (!arg) {
      await openWorkflowList({ state, client, render });
      return;
    }
    await openWorkflowById({ state, client, workflowId: arg, render });
    return;
  }
  if (name === "/signup") {
    finish({ action: "signup" });
    return;
  }
  if (name === "/login") {
    state.status = "Starting pair-auth login...";
    state.screen = "status";
    render();
    await terminal.suspend(async () => {
      await client.loginWithPairAuth();
      nodeStdout.write("Login successful. Press Enter to return to OpenMates.\n");
      const rl = createInterface({ input: nodeStdin, output: nodeStdout });
      try {
        await rl.question("");
      } finally {
        rl.close();
      }
    });
    state.status = "Login successful.";
    state.screen = "start";
    render();
    return;
  }
  if (name === "/embed") {
    state.screen = "status";
    state.status = arg
      ? `Full embed view for ${arg} is available with: openmates embeds show ${arg}`
      : "Visible embed list is not available in this v1 screen yet.";
    render();
    return;
  }
  if (name === "/clear") {
    state.messages = [];
    state.screen = "start";
    state.scrollOffset = 0;
    render();
    return;
  }
  state.status = `Unknown command: ${name}. Type /help.`;
  state.screen = "status";
  render();
}

async function sendTuiMessage(params: {
  message: string;
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { message, state, client, render } = params;
  const sourceExample = state.screen === "example" ? state.activeExample : null;
  state.screen = "chat";
  state.isBusy = true;
  state.messages.push({ role: "user", content: message });
  const assistantMessage = { role: "assistant" as const, content: "", title: "Sophia" };
  state.messages.push(assistantMessage);
  render();
  try {
    if (!client.hasSession()) {
      const result = await client.sendAnonymousMessage({
        message,
        messageHistory: sourceExample ? buildExampleContinuationHistory(sourceExample) : undefined,
      });
      assistantMessage.content = result.assistant;
    } else {
      const result = await client.sendMessage({
        message,
        messageHistory: sourceExample ? buildExampleContinuationHistory(sourceExample) : undefined,
        onStream: (event: StreamEvent) => {
          if (event.kind === "chunk" || event.kind === "done") {
            assistantMessage.content = event.content;
            render();
          }
        },
      });
      assistantMessage.content = result.assistant;
    }
    state.status = null;
  } catch (error) {
    assistantMessage.title = "Error";
    assistantMessage.content = error instanceof Error ? error.message : String(error);
  } finally {
    state.isBusy = false;
    render();
  }
}

function hydrateExamples(state: TuiState): void {
  state.examples = listExampleChats(20, 1).chats;
}

function openExamples(state: TuiState): void {
  state.examples = rankExamples(listExampleChats(50, 1).chats, state.selectedInterests);
  state.selectedIndex = 0;
  state.screen = "examples";
}

function openExample(state: TuiState, slug: string): void {
  const conversation = getExampleChatConversation(slug);
  if (!conversation) return;
  state.activeExample = conversation;
  state.screen = "example";
  state.input = "";
  state.scrollOffset = 0;
}

function moveSelectionOrScroll(state: TuiState, direction: number): void {
  if (state.screen === "interests") {
    state.selectedIndex = clamp(state.selectedIndex + direction, 0, TUI_INTERESTS.length - 1);
    return;
  }
  if (state.screen === "examples") {
    state.selectedIndex = clamp(state.selectedIndex + direction, 0, Math.max(0, state.examples.length - 1));
    return;
  }
  if (state.screen === "workflows") {
    state.selectedIndex = clamp(state.selectedIndex + direction, 0, Math.max(0, state.workflows.length - 1));
    return;
  }
  state.scrollOffset = Math.max(0, state.scrollOffset - direction);
}

async function openWorkflowList(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  state.screen = "status";
  state.status = "Loading workflows...";
  render();
  try {
    state.workflows = await client.listWorkflows();
    state.selectedIndex = 0;
    state.scrollOffset = 0;
    state.status = null;
    state.screen = "workflows";
  } catch (error) {
    state.status = workflowError(error, "Could not load workflows. Use /login first if you are not signed in.");
    state.screen = "status";
  }
  render();
}

async function openWorkflowById(params: {
  state: TuiState;
  client: OpenMatesClient;
  workflowId: string;
  render: () => void;
}): Promise<void> {
  const { state, client, workflowId, render } = params;
  state.screen = "status";
  state.status = `Loading workflow ${workflowId}...`;
  render();
  try {
    const workflow = await client.getWorkflow(workflowId);
    await openWorkflowDetail({ state, client, workflow, render });
  } catch (error) {
    state.status = workflowError(error, `Could not load workflow ${workflowId}.`);
    state.screen = "status";
    render();
  }
}

async function openWorkflowDetail(params: {
  state: TuiState;
  client: OpenMatesClient;
  workflow: WorkflowSummary;
  render: () => void;
}): Promise<void> {
  const { state, client, workflow, render } = params;
  state.activeWorkflow = workflow;
  state.workflowRuns = [];
  state.screen = "workflow";
  state.scrollOffset = 0;
  render();
  await refreshActiveWorkflowRuns({ state, client, render });
}

async function refreshActiveWorkflowRuns(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  const workflow = state.activeWorkflow;
  if (!workflow) return;
  state.status = "Refreshing workflow runs...";
  render();
  try {
    state.workflowRuns = await client.listWorkflowRuns(workflow.id);
    state.status = null;
    state.screen = "workflow";
  } catch (error) {
    state.status = workflowError(error, "Could not refresh workflow runs.");
  }
  render();
}

async function runActiveWorkflow(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  const workflow = state.activeWorkflow;
  if (!workflow) return;
  if (!workflow.enabled) {
    state.status = "Enable this workflow outside TUI before running it.";
    render();
    return;
  }
  state.status = "Starting workflow run...";
  render();
  try {
    const run = await client.runWorkflow(workflow.id, {
      idempotencyKey: `tui-${workflow.id}-${Date.now()}`,
      mode: "manual",
      input: {},
    });
    state.workflowRuns = [run, ...state.workflowRuns.filter((candidate) => candidate.id !== run.id)];
    state.status = `Started run ${run.id}. Press u to refresh.`;
  } catch (error) {
    state.status = workflowError(error, "Could not start workflow run.");
  }
  render();
}

async function cancelLatestWorkflowRun(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  const workflow = state.activeWorkflow;
  const run = state.workflowRuns.find((candidate) => ["queued", "running", "waiting"].includes(candidate.status));
  if (!workflow || !run) {
    state.status = "No active workflow run to cancel.";
    render();
    return;
  }
  state.status = `Cancelling run ${run.id}...`;
  render();
  try {
    const result = await client.cancelWorkflowRun(workflow.id, run.id);
    state.status = `Run ${result.run_id} ${result.status}.`;
    await refreshActiveWorkflowRuns({ state, client, render });
  } catch (error) {
    state.status = workflowError(error, "Could not cancel workflow run.");
    render();
  }
}

function workflowError(error: unknown, fallback: string): string {
  const details = error instanceof Error ? error.message : String(error);
  return `${fallback} ${details}`;
}

function toggleInterest(state: TuiState): void {
  const interest = TUI_INTERESTS[state.selectedIndex];
  if (!interest) return;
  if (state.selectedInterests.includes(interest)) {
    state.selectedInterests = state.selectedInterests.filter((candidate) => candidate !== interest);
  } else {
    state.selectedInterests = [...state.selectedInterests, interest];
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
