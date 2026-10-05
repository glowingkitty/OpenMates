import { claimPrivacyOffer } from "./privacyModel.js";
import { runPrivacyCommand } from "./privacyCommands.js";
/*
 * OpenMates CLI interactive terminal chat UI.
 *
 * Purpose: provide the default no-argument chat-first terminal experience.
 * Architecture: lightweight state machine over OpenMatesClient and pure render
 * helpers; no external TUI framework.
 * Security: auth leaves raw-mode UI; explicit file attachments use the shared
 * privacy, encryption, and upload contracts only when the user sends.
 * Tests: frontend/packages/openmates-cli/tests/tui.test.ts
 */

import { createInterface } from "node:readline/promises";
import { stdin as nodeStdin, stdout as nodeStdout } from "node:process";
import { randomUUID } from "node:crypto";

import type { OpenMatesClient, WorkflowDetail, WorkflowGraph, WorkflowRunDetail, WorkflowSummary } from "./client.js";
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
import { decryptUserTasks } from "./tasksCli.js";
import { handleWorkspaceKey, handleWorkspaceCommand, rememberDraft, route, type WorkspaceContext } from "./tuiWorkspaceController.js";
import { loadWorkflowRunGraph } from "./tuiWorkflowWorkspace.js";
import { prepareTuiMessage } from "./tuiAttachments.js";
import { loadHomeData } from "./tuiHome.js";
import { refreshTuiChatSidebar } from './tuiChatSidebar.js';
import { parseChatContextContent } from "./chatContextEvents.js";

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
  client.beginInteractiveViewerSession();
  state.signedIn = typeof client.hasSession === "function" && client.hasSession();
  hydrateExamples(state);
  let resolveResult: ((result: TuiResult) => void) | null = null;
  let renderTimer: NodeJS.Timeout | null = null;

  let closed = false;
  let stopActivity: (() => void) | undefined;
  let activityTimer: ReturnType<typeof setTimeout> | undefined;
  let refreshingActivity = false;
  const refreshActivity = async () => {
    if (closed || refreshingActivity || !state.signedIn) return;
    refreshingActivity = true;
    try { await refreshTuiChatSidebar(state, client, render); }
    finally { refreshingActivity = false; }
  };
  const activityPoll = setInterval(() => { void refreshActivity(); }, 30_000);
  const activityAnimation = setInterval(() => {
    if (!closed && state.runningChatIds.length) { state.activityFrame = (state.activityFrame + 1) % 4; render(); }
  }, 250);
  const render = () => {
    if (closed) return;
    if (state.screen !== "chat") client.clearInteractiveChatViewer();
    if (state.signedIn && typeof client.hasSession === "function" && !client.hasSession()) {
      Object.values(state.chatContextAuthoringControls).forEach(control => control.stop());
      Object.assign(state, createInitialTuiState(), {routeVersion: state.routeVersion + 1, homeLoadVersion:state.homeLoadVersion+1,status: "Session ended. Sign in to reopen your work."});
      hydrateExamples(state);
    }
    if (renderTimer) return;
    renderTimer = setTimeout(() => {
      renderTimer = null;
      terminal.render(renderTuiFrame(state, terminal.width, terminal.height, { colorMode: terminal.colorMode, ascii: terminal.ascii }));
    }, 16);
  };

  const finish = (result: TuiResult) => {
    closed = true;
    Object.values(state.chatContextAuthoringControls).forEach(control => control.stop());
    stopActivity?.(); clearTimeout(activityTimer); clearInterval(activityPoll); clearInterval(activityAnimation);
    client.endInteractiveViewerSession();
    if (renderTimer) clearTimeout(renderTimer);
    renderTimer = null;
    terminal.leave();
    resolveResult?.(result);
  };

  terminal.enter();
  terminal.onResize(render);
  terminal.onKey((chunk, key) => {
    void handleKey({ chunk, key, state, client, terminal, render, finish }).catch((error) => {
      state.status = error instanceof Error ? error.message : String(error);
      render();
    });
  });
  render();
  if (state.signedIn) void claimPrivacyOffer().then((show) => { if (!closed) { state.privacyOffer = show; render(); } }).catch(() => {});
  void loadHomeData(state,client,render);
  void refreshActivity();
  if (state.signedIn && typeof client.observeChatActivity === 'function') {
    void client.observeChatActivity(() => {
      clearTimeout(activityTimer); activityTimer = setTimeout(() => { void refreshActivity(); }, 300);
    }).then(stop => { if (closed) stop(); else stopActivity = stop; }).catch(() => { /* Polling still repairs activity state. */ });
  }

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
  if (state.privacyOffer && key.name === "f7") { state.privacyOffer = false; render(); return; }
  if (state.privacyOffer && key.name === "f6") {
    const draft = state.input, cursor = state.inputCursor;
    await handleCommand({ command: "/privacy install", state, client, terminal, render, finish });
    state.input = draft; state.inputCursor = cursor; rememberDraft(state); render(); return;
  }
  const context: WorkspaceContext = {
    state, client, terminal, render,
    command: (command) => handleCommand({command,state,client,terminal,render,finish}),
    send: (message) => sendTuiMessage({message,state,client,render}),
  };
  if (key.name === "escape") client.clearInteractiveChatViewer();
  if (await handleWorkspaceKey(context, chunk, key)) return;
  if (key.name === "escape") {
    if (state.workflowEdit) {
      state.workflowEdit = null;
      render();
      return;
    }
    state.screen = state.screen === "workflow" ? "workflows" : state.screen === "task" ? "tasks" : "start";
    state.input = "";
    render();
    return;
  }
  if (state.screen === "workflow" && state.workflowEdit) {
    if (key.name === "return") {
      await saveWorkflowNodeTitle({ state, client, render });
      return;
    }
    if (key.name === "backspace") {
      state.workflowEdit.value = state.workflowEdit.value.slice(0, -1);
      render();
      return;
    }
    if (!key.ctrl && !key.meta && chunk && chunk >= " ") {
      state.workflowEdit.value += chunk;
      render();
    }
    return;
  }
  if (state.screen === "workflow" && state.focus === "content" && !state.input && !key.ctrl && !key.meta) {
    if (chunk === "g") {
      state.workflowTab = "graph";
      state.selectedWorkflowNodeIndex = 0;
      render();
      return;
    }
    if (chunk === "r") {
      state.workflowTab = "runs";
      await loadSelectedWorkflowRunGraph({ state, client, render });
      return;
    }
    if (chunk === "x") {
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
    if (chunk === "e") {
      startWorkflowNodeEdit(state, "title");
      render();
      return;
    }
    if (chunk === "E") {
      startWorkflowNodeEdit(state, "config");
      render();
      return;
    }
  }
  if (key.name === "up") {
    await moveSelectionOrScroll({ state, client, render }, -1);
    render();
    return;
  }
  if (key.name === "down") {
    await moveSelectionOrScroll({ state, client, render }, 1);
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
    if (state.isBusy && state.workspace === "chats") return;
    await handleEnter({ state, client, terminal, render, finish });
    return;
  }
  if (state.screen === "workflow" || state.screen === "workflows" || state.screen === "tasks" || state.screen === "task") {
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
  if (state.input.startsWith("/")) {
    const command = state.input.trim(); state.input = ""; state.inputCursor = null;
    await handleCommand({command,state,client,terminal,render,finish}); return;
  }
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
    const selected = state.workflows.filter((w)=>w.title.toLowerCase().includes(state.filter.toLowerCase()))[state.selectedIndex];
    if (selected) await openWorkflowDetail({ state, client, workflow: selected, render });
    render();
    return;
  }
  if (state.screen === "workflow") {
    toggleSelectedWorkflowNode(state);
    render();
    return;
  }

  const text = state.input.trim();
  if (!text) return;
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
  client.clearInteractiveChatViewer();
  if (await handleWorkspaceCommand({state,client,terminal,render,command:(next)=>handleCommand({...params,command:next}),send:(message)=>sendTuiMessage({message,state,client,render})},command)) return;
  const [name, ...parts] = command.split(/\s+/);
  const arg = parts.join(" ");
  rememberDraft(state);
  state.input = ""; state.inputCursor = null;
  if (name === "/privacy") {
    const action = parts[0] ?? "status";
    if (action === "later") { state.privacyOffer = false; render(); return; }
    if (state.privacyInstalling) { state.status = "Offline model installation is already running."; render(); return; }
    const documents = parts[1] === "documents";
    const project = parts[1] === "project" ? parts[2] ?? state.selectedProjectId ?? undefined : undefined;
    if (parts[1] === "project" && !project) throw new Error("Open a Project first, or use /privacy enable project FULL_PROJECT_ID.");
    if (action === "remove" && parts[1] !== "confirm") { state.status = "Remove the offline model for all profiles? Use /privacy remove confirm to proceed."; render(); return; }
    const install = action === "install" || action === "update";
    state.privacyOffer = false; state.privacyInstalling = install;
    let lastProgress = 0;
    const operation = runPrivacyCommand(action, { yes: install || action === "remove" && parts[1] === "confirm", documents, project,
      progress: (done, total) => { if (Date.now() - lastProgress > 1000) { state.status = `Offline model download: ${Math.floor(done * 100 / total)}%`; lastProgress = Date.now(); render(); } },
    }).then((result) => { state.status = result; }).catch((error) => { state.status = error instanceof Error ? error.message : String(error); })
      .finally(() => { state.privacyInstalling = false; render(); });
    if (!install) await operation;
    render(); return;
  }
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
    route(state, "chats", "examples"); state.focus = "content";
    state.screen = state.selectedInterests.length > 0 ? "examples" : "interests";
    render();
    return;
  }
  if (name === "/workflows") {
    route(state, "workflows", "workflows");
    await openWorkflowList({ state, client, render });
    return;
  }
  if (name === "/tasks") {
    route(state, "tasks", "tasks");
    await openTaskList({ state, client, render });
    return;
  }
  if (name === "/workflow") {
    route(state, "workflows", "workflow");
    if (!arg) {
      await openWorkflowList({ state, client, render });
      return;
    }
    await openWorkflowById({ state, client, workflowId: arg, render });
    return;
  }
  if (name === "/example" && arg) {
    route(state, "chats", "example");
    state.selectedProjectId = null;
    openExample(state,arg); render(); return;
  }
  if (name === "/apps") {
    const request = route(state, "apps", "apps");
    const response = await client.listApps();
    if (request !== state.routeVersion) return;
    const value = response && typeof response === "object" && "apps" in response ? (response as {apps:unknown}).apps : response;
    const apps = Array.isArray(value) ? value : value && typeof value === "object" ? Object.values(value) : [];
    state.detailLines = apps.filter((app): app is Record<string, unknown> => !!app && typeof app === "object").map((app) => `${app.id ?? "App"} · ${typeof app.name === "string" ? app.name : app.id ?? ""}`);
    render(); return;
  }
  if (name === "/workflow-run") {await runActiveWorkflow({state,client,render});return;}
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
    Object.assign(state, createInitialTuiState(), {routeVersion:state.routeVersion+1,homeLoadVersion:state.homeLoadVersion+1, signedIn:client.hasSession(),status:"Login successful."});
    hydrateExamples(state);
    void claimPrivacyOffer().then((show) => { state.privacyOffer = show; render(); }).catch(() => {});
    void loadHomeData(state,client,render);
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
  if (state.isBusy) return;
  client.clearInteractiveChatViewer();
  state.isBusy = true;
  state.status = "Preparing message…"; render();
  const preparingRoute = state.routeVersion;
  let prepared: Awaited<ReturnType<typeof prepareTuiMessage>>;
  try {
    prepared = await prepareTuiMessage(client, message);
  } catch (error) {
    state.isBusy = false;
    if (preparingRoute === state.routeVersion) {
      state.input = message; state.inputCursor = null; rememberDraft(state);
      state.status = error instanceof Error ? error.message : String(error);
    }
    render(); return;
  }
  if (preparingRoute !== state.routeVersion) {state.isBusy = false; render(); return;}
  const sourceExample = state.screen === "example" ? state.activeExample : null;
  const history = sourceExample ? buildExampleContinuationHistory(sourceExample) : undefined;
  if (sourceExample) state.messages = sourceExample.messages.map((m) => ({role:m.role === "user" ? "user" : "assistant",content:m.content,title:m.senderName}));
  const messages = state.messages;
  const existingChatId = sourceExample ? null : state.activeChatId;
  const chatId = existingChatId ?? randomUUID();
  const draftKey = sourceExample ? `example:${sourceExample.chat.id}` : existingChatId ?? "new";
  state.drafts[draftKey] = ""; state.input = ""; state.inputCursor = null;
  const anonymousHistory = history ?? messages.filter((m) => m.role !== "system").map((m) => ({message_id:randomUUID(),role:m.role as "user"|"assistant",content:m.content,sender_name:m.title??(m.role==="user"?"User":"Assistant"),created_at:Math.floor(Date.now()/1000)}));
  state.activeChatId = chatId; state.headerState = existingChatId ? "ready" : "loading"; state.headerError = null;
  if (!existingChatId) state.activeChat = null;
  state.screen = "chat";
  state.aiTaskId = null;
  state.status = prepared.displayNames.length ? `Attached: ${prepared.displayNames.join(", ")}` : null;
  const userMessage = { role: "user" as const, content: prepared.message, embedIds: prepared.preparedEmbeds.map((embed) => embed.embedId) };
  state.messages.push(userMessage);
  const privacyCallbacks = {
    onPrivacyPrepared: (safe: string) => { userMessage.content = safe; render(); },
    onPrivacyProgress: (done: number, total: number) => { if (state.messages === messages) { state.status = `Offline personal-data scan: ${Math.floor(done * 100 / total)}%`; render(); } },
  };
  const assistantMessage = { role: "assistant" as const, content: "", title: "Sophia" };
  state.messages.push(assistantMessage);
  render();
  try {
    if (!client.hasSession()) {
      const result = await client.sendAnonymousMessage({
        message: prepared.message,
        ...privacyCallbacks,
        messageHistory: anonymousHistory,
      });
      assistantMessage.content = result.assistant;
      if (state.messages === messages) {
        state.activeChatId = result.chatId;
        state.activeChat = {id:result.chatId,shortId:result.chatId.slice(0,8),title:null,summary:null,updatedAt:null,createdAt:Math.floor(Date.now()/1000),category:result.category,mateName:result.mateName};
        state.followUpSuggestions = result.followUpSuggestions ?? [];
        if (result.mateName) assistantMessage.title = result.mateName;
      }
    } else {
      const result = await client.sendMessage({
        message: prepared.message,
        interactiveHuman: true,
        ...privacyCallbacks,
        piiMappings: prepared.piiMappings,
        chatId: existingChatId ?? undefined,
        newChatId: existingChatId ? undefined : chatId,
        projectId: state.selectedProjectId ?? undefined,
        preparedEmbeds: prepared.preparedEmbeds,
        messageHistory: history,
        onProjectFocusPending: (countdown) => {
          if (state.messages === messages) { state.projectFocusPending = countdown; render(); }
        },
        onChatContextApplied: (event) => {
          if (state.messages !== messages || messages.some(message => message.id === event.event_id
              || (message.role === "system" && parseChatContextContent(message.content)?.event_id === event.event_id))) return;
          messages.push({ id: event.event_id, role: "system", content: JSON.stringify(event) });
          render();
        },
        onStream: (event: StreamEvent) => {
          if (state.messages === messages && event.taskId) state.aiTaskId = event.taskId;
          if (event.kind === "chunk" || event.kind === "done") {
            assistantMessage.content = event.content;
            if (state.messages === messages && event.category) state.activeChat = {id:chatId,shortId:chatId.slice(0,8),title:state.activeChat?.title??null,summary:state.activeChat?.summary??null,updatedAt:null,createdAt:state.activeChat?.createdAt??Math.floor(Date.now()/1000),category:event.category,mateName:null};
            render();
          }
        },
      });
      assistantMessage.content = result.assistant;
      if (state.messages === messages) {
        state.activeChatId = result.chatId; state.followUpSuggestions = result.followUpSuggestions ?? [];
        if (state.screen === "chat") await client.setInteractiveChatViewer(result.chatId);
        if (result.mateName) assistantMessage.title = result.mateName;
        if (typeof client.getChatMetadata === "function") {
          try { const metadata = await client.getChatMetadata(result.chatId); if (state.messages === messages) state.activeChat = metadata; } catch { /* Saved messages remain usable while metadata catches up. */ }
        }
      }
    }
    if (state.messages === messages) {state.status = null;state.headerState="ready";}
  } catch (error) {
    assistantMessage.title = "Error";
    assistantMessage.content = error instanceof Error ? error.message : String(error);
    if (state.messages === messages) {state.headerState="error";state.headerError=/credit/i.test(assistantMessage.content)?"Not enough credits":assistantMessage.content;}
  } finally {
    state.isBusy = false;
    state.projectFocusPending = null;
    state.aiTaskId = null;
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
  state.focus = "composer";
  const conversation = getExampleChatConversation(slug);
  if (!conversation) return;
  state.activeExample = conversation;
  state.screen = "example";
  state.input = state.drafts[`example:${conversation.chat.id}`] ?? "";
  state.scrollOffset = 0;
}

async function moveSelectionOrScroll(params: { state: TuiState; client: OpenMatesClient; render: () => void }, direction: number): Promise<void> {
  const { state, client, render } = params;
  if (state.screen === "interests") {
    state.selectedIndex = clamp(state.selectedIndex + direction, 0, TUI_INTERESTS.length - 1);
    return;
  }
  if (state.screen === "examples") {
    state.selectedIndex = clamp(state.selectedIndex + direction, 0, Math.max(0, state.examples.length - 1));
    return;
  }
  if (state.screen === "workflows") {
    state.selectedIndex = clamp(state.selectedIndex + direction, 0, Math.max(0, state.workflows.filter((w)=>w.title.toLowerCase().includes(state.filter.toLowerCase())).length - 1));
    return;
  }
  if (state.screen === "tasks") {
    state.selectedIndex = clamp(state.selectedIndex + direction, 0, Math.max(0, state.tasks.length - 1));
    return;
  }
  if (state.screen === "workflow") {
    if (state.workflowTab === "runs") {
      state.selectedWorkflowRunIndex = clamp(state.selectedWorkflowRunIndex + direction, 0, Math.max(0, state.workflowRuns.length - 1));
      await loadSelectedWorkflowRunGraph({ state, client, render });
      return;
    }
    const nodeCount = state.activeWorkflow?.graph.nodes.length ?? 0;
    state.selectedWorkflowNodeIndex = clamp(state.selectedWorkflowNodeIndex + direction, 0, Math.max(0, nodeCount - 1));
    return;
  }
  state.scrollOffset = Math.max(0, state.scrollOffset + direction * (state.screen === "chat" ? -1 : 1));
}

function toggleSelectedWorkflowNode(state: TuiState): void {
  const workflow = state.activeWorkflow;
  if (!workflow) return;
  const run = state.workflowRuns[state.selectedWorkflowRunIndex];
  const graph = state.workflowTab === "runs"
    ? state.workflowRunGraph ?? (run?.version_id === workflow.current_version_id ? workflow.graph : null)
    : workflow.graph;
  const node = graph?.nodes[state.selectedWorkflowNodeIndex];
  if (!node) return;
  if (state.workflowTab === "runs") {
    state.expandedWorkflowRunNodeId = state.expandedWorkflowRunNodeId === node.id ? null : node.id;
  } else {
    state.expandedWorkflowNodeId = state.expandedWorkflowNodeId === node.id ? null : node.id;
  }
}

function firstRunNodeIndex(graph: WorkflowGraph, run: WorkflowRunDetail): number {
  const firstNodeRun = run?.node_runs?.[0];
  if (!firstNodeRun) return 0;
  return Math.max(0, graph.nodes.findIndex((node) => node.id === firstNodeRun.node_id));
}

const workflowRunGraphRequests = new WeakMap<TuiState, number>();
async function loadSelectedWorkflowRunGraph(params: { state: TuiState; client: OpenMatesClient; render: () => void }): Promise<void> {
  const { state, client, render } = params;
  const workflow = state.activeWorkflow;
  const run = state.workflowRuns[state.selectedWorkflowRunIndex];
  const routeVersion = state.routeVersion;
  const request = (workflowRunGraphRequests.get(state) ?? 0) + 1;
  workflowRunGraphRequests.set(state, request);
  state.workflowRunGraph = null;
  state.expandedWorkflowRunNodeId = null;
  state.selectedWorkflowNodeIndex = 0;
  render();
  if (!workflow || !run) return;
  const current = () => state.screen === "workflow" && state.routeVersion === routeVersion
    && state.activeWorkflow?.id === workflow.id
    && state.workflowRuns[state.selectedWorkflowRunIndex]?.id === run.id
    && workflowRunGraphRequests.get(state) === request;
  try {
    const graph = await loadWorkflowRunGraph(client, workflow, run);
    if (!current()) return;
    state.workflowRunGraph = graph;
    state.selectedWorkflowNodeIndex = firstRunNodeIndex(graph, run);
    state.status = null;
  } catch (error) {
    if (!current()) return;
    state.status = workflowError(error, `Could not load recorded graph for run ${run.id}.`);
  }
  render();
}

async function openTaskList(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  state.focus = "content"; state.filter = ""; state.taskContext = null;
  state.screen = "status";
  state.status = "Loading tasks...";
  render();
  try {
    state.tasks = await decryptUserTasks(await client.listUserTasks(), client.getMasterKeyBytes());
    state.selectedIndex = 0;
    state.scrollOffset = 0;
    state.activeTask = null;
    state.status = null;
    state.screen = "tasks";
  } catch (error) {
    state.status = workflowError(error, "Could not load tasks. Use /login first if you are not signed in.");
    state.screen = "status";
  }
  render();
}

const workflowOpenRequests = new WeakMap<TuiState, number>();
function nextWorkflowOpenRequest(state: TuiState): number {
  const request = (workflowOpenRequests.get(state) ?? 0) + 1;
  workflowOpenRequests.set(state, request);
  return request;
}

async function openWorkflowList(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  state.focus = "content"; state.filter = "";
  state.screen = "status";
  state.status = "Loading workflows...";
  const routeVersion = state.routeVersion;
  const request = nextWorkflowOpenRequest(state);
  const current = () => state.routeVersion === routeVersion && state.screen === "status" && workflowOpenRequests.get(state) === request;
  render();
  try {
    const workflows = await client.listWorkflows();
    if (!current()) return;
    state.workflows = workflows;
    state.selectedIndex = 0;
    state.scrollOffset = 0;
    state.status = null;
    state.screen = "workflows";
  } catch (error) {
    if (!current()) return;
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
  const routeVersion = state.routeVersion;
  const request = nextWorkflowOpenRequest(state);
  const current = () => state.routeVersion === routeVersion && state.screen === "status" && workflowOpenRequests.get(state) === request;
  render();
  try {
    const workflow = await client.getWorkflow(workflowId);
    if (!current()) return;
    await openWorkflowDetail({ state, client, workflow, render });
  } catch (error) {
    if (!current()) return;
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
  const routeVersion = state.routeVersion;
  const request = nextWorkflowOpenRequest(state);
  state.screen = "status";
  const current = () => state.routeVersion === routeVersion && state.screen === "status" && workflowOpenRequests.get(state) === request;
  state.status = `Loading workflow ${workflow.id}...`;
  render();
  let detail: WorkflowDetail;
  try {
    detail = await client.getWorkflow(workflow.id);
  } catch (error) {
    if (!current()) return;
    state.status = workflowError(error, `Could not load workflow ${workflow.id}.`);
    state.screen = "status";
    render();
    return;
  }
  if (!current()) return;
  state.activeWorkflow = detail;
  state.workflowRuns = [];
  state.workflowRunGraph = null;
  state.workflowTab = "graph";
  state.selectedWorkflowNodeIndex = 0;
  state.selectedWorkflowRunIndex = 0;
  state.expandedWorkflowNodeId = null;
  state.expandedWorkflowRunNodeId = null;
  state.workflowEdit = null;
  state.screen = "workflow";
  state.scrollOffset = 0;
  state.status = null;
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
  const routeVersion = state.routeVersion;
  const current = () => state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id;
  state.status = "Refreshing workflow runs...";
  render();
  try {
    const runs = await client.listWorkflowRuns(workflow.id);
    if (!current()) return;
    const selectedRunId = state.workflowRuns[state.selectedWorkflowRunIndex]?.id;
    state.workflowRuns = runs;
    const selectedIndex = selectedRunId ? runs.findIndex((run) => run.id === selectedRunId) : -1;
    if (selectedIndex >= 0) state.selectedWorkflowRunIndex = selectedIndex;
    state.selectedWorkflowRunIndex = clamp(state.selectedWorkflowRunIndex, 0, Math.max(0, state.workflowRuns.length - 1));
    state.status = null;
    if (state.workflowTab === "runs") await loadSelectedWorkflowRunGraph({ state, client, render });
  } catch (error) {
    if (!current()) return;
    state.status = workflowError(error, "Could not refresh workflow runs.");
  }
  render();
}

async function saveWorkflowNodeTitle(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  const workflow = state.activeWorkflow;
  const edit = state.workflowEdit;
  if (!workflow || !edit) return;
  const routeVersion = state.routeVersion;
  const current = () => state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id && state.workflowEdit === edit;
  let parsedConfig: Record<string, unknown> | null = null;
  if (edit.field === "config") {
    try {
      const parsed = JSON.parse(edit.value || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Config must be a JSON object");
      parsedConfig = parsed as Record<string, unknown>;
    } catch (error) {
      state.status = workflowError(error, "Invalid config JSON.");
      render();
      return;
    }
  }
  const graph = {
    ...workflow.graph,
    nodes: workflow.graph.nodes.map((node) => {
      if (node.id !== edit.nodeId) return node;
      if (edit.field === "config") return { ...node, config: parsedConfig ?? {} };
      return { ...node, title: edit.value.trim() || null };
    }),
  };
  state.status = `Saving node ${edit.field}...`;
  render();
  try {
    const updated = await client.updateWorkflow(workflow.id, { graph });
    if (!current()) return;
    state.activeWorkflow = updated;
    state.workflowEdit = null;
    state.status = `Saved node ${edit.field}.`;
  } catch (error) {
    if (!current()) return;
    state.status = workflowError(error, "Could not save node title.");
  }
  render();
}

function startWorkflowNodeEdit(state: TuiState, field: "title" | "config"): void {
  const workflow = state.activeWorkflow;
  if (!workflow || state.workflowTab !== "graph") {
    state.status = "Switch to the Graph tab before editing node details.";
    return;
  }
  const node = workflow.graph.nodes[state.selectedWorkflowNodeIndex];
  if (!node) return;
  state.workflowEdit = {
    nodeId: node.id,
    field,
    value: field === "config" ? JSON.stringify(node.config ?? {}) : node.title ?? "",
  };
  state.expandedWorkflowNodeId = node.id;
  state.status = `Editing ${field} for ${node.id}.`;
}

async function runActiveWorkflow(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  const workflow = state.activeWorkflow;
  if (!workflow) return;
  const routeVersion = state.routeVersion;
  const current = () => state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id;
  if (!workflow.enabled) {
    state.status = "This workflow is disabled. Press t to enable it before running.";
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
    if (!current()) return;
    state.workflowRuns = [run, ...state.workflowRuns.filter((candidate) => candidate.id !== run.id)];
    state.selectedWorkflowRunIndex = 0;
    if (state.workflowTab === "runs") await loadSelectedWorkflowRunGraph({ state, client, render });
    if (!current()) return;
    state.status = `Started run ${run.id}. Press u to refresh.`;
  } catch (error) {
    if (!current()) return;
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
  const routeVersion = state.routeVersion;
  const current = () => state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id;
  state.status = `Cancelling run ${run.id}...`;
  render();
  try {
    const result = await client.cancelWorkflowRun(workflow.id, run.id);
    if (!current()) return;
    state.status = `Run ${result.run_id} ${result.status}.`;
    await refreshActiveWorkflowRuns({ state, client, render });
  } catch (error) {
    if (!current()) return;
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
