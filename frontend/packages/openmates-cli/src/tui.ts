import { claimPrivacyOffer } from "./privacyModel.js";
import { runPrivacyCommand } from "./privacyCommands.js";
import { createTuiStartup, type TuiStartupServices } from "./tuiStartup.js";
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

import { shouldWaitForTeamAi, type OpenMatesClient, type WorkflowGraph, type WorkflowRunDetail } from "./client.js";
import type { StreamEvent } from "./ws.js";
import { getExampleChatConversation, listExampleChats } from "./exampleChats.js";
import { buildExampleContinuationHistory } from "./tuiExampleContinuation.js";
import { TuiTerminal, type TerminalKey } from "./tuiTerminal.js";
import {
  createInitialTuiState,
  programmaticQuickstart,
  rankExamples,
  renderTuiStreamingAnimationFrame,
  renderTuiFrame,
  resetEndedTuiSession,
  TUI_INTERESTS,
  TUI_SESSION_ENDED_STATUS,
  type TuiMessage,
  type TuiState,
} from "./tuiRenderer.js";
import { loadTuiTaskList } from "./tuiTaskList.js";
import { handleWorkspaceKey, handleWorkspaceCommand, rememberDraft, route, type WorkspaceContext } from "./tuiWorkspaceController.js";
import { loadWorkflowRunGraph, orderedWorkflowNodes } from "./tuiWorkflowWorkspace.js";
import { loadTuiProjects } from "./tuiProjectsWorkspace.js";
import { captureTuiWorkspaceOwner, invalidateCachedTuiWorkspace, loadCachedTuiWorkspace, writeCachedTuiWorkspace } from "./tuiCachedWorkspaces.js";
import { prepareTuiMessage } from "./tuiAttachments.js";
import { loadHomeData, startHomeSync } from "./tuiHome.js";
import { refreshTuiChatSidebar } from './tuiChatSidebar.js';
import { parseChatContextContent } from "./chatContextEvents.js";
import { tuiComposerCursor } from './tuiLayout.js';
import {pointerTargetAt} from './tuiPointer.js';
import {handleTuiPointer} from './tuiPointerActions.js';
import { registerChatEmbedAliases, hydrateChatEmbedPreviews } from './tuiEmbeds.js';
import {createChatModelPreferences} from './chatModelPreferences.js';
import {createTuiModelSelectorShell,isTuiAiComposer,type TuiModelSelectorShell} from './tuiModelSelectorShell.js';
import {createTuiTeamChatRefresh,loadTuiTeamIdentity,reconcileTuiTeamSenderLabels} from './tuiTeamChat.js';

export type CliDefaultMode = "tui" | "quickstart";
export type TuiResult = { action: "exit" | "signup" | "restart" };

export function defaultModeForStreams(input: NodeJS.ReadStream, output: NodeJS.WriteStream): CliDefaultMode {
  return input.isTTY === true && output.isTTY === true ? "tui" : "quickstart";
}

export function printProgrammaticQuickstart(): void {
  process.stdout.write(programmaticQuickstart());
}

export async function runTui(
  client: OpenMatesClient,
  terminal = new TuiTerminal(),
  startupServices?: TuiStartupServices,
): Promise<TuiResult> {
  const state = createInitialTuiState();
  client.beginInteractiveViewerSession();
  state.signedIn = typeof client.hasSession === "function" && client.hasSession();
  hydrateExamples(state);
  let resolveResult: ((result: TuiResult) => void) | null = null;
  let renderTimer: NodeJS.Timeout | null = null;
  let lastFrameOwner: (() => boolean) | null = null;

  let closed = false;
  let stopActivity: (() => void) | undefined;
  let activityTimer: ReturnType<typeof setTimeout> | undefined;
  let refreshingActivity = false;
  let identityScope = '';
  let identityEpoch = 0;
  let identityRetryTimer: ReturnType<typeof setTimeout> | null = null;
  let workspaceScope: string | null = null;
  const scopedDrafts = new Map<string, Record<string,string>>();
  let teamChatRefresh: ReturnType<typeof createTuiTeamChatRefresh> | null = null;
  let modelShell:TuiModelSelectorShell|null=null;
  const modelPreferences=createChatModelPreferences(client);
  const refreshActivity = async () => {
    if (closed || state.startup || refreshingActivity || !state.signedIn) return;
    refreshingActivity = true;
    teamChatRefresh?.request();
    try { await refreshTuiChatSidebar(state, client, render); }
    catch {
      // Polling is fire-and-forget. Keep the TUI alive on a transient failure;
      // render() fences private views if the session ended during the request.
      if (!closed && client.hasSession() && !state.status) {
        state.status = 'Running chat status unavailable.';
        render();
      }
    } finally {
      refreshingActivity = false;
      if (!closed && !client.hasSession()) render();
    }
  };
  const activityPoll = setInterval(() => { void refreshActivity(); }, 30_000);
  const activityAnimation = setInterval(() => {
    if (closed) return;
    const sidebarActivity = state.runningChatIds.length > 0;
    if (sidebarActivity) state.activityFrame = (state.activityFrame + 1) % 4;
    const streaming = state.screen === 'chat' && state.isAwaitingAi && state.streamingMessage && !state.textSelection
      && !terminal.reducedMotion && !terminal.isOutputBlocked && lastFrameOwner?.();
    if (streaming) {
      state.streamingPhase = (state.streamingPhase + 1) % 12;
    }
    if (sidebarActivity) { render(); return; }
    if (streaming && !renderTimer) {
      const frame = renderTuiStreamingAnimationFrame(state,terminal.width,terminal.height,
        {colorMode:terminal.colorMode,ascii:terminal.ascii,reducedMotion:terminal.reducedMotion});
      if (frame) terminal.render(frame,tuiComposerCursor(state,terminal.width,terminal.height),state.textSelection);
    }
  }, 250);
  const syncSessionView = () => {
    if (typeof client.hasSession === "function" && resetEndedTuiSession(state, client.hasSession())) {
      client.clearInteractiveChatViewer();
      hydrateExamples(state);
    }
  };
  const render = () => {
    if (closed) return;
    syncSessionView();
    const teamId = state.signedIn ? client.getActiveTeamId?.() ?? null : null;
    const session = state.signedIn && typeof client.getSession === 'function' ? client.getSession() : null;
    const nextScope = session ? JSON.stringify([session.apiUrl,session.hashedEmail,session.createdAt,session.masterKeyExportedB64,teamId]) : null;
    if (workspaceScope !== null && nextScope !== workspaceScope) {
      const endedStatus = !session && state.status===TUI_SESSION_ENDED_STATUS ? TUI_SESSION_ENDED_STATUS : null;
      identityEpoch++;
      identityScope='';
      if (identityRetryTimer) clearTimeout(identityRetryTimer);
      identityRetryTimer=null;
      if (session) {rememberDraft(state);scopedDrafts.set(workspaceScope,{...state.drafts});}
      else scopedDrafts.clear();
      state.homeAbortController?.abort();
      Object.values(state.chatContextAuthoringControls).forEach(control => control.stop());
      client.clearInteractiveChatViewer();
      const routeVersion=state.routeVersion+1,homeLoadVersion=state.homeLoadVersion+1;
      Object.assign(state,createInitialTuiState(),{signedIn:!!session,activeTeamId:teamId,
        drafts:nextScope?{...(scopedDrafts.get(nextScope)??{})}:{},routeVersion,homeLoadVersion,status:endedStatus});
      state.input=state.drafts.new??'';
      // The private-scope reset must not erase the public offline examples.
      if (!session) hydrateExamples(state);
      if (session) queueMicrotask(() => {
        if (closed || workspaceScope!==nextScope) return;
        void loadHomeData(state,client,render);
        void refreshTuiChatSidebar(state,client,render,true).catch(()=>{});
      });
    }
    workspaceScope=nextScope;
    state.activeTeamId = teamId;
    if (teamId && state.signedIn && nextScope) {
      if (nextScope !== identityScope) {
        identityScope=nextScope;
        const epoch=++identityEpoch;
        const loadIdentity=(attempt:number) => {
          void loadTuiTeamIdentity(state,client,render,()=>!closed && identityEpoch===epoch && workspaceScope===nextScope).then(result=>{
            if (!result || closed || identityEpoch!==epoch || workspaceScope!==nextScope) return;
            if ((!result.profileLoaded || !result.teamLoaded) && attempt<2) {
              identityRetryTimer=setTimeout(()=>{identityRetryTimer=null;loadIdentity(attempt+1);},attempt===0?1000:4000);
            }
          });
        };
        loadIdentity(0);
      }
    } else {
      identityScope='';
      identityEpoch++;
      if (identityRetryTimer) clearTimeout(identityRetryTimer);
      identityRetryTimer=null;
    }
    modelShell?.sync();
    if (state.screen !== "chat") client.clearInteractiveChatViewer();
    if (renderTimer) return;
    renderTimer = setTimeout(() => {
      renderTimer = null;
      if (closed) return;
      syncSessionView();
      lastFrameOwner = client.hasSession() ? captureTuiWorkspaceOwner(client) : () => !client.hasSession();
      terminal.render(renderTuiFrame(state, terminal.width, terminal.height, { colorMode: terminal.colorMode, ascii: terminal.ascii,reducedMotion:terminal.reducedMotion }),tuiComposerCursor(state,terminal.width,terminal.height),state.textSelection);
    }, 16);
  };

  teamChatRefresh=createTuiTeamChatRefresh(state,client,render);
  modelShell=createTuiModelSelectorShell({state,client,preferences:modelPreferences,render});

  const stopHomeSync=startHomeSync(state,client,render,()=>closed);

  const finish = (result: TuiResult) => {
    closed = true;
    state.homeAbortController?.abort();
    Object.values(state.chatContextAuthoringControls).forEach(control => control.stop());
    stopHomeSync();stopActivity?.(); teamChatRefresh?.dispose(); clearTimeout(activityTimer); clearInterval(activityPoll); clearInterval(activityAnimation);
    if (identityRetryTimer) clearTimeout(identityRetryTimer);
    modelShell?.dispose();
    client.endInteractiveViewerSession();
    if (renderTimer) clearTimeout(renderTimer);
    renderTimer = null;
    terminal.leave();
    resolveResult?.(result);
  };

  const result = new Promise<TuiResult>((resolve) => { resolveResult = resolve; });
  const startup = createTuiStartup({ state, render, closed: () => closed, services: startupServices,
    updated: () => finish({ action: "restart" }),
    ready: () => {
      void loadHomeData(state, client, render);
      void refreshActivity();
      warmTuiWorkspaceLists(client);
      if (state.signedIn && typeof client.observeChatActivity === 'function') {
        void client.observeChatActivity(() => {
          teamChatRefresh?.request();
          clearTimeout(activityTimer); activityTimer = setTimeout(() => { void refreshActivity(); }, 300);
        }).then(stop => { if (closed) stop(); else stopActivity = stop; }).catch(() => { /* Polling still repairs activity state. */ });
      }
    },
  });
  terminal.enter();
  terminal.onResize(render);
  terminal.onKey((chunk, key) => {
    if (key.ctrl && key.name === "c") { finish({ action: "exit" }); return; }
    void (async () => {
      if(key.name==='mouseclick'){await handleKey({chunk,key,state,client,terminal,render,finish,modelShell:modelShell!});return;}
      if (await startup.handleKey(chunk, key)) return;
      await handleKey({ chunk, key, state, client, terminal, render, finish, modelShell:modelShell! });
    })().catch((error) => {
      state.status = error instanceof Error ? error.message : String(error);
      render();
    });
  });
  void startup.start();
  return result;
}

async function handleKey(params: {
  chunk: string;
  key: TerminalKey;
  state: TuiState;
  client: OpenMatesClient;
  terminal: TuiTerminal;
  render: () => void;
  finish: (result: TuiResult) => void;
  modelShell?:TuiModelSelectorShell;
}): Promise<void> {
  const { chunk, key, state, client, terminal, render, finish, modelShell } = params;
  if (key.ctrl && key.name === "c") {
    finish({ action: "exit" });
    return;
  }
  if (state.privacyOffer && key.name === "f7") { state.privacyOffer = false; render(); return; }
  if (state.privacyOffer && key.name === "f6") {
    const draft = state.input, cursor = state.inputCursor;
    await handleCommand({ command: "/privacy install", state, client, terminal, render, finish, modelShell });
    state.input = draft; state.inputCursor = cursor; rememberDraft(state); render(); return;
  }
  const context: WorkspaceContext = {
    state, client, terminal, render,
    command: (command) => handleCommand({command,state,client,terminal,render,finish,modelShell}),
    send: (message, options) => sendTuiMessage({message,state,client,render,modelShell,questionAnswer:options?.questionAnswer}),
    modelShell,
  };
  if(key.name==='mouseclick'){
    if(!key.mouse||key.ctrl||key.meta||key.shift)return;
    const action=pointerTargetAt(state,key.mouse.column,key.mouse.row,terminal.width,terminal.height);
    if(action)await handleTuiPointer(context,action,(text,pressed)=>handleKey({...params,chunk:text,key:pressed}));
    else if(state.modelSelector?.open){await modelShell?.action('close');}
    return;
  }
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
    if (state.isBusy && state.workspace === "chats" && !state.input.startsWith('/')) return;
    await handleEnter({ state, client, terminal, render, finish, modelShell });
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
  modelShell?:TuiModelSelectorShell;
}): Promise<void> {
  const { state, client, terminal, render, finish, modelShell } = params;
  if (state.input.startsWith("/")) {
    const command = state.input.trim(); state.input = ""; state.inputCursor = null;
    await handleCommand({command,state,client,terminal,render,finish,modelShell}); return;
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
    if (selected) await openWorkflowDetail({ state, client, workflowId: selected.id, render });
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
    await handleCommand({ command: text, state, client, terminal, render, finish, modelShell });
    return;
  }
  await sendTuiMessage({ message: text, state, client, render, modelShell });
}

async function handleCommand(params: {
  command: string;
  state: TuiState;
  client: OpenMatesClient;
  terminal: TuiTerminal;
  render: () => void;
  finish: (result: TuiResult) => void;
  modelShell?:TuiModelSelectorShell;
}): Promise<void> {
  const { command, state, client, terminal, render, finish, modelShell } = params;
  if(command.split(/\s+/,1)[0]!=="/thinking")client.clearInteractiveChatViewer();
  if (await handleWorkspaceCommand({state,client,terminal,render,command:(next)=>handleCommand({...params,command:next}),send:(message,options)=>sendTuiMessage({message,state,client,render,modelShell,questionAnswer:options?.questionAnswer}),modelShell},command)) return;
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
    warmTuiWorkspaceLists(client);
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

export async function sendTuiMessage(params: {
  questionAnswer?:boolean;
  message: string;
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
  modelShell?:TuiModelSelectorShell;
}): Promise<void> {
  const { state, client, render } = params;
  if (state.isBusy) return;
  const initialMessage = params.message.trim();
  if (!initialMessage) return;
  const preparingOwner = client.hasSession()
    ? captureTuiWorkspaceOwner(client)
    : () => !client.hasSession();
  const preparingRoute = state.routeVersion;
  const previousMessages = state.messages;
  const preparingChatId = state.activeChatId;
  const previousActiveChat = state.activeChat, previousHeaderState = state.headerState;
  const previousScreen = state.screen;
  const sourceExample = previousScreen === "example" ? state.activeExample : null;
  const history = sourceExample ? buildExampleContinuationHistory(sourceExample) : undefined;
  const draftKey = sourceExample ? `example:${sourceExample.chat.id}` : preparingChatId ?? "new";
  const draftBeforeSend = state.drafts[draftKey];
  if (sourceExample) state.messages = sourceExample.messages.map((m) => ({role:m.role === "user" ? "user" : "assistant",content:m.content,title:m.senderName}));
  const messages = state.messages;
  const userMessage: TuiMessage = { id: randomUUID(), role: "user", content: initialMessage };
  messages.push(userMessage);
  state.screen = "chat";
  state.isBusy = true;
  state.drafts[draftKey] = "";
  state.input = ""; state.inputCursor = null;
  state.status = "Preparing message…";
  render();
  const ownsPreparation = () => preparingOwner() && state.routeVersion === preparingRoute
    && state.messages === messages && state.activeChatId === preparingChatId;
  const restorePreparation = (status: string | null) => {
    if (!ownsPreparation()) return;
    const index = messages.indexOf(userMessage);
    if (index >= 0) messages.splice(index, 1);
    state.messages = previousMessages;
    state.screen = previousScreen;
    state.isBusy = false;
    if (state.input === "" && state.drafts[draftKey] === "") {
      state.input = initialMessage; state.inputCursor = null;
      if (draftBeforeSend === undefined) delete state.drafts[draftKey];
      rememberDraft(state);
    }
    if (client.getActiveTeamId?.()) reconcileTuiTeamSenderLabels(state);
    state.status = status;
    render();
  };
  let resolved: {message:string;blocked:boolean};
  try {
    resolved = !params.questionAnswer && params.modelShell
      ? await params.modelShell.consumeMention(params.message, true) : { message: params.message, blocked: false };
  } catch (error) {
    restorePreparation(error instanceof Error ? error.message : String(error));
    return;
  }
  if (!ownsPreparation()) return;
  if (resolved.blocked) { restorePreparation(null); return; }
  const message = resolved.message.trim();
  if (!message) { restorePreparation(null); return; }
  userMessage.content = message;
  client.clearInteractiveChatViewer();
  state.status = "Preparing message…"; render();
  if (!ownsPreparation()) return;
  let prepared: Awaited<ReturnType<typeof prepareTuiMessage>>;
  try {
    prepared = params.questionAnswer ? {message,preparedEmbeds:[],displayNames:[]} : await prepareTuiMessage(client, message);
  } catch (error) {
    restorePreparation(error instanceof Error ? error.message : String(error));
    return;
  }
  if (!ownsPreparation()) return;
  const sendTeamId=client.getActiveTeamId?.() ?? null;
  const waitForAi = !client.hasSession() || shouldWaitForTeamAi(prepared.message, sendTeamId);
  const modelSelection = waitForAi && !params.questionAnswer && isTuiAiComposer(state) && client.hasSession()
    ? params.modelShell?.selectionForSend() ?? null : 'auto';
  if (modelSelection === null) {
    restorePreparation('Model selection is loading. Retry or choose Auto before sending.');
    return;
  }
  const separator = modelSelection.indexOf('/');
  const modelDirective = separator > 0 ? `@ai-model:${modelSelection.slice(separator+1)}:${modelSelection.slice(0,separator)} ` : '';
  const existingChatId = sourceExample ? null : state.activeChatId;
  const chatId = existingChatId ?? randomUUID();
  let ownedMessages = messages, ownedChatId: string | null = chatId;
  const ownsSend = () => preparingOwner() && state.routeVersion === preparingRoute
    && state.messages === ownedMessages && state.activeChatId === ownedChatId;
  // The composer was cleared when the optimistic row first appeared. Keep any
  // newer draft the user entered while preparation was still in progress.
  const anonymousHistory = history ?? messages.filter((m) => m !== userMessage && m.role !== "system").map((m) => ({message_id:randomUUID(),role:m.role as "user"|"assistant",content:m.content,sender_name:m.title??(m.role==="user"?"User":"Assistant"),created_at:Math.floor(Date.now()/1000)}));
  state.activeChatId = chatId; state.headerState = existingChatId ? "ready" : "loading"; state.headerError = null;
  if(!existingChatId && waitForAi)params.modelShell?.adoptNewChat(chatId);
  if (!existingChatId) state.activeChat = null;
  state.screen = "chat";
  state.aiTaskId = null;
  state.status = prepared.displayNames.length ? `Attached: ${prepared.displayNames.join(", ")}` : null;
  userMessage.content = prepared.message;
  userMessage.embedIds = prepared.preparedEmbeds.map((embed) => embed.embedId);
  const privacyCallbacks = {
    onPrivacyPrepared: (safe: string) => { if (ownsSend()) { userMessage.content = safe.replace(/^@ai-model:[^\s]+\s*/,""); render(); } },
    onPrivacyProgress: (done: number, total: number) => { if (ownsSend()) { state.status = `Offline personal-data scan: ${Math.floor(done * 100 / total)}%`; render(); } },
  };
  const assistantMessage: TuiMessage | null = waitForAi
    ? { id: randomUUID(), role: "assistant", content: "", title: "Assistant" } : null;
  state.streamingMessage = assistantMessage;
  if (assistantMessage) state.streamingPhase = 0;
  state.isAwaitingAi = waitForAi;
  const showAssistant = (content: string) => {
    if (!assistantMessage || !ownsSend() || !content) return;
    assistantMessage.content = content;
    if (!messages.includes(assistantMessage)) messages.push(assistantMessage);
  };
  render();
  let questionSendError: Error | null = null;
  let accepted = false;
  try {
    if (!client.hasSession()) {
      const result = await client.sendAnonymousMessage({
        message: prepared.message,
        ...privacyCallbacks,
        messageHistory: anonymousHistory,
      });
      accepted = true;
      showAssistant(result.assistant);
      if (ownsSend()) {
        ownedChatId = result.chatId; state.activeChatId = result.chatId;
        state.activeChat = {id:result.chatId,shortId:result.chatId.slice(0,8),title:null,summary:null,updatedAt:null,createdAt:Math.floor(Date.now()/1000),category:result.category,mateName:result.mateName};
        state.followUpSuggestions = result.followUpSuggestions ?? [];
        if (result.mateName && assistantMessage) assistantMessage.title = result.mateName;
      }
    } else {
      const result = await client.sendMessage({
        message: modelDirective && !/@(?:ai-model|best-model):/.test(prepared.message) ? modelDirective+prepared.message : prepared.message,
        interactiveHuman: true,
        ...privacyCallbacks,
        piiMappings: prepared.piiMappings,
        chatId: existingChatId ?? undefined,
        newChatId: existingChatId ? undefined : chatId,
        projectId: state.selectedProjectId ?? undefined,
        preparedEmbeds: prepared.preparedEmbeds,
        messageHistory: history,
        onProjectFocusPending: (countdown) => {
          if (ownsSend()) { state.projectFocusPending = countdown; render(); }
        },
        onChatContextApplied: (event) => {
          if (!ownsSend() || messages.some(message => message.id === event.event_id
              || (message.role === "system" && parseChatContextContent(message.content)?.event_id === event.event_id))) return;
          messages.push({ id: event.event_id, role: "system", content: JSON.stringify(event) });
          render();
        },
        onStream: (event: StreamEvent) => {
          if (!ownsSend()) return;
          if (event.taskId) state.aiTaskId = event.taskId;
          if(assistantMessage&&event.thinkingContent!==undefined)assistantMessage.thinkingContent=event.thinkingContent;
          if(assistantMessage&&event.thinkingActive!==undefined)assistantMessage.thinkingActive=event.thinkingActive;
          if (assistantMessage && event.modelName) assistantMessage.modelName = event.modelName;
          if (assistantMessage && event.category) {
            state.activeChat = {id:chatId,shortId:chatId.slice(0,8),title:state.activeChat?.title??null,
              summary:state.activeChat?.summary??null,updatedAt:null,
              createdAt:state.activeChat?.createdAt??Math.floor(Date.now()/1000),category:event.category,mateName:null};
          }
          if (assistantMessage && (event.kind === "chunk" || event.kind === "done")) {
            showAssistant(event.content);
          }
          render();
        },
      });
      accepted = true;
      showAssistant(result.assistant);
      if (ownsSend()) {
        ownedChatId = result.chatId; state.activeChatId = result.chatId; state.followUpSuggestions = result.followUpSuggestions ?? [];
        if (result.userMessageId) userMessage.id = result.userMessageId;
        if (!existingChatId && params.modelShell) {
          void Promise.resolve().then(() => ownsSend()
            ? params.modelShell?.persistCreatedChat(result.chatId,modelSelection) : undefined).catch(() => {});
        }
        // A completed reply must release send controls even if viewer sync is offline.
        if (state.screen === "chat" && typeof client.setInteractiveChatViewer === "function") {
          void Promise.resolve().then(() => ownsSend() && state.screen === "chat"
            ? client.setInteractiveChatViewer(result.chatId) : undefined).catch(() => {});
        }
        if (result.mateName && assistantMessage) assistantMessage.title = result.mateName;
        if (typeof client.getChatMetadata === "function") {
          const completedLength = messages.length;
          const ownsMetadata = () => ownsSend() && state.activeChatId === result.chatId && messages.length === completedLength;
          void (async () => {
            try {
              const metadata = await client.getChatMetadata(result.chatId);
              if (ownsMetadata()) state.activeChat = metadata;
            } catch { /* Saved messages remain usable while metadata catches up. */ }
            finally { if (ownsMetadata()) { state.headerState = "ready"; render(); } }
          })();
        }
      }
    }
    if (ownsSend()) {state.status = null;state.headerState="ready";}
  } catch (error) {
    // Server acceptance is irreversible; optional local follow-up failure
    // must never turn the acknowledged message back into a retry draft.
    if (accepted) return;
    if (params.questionAnswer) {
      questionSendError = error instanceof Error ? error : new Error(String(error));
      if (ownsSend()) {
        for (const optimistic of [userMessage, assistantMessage].filter((item): item is NonNullable<typeof item> => item !== null)) {
          const index = messages.indexOf(optimistic); if (index >= 0) messages.splice(index, 1);
        }
        state.messages = previousMessages; state.activeChatId = existingChatId; state.activeChat = previousActiveChat;
        ownedMessages = previousMessages; ownedChatId = existingChatId;
        state.headerState = previousHeaderState; state.screen = sourceExample ? "example" : "chat"; state.status = null;
      }
    } else if (assistantMessage && ownsSend()) {
      assistantMessage.title = "Error";
      showAssistant(error instanceof Error ? error.message : String(error));
      state.headerState="error";state.headerError=/credit/i.test(assistantMessage.content)?"Not enough credits":assistantMessage.content;
    } else if (ownsSend()) {
      const index = messages.indexOf(userMessage);
      if (index >= 0) messages.splice(index, 1);
      state.messages = previousMessages; state.activeChatId = existingChatId; state.activeChat = previousActiveChat;
      ownedMessages = previousMessages; ownedChatId = existingChatId;
      state.headerState = previousHeaderState; state.screen = previousScreen;
      if (state.input === "" && state.drafts[draftKey] === "") {
        state.input = message; state.inputCursor = null; rememberDraft(state);
      }
      state.status = error instanceof Error ? error.message : String(error);
    }
  } finally {
    if (ownsSend()) {
      state.isBusy = false;
      if (sendTeamId) reconcileTuiTeamSenderLabels(state);
      state.isAwaitingAi = false;
      state.streamingMessage = null;
      state.projectFocusPending = null;
      state.aiTaskId = null;
      registerChatEmbedAliases(state);
      if(state.screen==='chat'&&typeof client.getEmbed==='function')void hydrateChatEmbedPreviews(state,client,render);
      render();
    }
  }
  if (questionSendError) throw questionSendError;
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
  state.chatEmbeds={};state.embedAliases={};state.chatEmbedLoads=new Set();
  state.resultsViewModes={};state.activeResultsView=null;state.resultsViewOrigin=null;
  state.screen = "example";
  registerChatEmbedAliases(state);
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
  const node = graph ? orderedWorkflowNodes(graph)[state.selectedWorkflowNodeIndex] : null;
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
  return Math.max(0, orderedWorkflowNodes(graph).findIndex((node) => node.id === firstNodeRun.node_id));
}

const tasksListCacheKey = "tasks:list";
const workflowsListCacheKey = "workflows:list";
const workflowDetailCacheKey = (id: string) => `workflow:${id}:detail`;
const workflowRunsCacheKey = (id: string) => `workflow:${id}:runs`;
const workflowVersionCacheKey = (id: string, version: string) => `workflow:${id}:version:${version}`;

function warmTuiWorkspaceLists(client: OpenMatesClient): void {
  // Fake clients and unauthenticated startup never access a personal disk cache.
  if (typeof client.getSession !== "function" || !client.hasSession()) return;
  void Promise.allSettled([
    loadCachedTuiWorkspace(client, "projects:list", () => loadTuiProjects(client), () => {}),
    loadTuiTaskList(client, tasksListCacheKey, {}, () => {}),
    loadCachedTuiWorkspace(client, workflowsListCacheKey, () => client.listWorkflows(), () => {}),
  ]);
}

const workflowRunGraphRequests = new WeakMap<TuiState, number>();
async function loadSelectedWorkflowRunGraph(params: { state: TuiState; client: OpenMatesClient; render: () => void; ownerCurrent?: () => boolean }): Promise<void> {
  const { state, client, render, ownerCurrent } = params;
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
  const current = () => (!ownerCurrent || ownerCurrent()) && state.screen === "workflow" && state.routeVersion === routeVersion
    && state.activeWorkflow?.id === workflow.id
    && state.workflowRuns[state.selectedWorkflowRunIndex]?.id === run.id
    && workflowRunGraphRequests.get(state) === request;
  await loadCachedTuiWorkspace(client, workflowVersionCacheKey(workflow.id, run.version_id ?? "unknown"),
    () => loadWorkflowRunGraph(client, workflow, run), (graph, source) => {
    if (!current()) return;
    const selectedNodeId = source === "sync" && state.workflowRunGraph
      ? orderedWorkflowNodes(state.workflowRunGraph)[state.selectedWorkflowNodeIndex]?.id : null;
    state.workflowRunGraph = graph;
    const selectedIndex = selectedNodeId ? orderedWorkflowNodes(graph).findIndex(node => node.id === selectedNodeId) : -1;
    state.selectedWorkflowNodeIndex = selectedIndex >= 0 ? selectedIndex : firstRunNodeIndex(graph, run);
    state.status = null;
    render();
  }, (error, hasCached) => {
    if (!current()) return;
    state.status = hasCached ? "Showing cached recorded graph. Refresh failed." : workflowError(error, `Could not load recorded graph for run ${run.id}.`);
    render();
  });
}

async function openTaskList(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
}): Promise<void> {
  const { state, client, render } = params;
  state.focus = "content"; state.filter = ""; state.taskContext = null;
  const routeVersion = state.routeVersion;
  state.screen = "status";
  state.status = "Loading tasks...";
  render();
  const ownerCurrent = captureTuiWorkspaceOwner(client);
  const current = () => ownerCurrent() && state.routeVersion === routeVersion && (state.screen === "status" || state.screen === "tasks");
  await loadTuiTaskList(client, tasksListCacheKey, {}, (tasks, source, complete) => {
    if (!current()) return;
    const opening = state.screen === "status";
    const selectedId = opening ? null : state.tasks[state.selectedIndex]?.taskId;
    state.tasks = tasks;
    const selectedIndex = selectedId ? tasks.findIndex(task => task.taskId === selectedId) : -1;
    state.selectedIndex = selectedIndex >= 0 ? selectedIndex : clamp(state.selectedIndex, 0, Math.max(0, tasks.length - 1));
    if (opening) { state.scrollOffset = 0; state.activeTask = null; }
    state.status = complete ? null : source === "cache" ? "Showing saved tasks. Syncing…" : `Loading more tasks… ${tasks.length} available.`;
    state.screen = "tasks";
    render();
  }, (error, hasCached) => {
    if (!current()) return;
    state.status = hasCached ? "Showing saved or partially synced tasks. Refresh failed." : workflowError(error,
      client.hasSession() ? "Could not load tasks. Use /refresh to retry." : "Could not load tasks. Use /login first.");
    if (!hasCached) state.screen = "status";
    render();
  });
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
  const current = () => state.routeVersion === routeVersion &&
    (state.screen === "status" || state.screen === "workflows") && workflowOpenRequests.get(state) === request;
  render();
  await loadCachedTuiWorkspace(client, workflowsListCacheKey, () => client.listWorkflows(), (workflows) => {
    if (!current()) return;
    const opening = state.screen === "status";
    const selectedId = opening ? null : state.workflows[state.selectedIndex]?.id;
    state.workflows = workflows;
    const selectedIndex = selectedId ? workflows.findIndex(item => item.id === selectedId) : -1;
    state.selectedIndex = selectedIndex >= 0 ? selectedIndex : clamp(state.selectedIndex, 0, Math.max(0, workflows.length - 1));
    if (opening) state.scrollOffset = 0;
    state.status = null;
    state.screen = "workflows";
    render();
  }, (error, hasCached) => {
    if (!current()) return;
    state.status = hasCached ? "Showing cached workflows. Refresh failed." : workflowError(error, "Could not load workflows. Use /login first if you are not signed in.");
    if (!hasCached) state.screen = "status";
    render();
  });
}

async function openWorkflowById(params: {
  state: TuiState;
  client: OpenMatesClient;
  workflowId: string;
  render: () => void;
}): Promise<void> {
  const { state, client, workflowId, render } = params;
  await openWorkflowDetail({ state, client, workflowId, render });
}

async function openWorkflowDetail(params: {
  state: TuiState;
  client: OpenMatesClient;
  workflowId: string;
  render: () => void;
}): Promise<void> {
  const { state, client, workflowId, render } = params;
  const routeVersion = state.routeVersion;
  const request = nextWorkflowOpenRequest(state);
  state.screen = "status";
  const current = () => state.routeVersion === routeVersion && workflowOpenRequests.get(state) === request &&
    (state.screen === "status" || (state.screen === "workflow" && state.activeWorkflow?.id === workflowId));
  const detailVisible = () => state.screen === "workflow" && state.activeWorkflow?.id === workflowId;
  state.status = `Loading workflow ${workflowId}...`;
  render();
  await loadCachedTuiWorkspace(client, workflowDetailCacheKey(workflowId), () => client.getWorkflow(workflowId), (detail) => {
    if (!current()) return;
    const opening = state.screen === "status";
    const selectedNodeId = !opening && state.workflowTab === "graph" && state.activeWorkflow
      ? orderedWorkflowNodes(state.activeWorkflow.graph)[state.selectedWorkflowNodeIndex]?.id : null;
    state.activeWorkflow = detail;
    if (opening) {
      state.workflowRuns = [];
      state.workflowRunGraph = null;
      state.workflowTab = "graph";
      state.selectedWorkflowNodeIndex = 0;
      state.selectedWorkflowRunIndex = 0;
      state.expandedWorkflowNodeId = null;
      state.expandedWorkflowRunNodeId = null;
      state.workflowEdit = null;
      state.scrollOffset = 0;
    } else if (selectedNodeId) {
      const selectedIndex = orderedWorkflowNodes(detail.graph).findIndex(node => node.id === selectedNodeId);
      state.selectedWorkflowNodeIndex = selectedIndex >= 0 ? selectedIndex : 0;
    }
    state.screen = "workflow";
    state.status = null;
    render();
  }, (error, hasCached) => {
    if (!current()) return;
    state.status = hasCached ? "Showing cached workflow. Refresh failed." : workflowError(error, `Could not load workflow ${workflowId}.`);
    if (!hasCached) state.screen = "status";
    render();
  });
  if (current() && detailVisible()) await refreshActiveWorkflowRuns({ state, client, render });
}

async function refreshActiveWorkflowRuns(params: {
  state: TuiState;
  client: OpenMatesClient;
  render: () => void;
  ownerCurrent?: () => boolean;
}): Promise<void> {
  const { state, client, render, ownerCurrent } = params;
  const workflow = state.activeWorkflow;
  if (!workflow) return;
  const routeVersion = state.routeVersion;
  const current = () => (!ownerCurrent || ownerCurrent()) && state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id;
  if (!state.workflowRuns.length) { state.status = "Refreshing workflow runs..."; render(); }
  await loadCachedTuiWorkspace(client, workflowRunsCacheKey(workflow.id),
    () => client.listWorkflowRuns(workflow.id), (runs) => {
    if (!current()) return;
    const previousRun = state.workflowRuns[state.selectedWorkflowRunIndex];
    const selectedRunId = previousRun?.id;
    state.workflowRuns = runs;
    const selectedIndex = selectedRunId ? runs.findIndex((run) => run.id === selectedRunId) : -1;
    if (selectedIndex >= 0) state.selectedWorkflowRunIndex = selectedIndex;
    state.selectedWorkflowRunIndex = clamp(state.selectedWorkflowRunIndex, 0, Math.max(0, state.workflowRuns.length - 1));
    state.status = null;
    const currentRun = state.workflowRuns[state.selectedWorkflowRunIndex];
    if (!currentRun) state.workflowRunGraph = null;
    if (state.workflowTab === "runs" && currentRun &&
        (!state.workflowRunGraph || currentRun.id !== selectedRunId || currentRun.version_id !== previousRun?.version_id)) {
      void loadSelectedWorkflowRunGraph({ state, client, render, ownerCurrent });
    }
    render();
  }, (error, hasCached) => {
    if (!current()) return;
    state.status = hasCached ? "Showing cached runs. Refresh failed." : workflowError(error, "Could not refresh workflow runs.");
    render();
  });
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
  const ownerCurrent = captureTuiWorkspaceOwner(client);
  const routeVersion = state.routeVersion;
  const current = () => ownerCurrent() && state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id && state.workflowEdit === edit;
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
    await Promise.all([
      invalidateCachedTuiWorkspace(client, workflowDetailCacheKey(workflow.id), ownerCurrent),
      invalidateCachedTuiWorkspace(client, workflowsListCacheKey, ownerCurrent),
    ]);
    if (!current()) return;
    const updated = await client.updateWorkflow(workflow.id, { graph });
    if (!current()) return;
    const hasListEntry = state.workflows.some(item => item.id === updated.id);
    const updatedList = hasListEntry ? state.workflows.map(item => item.id === updated.id ? updated : item) : state.workflows;
    await writeCachedTuiWorkspace(client, workflowDetailCacheKey(workflow.id), updated, ownerCurrent);
    if (!current()) return;
    if (hasListEntry) await writeCachedTuiWorkspace(client, workflowsListCacheKey, updatedList, ownerCurrent);
    if (!current()) return;
    state.activeWorkflow = updated;
    state.workflows = updatedList;
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
  const node = orderedWorkflowNodes(workflow.graph)[state.selectedWorkflowNodeIndex];
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
  const ownerCurrent = captureTuiWorkspaceOwner(client);
  const routeVersion = state.routeVersion;
  const current = () => ownerCurrent() && state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id;
  if (!workflow.enabled) {
    state.status = "This workflow is disabled. Press t to enable it before running.";
    render();
    return;
  }
  state.status = "Starting workflow run...";
  render();
  try {
    await invalidateCachedTuiWorkspace(client, workflowRunsCacheKey(workflow.id), ownerCurrent);
    if (!current()) return;
    const run = await client.runWorkflow(workflow.id, {
      idempotencyKey: `tui-${workflow.id}-${Date.now()}`,
      mode: "manual",
      input: {},
    });
    if (!current()) return;
    const updatedRuns = [run, ...state.workflowRuns.filter((candidate) => candidate.id !== run.id)];
    await writeCachedTuiWorkspace(client, workflowRunsCacheKey(workflow.id), updatedRuns, ownerCurrent);
    if (!current()) return;
    state.workflowRuns = updatedRuns;
    state.selectedWorkflowRunIndex = 0;
    if (state.workflowTab === "runs") await loadSelectedWorkflowRunGraph({ state, client, render, ownerCurrent });
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
  const ownerCurrent = captureTuiWorkspaceOwner(client);
  const routeVersion = state.routeVersion;
  const current = () => ownerCurrent() && state.screen === "workflow" && state.routeVersion === routeVersion && state.activeWorkflow?.id === workflow.id;
  state.status = `Cancelling run ${run.id}...`;
  render();
  try {
    await invalidateCachedTuiWorkspace(client, workflowRunsCacheKey(workflow.id), ownerCurrent);
    if (!current()) return;
    const result = await client.cancelWorkflowRun(workflow.id, run.id);
    if (!current()) return;
    state.status = `Run ${result.run_id} ${result.status}.`;
    await refreshActiveWorkflowRuns({ state, client, render, ownerCurrent });
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
