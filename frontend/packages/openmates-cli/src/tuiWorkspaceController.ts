/** Workspace navigation and forms reuse the encrypted client contracts. */
import { parseEmbedContentObject, type OpenMatesClient, type UserTaskStatus } from "./client.js";
import {captureTuiView,closeTuiFullscreen,fullscreenHeaderControls,isTuiFullscreen} from './tuiFullscreenChrome.js';
import {handleHeaderKey,handleHeaderCommand,openHeaderAction} from './tuiHeaderActions.js';
import {openTuiSettings,closeTuiSettings,handleSettingsCommand,handleSettingsKey} from './tuiSettingsShell.js';
import { randomUUID } from "node:crypto";
import type { TuiState, TuiScreen, TuiWorkspace } from "./tuiRenderer.js";
import type { TuiTerminal, TerminalKey } from "./tuiTerminal.js";
import { parseChatContextContent, chatContextDetails, chatContextSummary } from "./chatContextEvents.js";
import { AuthoringSaveApprovalRequired, persistCliProjectAuthoringJob } from "./cliProjectAuthoringSave.js";
import { registerCliProjectFileExecutor } from "./projectFileExecutor.js";
import { boundedAuthoringHistory, startCliProjectAuthoring, type AuthoringRecommendation } from "./cliProjectAuthoring.js";
import { buildTaskForm, filterTasks, loadTaskContext, submitTaskForm } from "./tuiTasksWorkspace.js";
import { loadTuiProjects, loadTuiProject, loadTuiProjectFiles, readTuiProjectFile, buildProjectForm, submitProjectForm, filteredProjects, filteredProjectFiles, parentTuiProjectFolderId } from "./tuiProjectsWorkspace.js";
import { buildWorkflowNodeForm, orderedWorkflowNodes, submitWorkflowNodeForm } from "./tuiWorkflowWorkspace.js";
import { decryptUserTasks, TASK_STATUSES } from "./tasksCli.js";
import { formValue } from "./tuiForms.js";
import { WORKSPACES } from "./tuiLayout.js";
import { tuiChatSidebarRows, refreshTuiChatSidebar, placeTuiChats, createTuiChatProject, moveTuiChatSidebarSelection, updateTuiChatSidebar } from './tuiChatSidebar.js';
import { encryptWithAesGcmCombined } from './crypto.js';
import { paletteActions, TUI_ACTIONS } from "./tuiActions.js";
import { eraseGrapheme, moveGraphemeCursor, terminalText } from "./tuiText.js";
import { formatEmbedFullscreenLines } from "./embedRenderers.js";
import { registerChatEmbedAliases, exampleEmbedMap, chatEmbedReferences, hydrateChatEmbedPreviews, hydrateFitnessResults, aliasForEmbed, isFitnessEmbed, fitnessSearchDetail, fitnessResultDetail } from './tuiEmbeds.js';
import { normalizeFitnessSearchContent } from '../../ui/src/components/embeds/fitness/fitnessEmbedData.js';
import { chatResultsViews } from './tuiChatResults.js';
import {handleQuestionKey, openQuestion} from './tuiInteractiveQuestions.js';
import { buildTuiResultsViewData, type TuiResultsViewMode } from './tuiResultsViews.js';
import { currentInspiration, homeContinueItems, isWorkspaceHome, loadHomeData, workspaceInspirations } from "./tuiHome.js";
import { loadTuiApps, homeTuiApps, loadTuiAppsSkill, buildTuiAppsSkillForm, prepareTuiAppsSkillRun, buildTuiAppsRunConfirmation, executeTuiAppsSkill, loadTuiAppsResults, loadTuiAppsResult, loadTuiAppsWorkflows } from "./tuiAppsWorkspace.js";
import { loadCachedTuiWorkspace, invalidateCachedTuiWorkspace, writeCachedTuiWorkspace, readCachedTuiWorkspace, captureTuiWorkspaceOwner } from './tuiCachedWorkspaces.js';
import {isTuiAiComposer,type TuiModelSelectorShell} from './tuiModelSelectorShell.js';

export type WorkspaceContext = {
  state: TuiState; client: OpenMatesClient; terminal: TuiTerminal; render: () => void;
  command: (command: string) => Promise<void>; send: (message: string,options?:{questionAnswer?:boolean}) => Promise<void>;
  modelShell?: TuiModelSelectorShell;
};

function chatDraftKey(state: TuiState) { return state.screen === "example" ? `example:${state.activeExample?.chat.id}` : state.activeChatId ?? "new"; }
const DRAFT_ONLY_CHAT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function missingChatMetadata(error: unknown, id: string): boolean {
  return error instanceof Error && (error.message === "Chat metadata failed with HTTP 404" || error.message.startsWith(`Chat '${id}' not found.`));
}
function selectedTask(state:TuiState) {return state.screen==="tasks"?filterTasks(state.tasks,state.filter,state.taskStatusFilter as UserTaskStatus||undefined)[state.selectedIndex]:state.activeTask;}
export function rememberDraft(state: TuiState): void {
  if (state.workspace === "chats" && !state.input.startsWith("/")) state.drafts[chatDraftKey(state)] = state.input;
}
export function route(state: TuiState, workspace: TuiWorkspace, screen: TuiScreen): number {
  if(state.settings)closeTuiSettings(state);
  if (state.input) rememberDraft(state);
  state.workspace = workspace; state.screen = screen;
  state.navigationIndex = WORKSPACES.indexOf(workspace); state.focus = workspace === "chats" && !["start","chats"].includes(screen) ? "composer" : "content";
  state.input = ""; state.inputCursor = null; state.filter = ""; state.scrollOffset = 0; state.selectedIndex = 0;
  state.sidebarIndex = 0;
  state.homeShowAll = false;state.homeSelectionMoved=false;
  state.status = null;
  state.form = null; state.workflowEdit = null;state.questionEditor=null;state.chrome=null;
  state.headerActionIndex=0;
  state.textSelection = false;
  return ++state.routeVersion;
}
function newChat(state: TuiState): void {
  state.chatOrigin=null;
  route(state, "chats", "start");
  state.activeChatId = null; state.activeChat = null; state.activeExample = null;
  state.messages = []; state.headerState = "new"; state.headerError = null; state.followUpSuggestions = [];
  state.chatEmbeds={};state.embedAliases={};state.chatSelectedEmbedId=null;state.chatEmbedLoads=new Set();
  state.resultsViewModes={};state.activeResultsView=null;state.resultsViewOrigin=null;
  state.projectFocusPending = null;
  state.input = state.drafts.new ?? "";
}
async function recent(context: WorkspaceContext): Promise<void> {
  const {state, client, render} = context;
  if (!state.signedIn || state.homeLoading || typeof client.listChats !== "function") return;
  const request=state.routeVersion,homeRequest=state.homeLoadVersion;
  const chats=(await client.listChats(Number.MAX_SAFE_INTEGER, 1)).chats;
  if(request!==state.routeVersion||homeRequest!==state.homeLoadVersion||!state.signedIn)return;
  updateTuiChatSidebar(state, () => { state.recentChats = chats; });
  render();
  await refreshTuiChatSidebar(state, client, render, true);
}

export async function openSavedChat(context: WorkspaceContext, id: string): Promise<void> {
  const {state, client, render} = context;
  if(state.screen!=="chat"||state.activeChatId!==id)state.chatOrigin=captureTuiView(state);
  const request = route(state, "chats", "chat");
  const ownerCurrent = captureTuiWorkspaceOwner(client);
  let ownedChatId = id;
  const current = () => state.routeVersion === request && state.activeChatId === ownedChatId && ownerCurrent();
  state.activeChatId=id;state.activeChat=[...state.recentChats,...state.sidebarLinkedChats,...state.activityChats].find(chat=>chat.id===id) ?? null;
  state.activeExample=null;state.messages=[];state.headerState=state.activeChat ? "ready" : "loading";
  state.chatEmbeds={};state.embedAliases={};state.chatSelectedEmbedId=null;state.chatEmbedLoads=new Set();
  state.resultsViewModes={};state.activeResultsView=null;state.resultsViewOrigin=null;
  state.status = "Loading chat…"; render();
  let published = false;
  const publish = (result: Awaited<ReturnType<OpenMatesClient['getChatMessages']>>, pending = false, draftMarkdown?: string) => {
    if (!current()) return;
    ownedChatId = result.chat.id;
    state.activeChatId = result.chat.id; state.activeChat = result.chat; state.activeExample = null;
    state.selectedProjectId = null;
    state.messages = result.messages.map((m) => ({id: m.id, role: m.role === "user" ? "user" : m.role === "system" ? "system" : "assistant", content: m.content, title: m.senderName, category:m.category, embedIds: m.embedIds}));
    registerChatEmbedAliases(state);
    if(typeof client.getEmbed==='function')void hydrateChatEmbedPreviews(state,client,render);
    state.projectFocusPending = null;
    state.headerState = "ready"; state.headerError = null;
    if (!published) state.input = state.drafts[result.chat.id] ?? draftMarkdown ?? "";
    state.status = pending ? "Loading older messages…" : result.historyIncomplete ? "Showing cached recent messages. Older history is unavailable offline." : null; render();
    // Draft lookup must not delay browsing or replace text typed after opening.
    if (!published && state.drafts[result.chat.id] === undefined && draftMarkdown === undefined) {
      const inputAtOpen = state.input;
      const draft = typeof client.getCachedDraft === "function" ? client.getCachedDraft(result.chat.id) :
        typeof client.getDraft === "function" ? client.getDraft(result.chat.id) : Promise.resolve(null);
      void draft.then(remoteDraft => {
        if (!current() || state.input !== inputAtOpen || state.drafts[result.chat.id] !== undefined) return;
        state.input = remoteDraft?.markdown ?? "";render();
      }).catch(() => {
        if (current() && !state.status) { state.status = "Saved draft unavailable."; render(); }
      });
    }
    published = true;
  };
  try {
    const result = await client.getChatMessages(id, {preferCache:true,onMessages:latest=>publish(latest,true)});
    publish(result);
  } catch (error) {
    if (!current()) return;
    if (!published && DRAFT_ONLY_CHAT_ID.test(id) && missingChatMetadata(error,id) &&
        typeof client.hasSession === "function" && client.hasSession() && typeof client.getDraft === "function") {
      try {
        // Only an owner-decrypted, targeted draft may establish a chat without metadata.
        const draft = await client.getDraft(id,true);
        if (current() && client.hasSession() && draft?.chatId === id && draft.markdown.trim()) {
          const recovered = await client.getChatMessages(id,{preferCache:true});
          if (current() && recovered.chat.id === id && recovered.chat.hasDraft === true && recovered.messages.length === 0) {
            publish(recovered,false,draft.markdown);
            return;
          }
        }
      } catch { /* Keep the original missing-chat error when no draft-only chat is proven. */ }
    }
    if (!current()) return;
    if (!published) { state.headerState = 'error'; state.headerError = 'Could not load chat'; }
    state.status = `${error instanceof Error ? error.message : String(error)}. Use /refresh to retry.`;
    render();
  }
}
async function openProject(context: WorkspaceContext, id: string): Promise<void> {
  const {state, client, render} = context;
  const request = route(state, "projects", "project");
  state.activeProject=null;state.projectFiles=[];state.projectTab='overview';state.projectPath='';state.projectFolderId=null;state.projectSourceId=null;
  state.status = "Loading Project…"; render();
  await loadCachedTuiWorkspace(client,`project:${id}:detail`,()=>loadTuiProject(client,id),async project=>{
    if(state.routeVersion!==request)return;
    state.activeProject=project;state.status=null;render();
    if(state.projectTab!=='tasks')await projectFiles(context,project,{folderId:state.projectFolderId??undefined,sourceId:state.projectSourceId??undefined,path:state.projectSourceId?state.projectPath:undefined});
  },(error,cached)=>workspaceLoadError(context,request,'Project',error,cached));
}
function workspaceLoadError(context:WorkspaceContext,request:number,label:string,error:unknown,cached:boolean):void {
  if(context.state.routeVersion!==request)return;
  context.state.status=cached?`Showing saved ${label}. Offline; /refresh to retry.`:`Could not load ${label}: ${error instanceof Error?error.message:String(error)}`;
  context.render();
}
type ProjectFileOptions=Parameters<typeof loadTuiProjectFiles>[2];
function projectFilesKey(id:string,options:ProjectFileOptions={}) {return `project:${id}:files:${JSON.stringify([options?.folderId??null,options?.sourceId??null,options?.path??null])}`;}
async function projectFiles(context:WorkspaceContext,project:NonNullable<TuiState['activeProject']>,options:ProjectFileOptions={}):Promise<void> {
  const {state,client,render}=context,request=state.routeVersion;
  const location=JSON.stringify([state.projectFolderId,state.projectSourceId,state.projectPath]);
  await loadCachedTuiWorkspace(client,projectFilesKey(project.id,options),()=>loadTuiProjectFiles(client,project,options),files=>{
    if(request!==state.routeVersion||state.activeProject?.id!==project.id||location!==JSON.stringify([state.projectFolderId,state.projectSourceId,state.projectPath]))return;
    const selected=filteredProjectFiles(state.projectFiles,state.filter)[state.selectedIndex]?.id;
    state.projectFiles=files;
    if(selected){const index=filteredProjectFiles(files,state.filter).findIndex(file=>file.id===selected);if(index>=0)state.selectedIndex=index;}
    state.status=null;render();
  },(error,cached)=>workspaceLoadError(context,request,'Files',error,cached));
}
async function projectTasks(context:WorkspaceContext,id:string):Promise<void> {
  const {state,client,render}=context,request=state.routeVersion;
  await loadCachedTuiWorkspace(client,`project:${id}:tasks`,async()=>decryptUserTasks(await client.listUserTasks({projectId:id}),client.getMasterKeyBytes()),tasks=>{
    if(request!==state.routeVersion||state.activeProject?.id!==id||state.projectTab!=='tasks')return;
    const selected=filterTasks(state.tasks,state.filter)[state.selectedIndex]?.taskId;
    state.tasks=tasks;
    if(selected){const index=filterTasks(tasks,state.filter).findIndex(task=>task.taskId===selected);if(index>=0)state.selectedIndex=index;}
    state.status=null;render();
  },(error,cached)=>workspaceLoadError(context,request,'Project Tasks',error,cached));
}
async function refreshOpenProject(context: WorkspaceContext): Promise<void> {
  const {state, client, render} = context, id = state.activeProject!.id;
  const request = ++state.routeVersion;
  state.status = 'Refreshing Project…'; render();
  await invalidateCachedTuiWorkspace(client,`project:${id}:detail`);
  await loadCachedTuiWorkspace(client,`project:${id}:detail`,()=>loadTuiProject(client,id),async project=>{
    if(request!==state.routeVersion||state.activeProject?.id!==id)return;
    state.activeProject=project;state.status=null;render();
    if(state.projectTab==='tasks') {await invalidateCachedTuiWorkspace(client,`project:${id}:tasks`);await projectTasks(context,id);}
    else {
      const options={folderId:state.projectFolderId??undefined,sourceId:state.projectSourceId??undefined,path:state.projectSourceId?state.projectPath:undefined};
      await invalidateCachedTuiWorkspace(client,projectFilesKey(id,options));await projectFiles(context,project,options);
    }
  },(error,cached)=>workspaceLoadError(context,request,'Project',error,cached));
}
async function openTask(context: WorkspaceContext, taskId: string): Promise<void> {
  const {state, client, render} = context;
  const task = state.tasks.find((t) => t.taskId === taskId || t.shortId === taskId || t.slug === taskId);
  if (!task) throw new Error("Task not found in this workspace.");
  route(state, state.workspace === "projects" ? "projects" : "tasks", "task"); state.activeTask = task; state.taskContext = null; render();
  const request = state.routeVersion;
  try {
    const detail = await loadTaskContext(client, task.taskId);
    if (request === state.routeVersion && state.activeTask?.taskId === task.taskId) state.taskContext = detail;
  } catch (error) { if (request === state.routeVersion) state.status = `Task activity unavailable: ${error instanceof Error ? error.message : String(error)}`; }
  render();
}

async function persistTuiAuthoring(context: WorkspaceContext, event: AuthoringRecommendation, job: Record<string, unknown>, approvedDigest?: string): Promise<Record<string, unknown>> {
  const { state } = context;
  try {
    const saved = await persistCliProjectAuthoringJob(context.client, job, approvedDigest);
    if (saved.status === "needs_input" && state.activeChatId === event.chat_id) {
      const draft = saved.draft && typeof saved.draft === "object" ? saved.draft as Record<string, unknown> : {};
      state.detailTitle = "Authoring needs your input";
      state.detailLines = [typeof draft.question === "string" ? draft.question : "Open the Workflow input request to supply its missing details."];
      state.screen = "embed"; state.scrollOffset = 0; state.focus = "content";
    }
    state.chatContextAuthoringJobs[event.event_id] = { projectId: event.project_id, jobId: String(saved.job_id), status: String(saved.status) };
    return saved;
  } catch (error) {
    if (!(error instanceof AuthoringSaveApprovalRequired)) throw error;
    state.chatContextAuthoringJobs[event.event_id] = { projectId: event.project_id, jobId: String(job.job_id), status: "needs_write_approval", ...(state.activeChatId === event.chat_id ? { approvalDigest: error.digest } : {}) };
    if (state.activeChatId !== event.chat_id) return { ...job, status: "needs_write_approval" };
    state.detailTitle = `Review generated ${event.kind === "focus" ? "Focus" : "Workflow"}`;
    state.detailLines = [error.mutation.path, "", ...(error.mutation.content ?? error.mutation.patch ?? "").split("\n"), "", `Approve this exact write: /authoring-save ${contextIndex(state, event)}`];
    state.screen = "embed"; state.scrollOffset = 0; state.focus = "content";
    return { ...job, status: "needs_write_approval" };
  }
}
function contextIndex(state: TuiState, event: AuthoringRecommendation): number {
  return state.messages.filter(row => row.role === "system").map(row => parseChatContextContent(row.content)).filter(row => row !== null).findIndex(row => row.event_id === event.event_id) + 1;
}
function watchTuiAuthoring(context: WorkspaceContext, event: AuthoringRecommendation, jobId: string): void {
  const control = context.state.chatContextAuthoringControls[event.event_id];
  if (!control || control.watching || typeof context.client.getProjectAuthoringJob !== "function") return;
  control.watching = true;
  void (async () => {
    // Source jobs deliver over the retained executor socket; polling also repairs a missed completion event.
    for (let attempt = 0; attempt < 40 && context.state.chatContextAuthoringControls[event.event_id] === control; attempt++) {
      await new Promise(resolve => { const timer = setTimeout(resolve, 3000); timer.unref(); });
      if (context.state.chatContextAuthoringControls[event.event_id] !== control) return;
      if (control.approve) return; // The exact source proposal is waiting for the displayed user action.
      const job = await context.client.getProjectAuthoringJob(event.project_id, jobId);
      const settled = await persistTuiAuthoring(context, event, job);
      context.render();
      if (!["queued", "running", "pending_file"].includes(String(settled.status))) {
        if (settled.status !== "needs_write_approval" || !control.approve) control.stop();
        return;
      }
    }
    control.stop();
  })().catch(() => {
    const entry = context.state.chatContextAuthoringJobs[event.event_id];
    if (entry) entry.status = "save_pending";
    context.state.status = "Authoring needs attention. Refresh the job to retry its encrypted save.";
    control.stop(); context.render();
  }).finally(() => { control.watching = false; });
}
function showSourceAuthoringReview(context: WorkspaceContext, event: AuthoringRecommendation): void {
  const control = context.state.chatContextAuthoringControls[event.event_id];
  if (!control?.reviewLines) return;
  context.state.detailTitle = "Review generated Workflow file";
  context.state.detailLines = [...control.reviewLines, "", `Approve this exact write: /authoring-save ${contextIndex(context.state, event)}`];
  control.reviewed = true;
  context.state.screen = "embed"; context.state.scrollOffset = 0; context.state.focus = "content";
}
async function openTuiAuthoringExecutor(context: WorkspaceContext, event: AuthoringRecommendation): Promise<void> {
  if (typeof context.client.openProjectAuthoringWebSocket !== "function") return;
  const focus = await context.client.getActiveProjectFocus(event.chat_id!);
  if (focus?.project_id !== event.project_id) throw new Error("This Project is no longer active in the chat.");
  const key = await context.client.getChatEncryptionKey(event.chat_id!, { teamId: focus.team_id, personal: !focus.team_id });
  const ws = await context.client.openProjectAuthoringWebSocket();
  let approval: ((accepted: boolean) => void) | undefined;
  const control = { reviewLines: undefined as string[] | undefined, reviewed: false, stop() { approval?.(false); executorStop?.(); ws.close(); if (context.state.chatContextAuthoringControls[event.event_id] === control) delete context.state.chatContextAuthoringControls[event.event_id]; }, approve: undefined as (() => void) | undefined };
  context.state.chatContextAuthoringControls[event.event_id] = control;
  const executorStop = registerCliProjectFileExecutor({ client: context.client, ws, chatId: event.chat_id!, chatKey: key,
    requestApproval: request => new Promise<boolean>(resolve => {
      if (approval) { resolve(false); return; }
      approval = resolve;
      control.approve = () => { approval = undefined; control.approve = undefined; resolve(true); };
      const entry = context.state.chatContextAuthoringJobs[event.event_id]; if (entry) entry.status = "needs_write_approval";
      control.reviewLines = [request.mutation.path, "", ...(request.mutation.content ?? request.mutation.patch ?? "").split("\n")];
      if (context.state.activeChatId === event.chat_id) {
        showSourceAuthoringReview(context, event); control.reviewed = true;
      }
      context.render();
    }) });
}

export async function handleWorkspaceCommand(context: WorkspaceContext, command: string): Promise<boolean> {
  const {state, client, render} = context;
  const space = command.indexOf(" ");
  const name = space < 0 ? command : command.slice(0, space);
  const arg = space < 0 ? "" : command.slice(space + 1).trim();
  switch (name) {
    case "/model": if(context.modelShell)await context.modelShell.open();return true;
    case "/model-action": if(context.modelShell)await context.modelShell.action(arg);return true;
    case "/attach": {
      if(!isTuiAiComposer(state))return true;
      if(!client.hasSession()){state.status="Sign in to attach a local file.";render();return true;}
      state.form={kind:"composer-attach",title:"Attach a local file",fieldIndex:0,
        fields:[{name:"path",label:"Explicit path (./, ../, ~/ or /)",value:"",required:true}]};
      render();return true;
    }
    case "/settings": await openTuiSettings(context,arg);return true;
    case "/settings-close": closeTuiSettings(state);render();return true;
    case "/settings-action": await handleSettingsCommand(context,arg);return true;
    case "/header": await openHeaderAction(context,arg);return true;
    case "/header-action": await handleHeaderCommand(context,arg);return true;
    case "/back":
    case "/close":
      if(state.chrome)state.chrome=null;else if(state.settings)closeTuiSettings(state);else if(!closeTuiFullscreen(state))await handleWorkspaceKey(context,"",{name:"escape"});
      render();return true;
    case "/context": {
      const events = state.messages.filter(message => message.role === "system").map(message => parseChatContextContent(message.content)).filter(event => event !== null);
      const index = Number(arg || events.length) - 1;
      const event = events[index];
      if (!event) { state.status = "No applied context at that index."; render(); return true; }
      state.detailTitle = chatContextSummary(event); state.detailLines = chatContextDetails(event);
      state.screen = "embed"; state.scrollOffset = 0; state.focus = "content"; render(); return true;
    }
    case "/project-focus-reject": {
      if (state.projectFocusPending) await state.projectFocusPending.reject();
      state.projectFocusPending = null; render(); return true;
    }
    case "/focus-author":
    case "/authoring-refresh":
    case "/authoring-save": {
      const events = state.messages.filter(message => message.role === "system").map(message => parseChatContextContent(message.content)).filter(event => event !== null);
      const event = events[Number(arg || events.length) - 1];
      if (!event || event.type !== "project_authoring_recommendation" || event.chat_id !== state.activeChatId) throw new Error("Choose a Project authoring recommendation in this chat.");
      const existing = state.chatContextAuthoringJobs[event.event_id];
      if (name === "/focus-author" && existing) { state.status = `Authoring: ${existing.status}`; render(); return true; }
      if (name !== "/focus-author" && !existing?.jobId) throw new Error("This recommendation has no started authoring job.");
      if (name === "/focus-author") state.chatContextAuthoringJobs[event.event_id] = { projectId: event.project_id, jobId: null, status: "starting" };
      if (name !== "/focus-author" && state.chatContextAuthoringControls[event.event_id]?.approve
          && (name === "/authoring-refresh" || !state.chatContextAuthoringControls[event.event_id].reviewed)) {
        showSourceAuthoringReview(context, event); render(); return true;
      }
      if (name === "/authoring-save" && state.chatContextAuthoringControls[event.event_id]?.approve) {
        state.chatContextAuthoringControls[event.event_id].approve?.();
        if (existing) existing.status = "pending_file";
        state.screen = "chat"; watchTuiAuthoring(context, event, existing!.jobId!); render(); return true;
      }
      render();
      try {
        if (name === "/focus-author") await openTuiAuthoringExecutor(context, event);
        const job = name !== "/focus-author" ? await client.getProjectAuthoringJob(event.project_id, existing!.jobId!)
          : await startCliProjectAuthoring(client, event, boundedAuthoringHistory(state.messages));
        if (typeof job.job_id !== "string" || typeof job.status !== "string") throw new Error("Authoring job response is incomplete.");
        const settled = await persistTuiAuthoring(context, event, job, name === "/authoring-save" ? existing?.approvalDigest : undefined);
        state.status = `Authoring: ${String(settled.status)}`;
        if (["queued", "running", "pending_file"].includes(String(settled.status))) watchTuiAuthoring(context, event, job.job_id);
        else if (settled.status !== "needs_write_approval") state.chatContextAuthoringControls[event.event_id]?.stop();
      } catch (error) {
        if (name === "/focus-author") { delete state.chatContextAuthoringJobs[event.event_id]; state.chatContextAuthoringControls[event.event_id]?.stop(); }
        throw error;
      } finally { render(); }
      return true;
    }
    case "/browse": state.homeShowAll=!state.homeShowAll;state.selectedIndex=0;state.scrollOffset=0;state.focus="content";render();return true;
    case "/inspiration-next": {
      const count=workspaceInspirations(state).length;
      state.inspirationIndices[state.workspace]=((state.inspirationIndices[state.workspace]??0)+1)%Math.max(1,count);render();return true;
    }
    case "/inspiration": {
      const inspiration=currentInspiration(state);
      if(!inspiration){state.status=state.homeError||"Daily inspiration is loading.";render();return true;}
      if(state.workspace==="tasks"){state.form=buildTaskForm("task-create");const title=state.form.fields.find((f)=>f.name==="title");if(title)title.value=inspiration.title||inspiration.phrase;}
      else if(state.workspace==="apps" && inspiration.feature?.settings_path?.startsWith("apps/")) {
        const parts=inspiration.feature.settings_path.split("/");
        if(parts[1]!=="all"&&parts[2]==="skill"&&parts[3])await context.command(`/app-skill ${parts[1]}/${parts[3]}`);
        else if(parts[1]!=="all"&&parts.length===3&&!['skills','focus_modes','settings_memories'].includes(parts[2]))await context.command(`/app-skill ${parts[1]}/${parts[2]}`);
        else {await context.command("/apps");if(parts[1]!=="all")await context.command(`/app ${parts[1]}`);}
      }
      else if(state.workspace!=="chats"){state.detailTitle=inspiration.feature?.title||inspiration.title;state.detailLines=[inspiration.phrase,"",inspiration.assistant_response||inspiration.feature?.description||""];state.screen="embed";state.scrollOffset=0;}
      else {newChat(state);state.input=inspiration.phrase;state.followUpSuggestions=inspiration.follow_up_suggestions;rememberDraft(state);state.status="Review the inspiration prompt, then press Enter to start.";}
      render();return true;
    }
    case "/apps": {
      const request=route(state,"apps","apps");state.status="Loading Apps…";render();const apps=await loadTuiApps(client);
      if(request===state.routeVersion){state.apps=apps;state.status=null;}render();return true;
    }
    case "/app": {
      const app=state.apps.find((a)=>a.id===arg);if(!app)throw new Error("App not found. Open /apps first.");
      route(state,"apps","app");state.activeApp=app;state.activeAppSkill=null;state.appTab="skills";render();return true;
    }
    case "/app-skill": {
      const [appId,skillId]=arg.split("/");if(!appId||!skillId)throw new Error("Choose /app-skill app/skill.");
      const request=route(state,"apps","app-skill");state.activeAppSkill=null;state.appTab="skills";state.appSkillTab="overview";state.status="Loading skill…";render();
      const apps=state.apps.length?state.apps:await loadTuiApps(client);
      if(request!==state.routeVersion)return true;
      const skill=await loadTuiAppsSkill(client,appId,skillId);if(request===state.routeVersion){state.apps=apps;state.activeAppSkill=skill;state.activeApp=apps.find((a)=>a.id===appId)??null;state.status=null;}render();return true;
    }
    case "/app-run": if(!state.activeAppSkill)throw new Error("Open an app skill first.");state.form=buildTuiAppsSkillForm(state.activeAppSkill);render();return true;
    case "/app-results": {
      if(!state.activeApp)throw new Error("Open an app first.");const request=++state.routeVersion;state.status="Loading saved results…";render();
      const results=await loadTuiAppsResults(client,state.activeApp.id,arg?Number(arg):0);if(request===state.routeVersion){state.appResults=results;state.appTab="embeds";state.appSkillTab="embeds";state.selectedIndex=0;state.status=null;}render();return true;
    }
    case "/app-workflows": {
      if(!state.activeApp)throw new Error("Open an app first.");const request=++state.routeVersion;const workflows=await loadTuiAppsWorkflows(client,state.activeApp.id,arg?Number(arg):0);
      if(request===state.routeVersion){state.appWorkflows=workflows;state.appTab="workflows";state.appSkillTab="workflows";state.selectedIndex=0;}render();return true;
    }
    case "/app-result": {
      const request=route(state,"apps","app-result");state.activeAppResult=null;render();const result=await loadTuiAppsResult(client,arg);
      if(request===state.routeVersion)state.activeAppResult=result;render();return true;
    }
    case "/new": case "/clear": newChat(state); state.selectedProjectId = null; render(); return true;
    case '/active': state.sidebarOpen = true; state.focus = 'sidebar'; state.sidebarIndex = 0; render(); await refreshTuiChatSidebar(state, client, render, true); state.sidebarIndex = 0; render(); return true;
    case '/chat-add-to-project': case '/chat-move-to-project': case '/chat-create-project': {
      if (state.chatProjectBusy) return true;
      if (!state.signedIn) throw new Error('Sign in to organize chats.');
      const homeItem=homeContinueItems(state)[state.selectedIndex];
      const selected = state.focus === 'sidebar' ? tuiChatSidebarRows(state)[state.sidebarIndex]?.chatId :
        ['start','chats'].includes(state.screen) ? (homeItem?.kind==='chat' ? homeItem.chat.id : undefined) : state.activeChatId;
      const ids = arg ? arg.split(/\s+/).filter(Boolean) : selected ? [selected] : [];
      if (!ids.length) throw new Error('Choose a saved chat first.');
      await refreshTuiChatSidebar(state, client, render, true);
      if (name === '/chat-create-project') {
        state.chatProjectBusy = true; state.status = 'Organizing chats…'; render();
        try { const id = await createTuiChatProject(state, client, ids); state.chatProjectOperation = null; await openProject(context, id); }
        finally { state.chatProjectBusy = false; }
      } else {
        state.chatProjectOperation = { chatIds: ids, mode: name === '/chat-move-to-project' ? 'move' : 'add' };
        state.chatSidebarLocation = null; state.sidebarOpen = true; state.focus = 'sidebar'; state.sidebarIndex = 0;
        state.status = 'Choose a project or subfolder.';
      }
      render(); return true;
    }
    case '/chat-subfolder': {
      const location = state.chatSidebarLocation;
      if (!location || !arg.trim()) throw new Error('Open a project folder and enter /chat-subfolder followed by a name.');
      const project = state.chatSidebarProjects.find(project => project.id === location.projectId);
      if (!project) throw new Error('Project unavailable.');
      const timestamp = Math.floor(Date.now() / 1000);
      await client.createProjectFolder(project.id, { folder_id: randomUUID(), parent_folder_id: location.folderId,
        encrypted_name: await encryptWithAesGcmCombined(arg.trim().slice(0, 200), project.projectKey),
        encrypted_sort_key: await encryptWithAesGcmCombined(arg.trim().toLowerCase().slice(0, 200), project.projectKey),
        created_at: timestamp, updated_at: timestamp, position: timestamp });
      await refreshTuiChatSidebar(state, client, render, true); return true;
    }
    case "/sidebar": state.sidebarOpen = !state.sidebarOpen; state.focus = state.sidebarOpen ? "sidebar" : state.workspace === "chats" && !["start","chats"].includes(state.screen) ? "composer" : "content"; render(); if (state.sidebarOpen) void recent(context).catch(() => { if(state.signedIn){state.status="Showing cached chats. Sync failed; /refresh to retry.";render();} }); return true;
    case "/chats": route(state, "chats", "chats"); render(); void recent(context).catch(() => { if(state.signedIn){state.status="Showing cached chats. Sync failed; /refresh to retry.";render();} }); return true;
    case "/chat": if (!arg) return handleWorkspaceCommand(context, "/chats"); await openSavedChat(context, arg); return true;
    case "/projects": {
      const request = route(state, "projects", "projects"); state.status = "Loading Projects…"; render();
      await loadCachedTuiWorkspace(client,'projects:list',()=>loadTuiProjects(client),projects=>{
        if(request!==state.routeVersion)return;
        const selected=filteredProjects(state.projects,state.filter)[state.selectedIndex]?.id;
        state.projects=projects;
        if(selected){const index=filteredProjects(projects,state.filter).findIndex(project=>project.id===selected);if(index>=0)state.selectedIndex=index;}
        state.status=null;render();
      },(error,cached)=>workspaceLoadError(context,request,'Projects',error,cached));return true;
    }
    case "/project": if (!arg) return handleWorkspaceCommand(context, "/projects"); await openProject(context, arg); return true;
    case "/project-create": state.form = buildProjectForm(); render(); return true;
    case "/workflow-create": state.form={kind:"workflow-create",title:"Describe new workflow",fieldIndex:0,fields:[{name:"description",label:"What do you want to automate?",value:arg,multiline:true}]};render();return true;
    case "/project-source": {
      if (!state.activeProject) throw new Error("Open a Project first.");
      if (!arg) {state.status = state.activeProject.sources.map((source) => `${source.name ?? source.id}: /project-source ${source.id}`).join("  ") || "This Project has no connected sources.";render();return true;}
      const project = state.activeProject;
      ++state.routeVersion;state.projectTab='files';state.projectSourceId=arg;state.projectFolderId=null;state.projectPath='.';state.projectFiles=[];state.selectedIndex=0;state.filter='';render();
      await projectFiles(context,project,{sourceId:arg,path:'.'});return true;
    }
    case "/project-chat": {
      const project = state.activeProject;
      if (!project) throw new Error("Open a Project first.");
      newChat(state); state.selectedProjectId = project.id; state.activeProject = project;
      state.status = `Chat in Project: ${project.name}`; render(); return true;
    }
    case "/search": {
      if (arg) { state.filter = arg; state.selectedIndex = 0; state.scrollOffset = 0; state.focus = 'content'; render(); }
      else state.form = { kind: "workspace-search", title: `Search ${state.workspace}`, fields: [{name:"query", label:"Search", value:state.filter}], fieldIndex:0 };
      render(); return true;
    }
    case "/question": {
      const key=arg?Number(arg):undefined;
      if(key!==undefined&&(!Number.isInteger(key)||key<1))throw Error('Use /question <number> shown in this chat.');
      openQuestion(state,key);render();return true;
    }
    case "/view": {
      const [indexText,modeText] = arg.split(/\s+/), key=Number(indexText || 1);
      const descriptor=chatResultsViews(state)[key-1];
      if(!Number.isInteger(key)||!descriptor)throw Error('Use /view <number> map, calendar or list for a results view in this chat.');
      if(modeText&&!['map','calendar','list'].includes(modeText))throw Error('Choose map, calendar or list.');
      const data=buildTuiResultsViewData(descriptor,{...exampleEmbedMap(state),...state.chatEmbeds});
      const mode=(modeText||state.resultsViewModes[key]||data.availableModes[0]||'list') as TuiResultsViewMode;
      if(data.entries.length&&!data.availableModes.includes(mode))throw Error(`This results view has no ${mode==='calendar'?'dated':mode==='map'?'mapped':'available'} results.`);
      if(state.screen!=='results-view')state.resultsViewOrigin=captureTuiView(state);
      state.resultsViewModes[key]=mode;state.activeResultsView=key;
      route(state,state.workspace,'results-view');state.focus='content';render();return true;
    }
    case "/wiki": {
      if(!arg)throw Error('Use /wiki <article-title>, for example /wiki Apple_Watch.');
      const languageMatch=/^([a-z]{2,10}):(.+)$/i.exec(arg),language=languageMatch?.[1]??'en',title=languageMatch?.[2]??arg;
      if(state.screen!=='embed')state.embedOrigin=captureTuiView(state);
      const request=route(state,state.workspace,'embed');state.detailEmbed=null;state.embedChoices=[];state.detailTitle=title.replaceAll('_',' ');
      state.detailLines=['Loading Wikipedia article…'];state.focus='content';render();
      try {
        const summary=await client.wikipediaSummary(title,language);
        if(request!==state.routeVersion)return true;
        state.detailTitle=String(summary.title||title).replaceAll('_',' ');
        state.detailLines=[String(summary.description||''),'',String(summary.extract||''),'',String(summary.source_url||'')];
      } catch(error) {
        if(request!==state.routeVersion)return true;
        state.detailLines=['Wikipedia article unavailable.',error instanceof Error?error.message:String(error),'',`/wiki ${arg} · Retry`];
      }
      render();return true;
    }
    case "/embed": {
      registerChatEmbedAliases(state);
      const target=state.embedAliases[arg];
      const id=target?.embedId??arg;
      if(state.screen!=="embed")state.embedOrigin=captureTuiView(state);
      const request = route(state, state.workspace, "embed"); state.detailTitle = "Embeds";state.detailEmbed=null;state.focus="content";
      state.detailLines=["Loading saved embed…"];render();
      if (!arg) {
        const aliases = Object.keys(state.embedAliases).filter(alias=>!state.embedAliases[alias].legacy);state.embedChoices=aliases;
        state.detailLines = aliases.length ? aliases.map(alias => `/embed ${alias}`) : ["No saved embeds in this chat yet."];
      } else {
        try {
        const example = state.activeExample?.embeds?.find((embed) => embed.embed_id === id);
        const content = example ? parseEmbedContentObject(example.content) : null;
        let embed = state.chatEmbeds[id] ?? (example && content ? {id, embedId:id, type:example.type, content, textPreview:null,
          appId:typeof content.app_id==="string"?content.app_id:null, skillId:typeof content.skill_id==="string"?content.skill_id:null, createdAt:null} : await client.getEmbed(id,{preferCache:true,chatId:state.activeChatId ?? undefined}));
        if (request !== state.routeVersion) return true;
        state.detailTitle = embed.textPreview || (embed.appId ? `${embed.appId}${embed.skillId ? `/${embed.skillId}` : ""}` : embed.type?.replaceAll("_", " ")) || "Embed";
        state.detailEmbed=embed;state.embedChoices=[];
        const cachedClient=Object.create(client) as OpenMatesClient;
        cachedClient.getEmbed=(id,options)=>client.getEmbed(id,{...options,preferCache:true,chatId:state.activeChatId ?? undefined});
        let lines:string[];
        if(isFitnessEmbed(embed)){
          embed=await hydrateFitnessResults(embed,cachedClient);
          if(request!==state.routeVersion)return true;
          state.chatEmbeds[id]=embed;registerChatEmbedAliases(state);
          const result=target?.resultIndex===undefined?undefined:normalizeFitnessSearchContent(embed.content).results[target.resultIndex];
          if(target?.resultIndex!==undefined&&!result)throw Error('This class result is unavailable. Open the search to see its current results.');
          if(result?._tuiUnavailable)throw Error('Class details are unavailable offline. Reconnect and open this shortcut again to retry.');
          if(result){embed={...embed,type:'fitness-class',embedId:result.embed_id??embed.embedId,content:result};state.detailTitle=String(result.name??result.venue_name??'Fitness class');}
          else state.detailTitle=embed.type==='fitness-class'?String(embed.content.name??'Fitness class'):'Search classes';
          state.detailEmbed=embed;
          lines=embed.type==='fitness-class'?fitnessResultDetail(embed.content):fitnessSearchDetail(embed,aliasForEmbed(state,id));
        }else lines=await formatEmbedFullscreenLines(embed,cachedClient);
        if(request!==state.routeVersion)return true;
        state.detailLines=lines;
        } catch(error) {
          if(request!==state.routeVersion)return true;
          state.detailTitle="Saved embed unavailable";state.detailLines=[error instanceof Error ? error.message : String(error),"","Reconnect and use /refresh to retry."];state.detailEmbed=null;state.status=null;
        }
      }
      render(); return true;
    }
    case "/refresh": {
      if(state.workspace==="workflows"&&state.workflowInputSessionId){
        const request=state.routeVersion,sessionId=state.workflowInputSessionId;
        const session=await client.getWorkflowInputSession(sessionId);
        if(request!==state.routeVersion||sessionId!==state.workflowInputSessionId)return true;
        const workflow=session.workflow??session.workflows?.[0];
        if(workflow){state.activeWorkflow=workflow;state.screen="workflow";state.workflowTab="graph";state.workflowInputSessionId=null;state.status=session.message??"Workflow created.";}
        else {state.status=session.error??session.message??`Workflow creation: ${session.status}. /refresh to check again.`;if(["failed","cancelled"].includes(session.status))state.workflowInputSessionId=null;}
        render();
      }
      else if (state.screen === "project" && state.activeProject) await refreshOpenProject(context);
      else if (state.screen === "task" && state.activeTask) await openTask(context, state.activeTask.taskId);
      else if (state.screen === "chat" && state.activeChatId) await openSavedChat(context, state.activeChatId);
      else {if(isWorkspaceHome(state))await loadHomeData(state,client,render);await context.command(`/${state.workspace}`);}
      return true;
    }
    case "/workflow-edit": {
      const workflow = state.activeWorkflow, node = workflow?orderedWorkflowNodes(workflow.graph)[state.selectedWorkflowNodeIndex]:undefined;
      if (!workflow || !node || state.workflowTab !== "graph") throw new Error("Select a Template step first.");
      const request=state.routeVersion;
      const fallback=buildWorkflowNodeForm(workflow,node),values=JSON.stringify(fallback.fields);
      state.form=fallback;render();
      if(typeof client.listWorkflowCapabilities==='function'){
        await loadCachedTuiWorkspace(client,'workflows:capabilities',()=>client.listWorkflowCapabilities(),capabilities=>{
          // Metadata arriving late must never discard edits already made in the fallback form.
          if(request===state.routeVersion&&state.form===fallback&&!fallback.busy&&JSON.stringify(fallback.fields)===values)state.form=buildWorkflowNodeForm(workflow,node,capabilities);
          render();
        });
      }
      render(); return true;
    }
    case "/workflow-toggle": {
      if (!state.activeWorkflow) throw new Error("Open a workflow first.");
      const workflow=state.activeWorkflow,request=state.routeVersion,ownerCurrent=captureTuiWorkspaceOwner(client);
      await invalidateCachedTuiWorkspace(client,'workflows:list',ownerCurrent);await invalidateCachedTuiWorkspace(client,`workflow:${workflow.id}:detail`,ownerCurrent);
      if(!ownerCurrent())return true;
      const updated=await client.updateWorkflow(workflow.id,{enabled:!workflow.enabled});
      await writeCachedTuiWorkspace(client,`workflow:${workflow.id}:detail`,updated,ownerCurrent);
      if(!ownerCurrent())return true;
      const hasSummary=state.workflows.some(item=>item.id===updated.id);
      state.workflows=state.workflows.map(item=>item.id===updated.id?updated:item);
      if(hasSummary)await writeCachedTuiWorkspace(client,'workflows:list',state.workflows,ownerCurrent);
      if(request===state.routeVersion&&state.activeWorkflow?.id===workflow.id)state.activeWorkflow=updated;
      render();return true;
    }
    case "/stop": {
      if (!state.isBusy || !state.aiTaskId || !state.activeChatId) {state.status = state.isBusy ? "Waiting for the AI task to start before it can be stopped." : "No active response.";render();return true;}
      await client.cancelAITask(state.aiTaskId, state.activeChatId);
      state.status = "Stop requested."; render();return true;
    }
    case "/retry": {
      const message = [...state.messages].reverse().find((entry) => entry.role === "user");
      if (message) {state.input=message.content;state.focus="composer";state.status="Review the message, then press Enter to retry.";rememberDraft(state);}
      render();return true;
    }
    case "/task-create": case "/task-edit": case "/task-status": case "/task-activity": case "/task-assignee": case "/task-block": case "/task-delete": case "/task-reorder": {
      const task=selectedTask(state);
      if (name !== "/task-create" && !task) throw new Error("Select a task first.");
      if(name!=="/task-create")state.activeTask=task??null;
      state.form = buildTaskForm(name.slice(1), name === "/task-create" ? undefined : task ?? undefined); render(); return true;
    }
    default: return false;
  }
}

async function saveForm(context: WorkspaceContext): Promise<void> {
  const {state, client, render} = context, form = state.form;
  if (!form || form.busy) return;
  const request=state.routeVersion,ownerCurrent=captureTuiWorkspaceOwner(client),current=()=>ownerCurrent()&&request===state.routeVersion&&state.form===form;
  form.busy = true; form.error = undefined; render();
  try {
    if (form.kind === "composer-attach") {
      const path=formValue(form,"path").trim();
      if(!/^(?:\.\.?\/|~\/|\/)[^\s@]+$/.test(path))throw new Error("Use one explicit local path without spaces: ./, ../, ~/ or /.");
      if(!current())return;
      const cursor=state.inputCursor??state.input.length,before=state.input.slice(0,cursor),after=state.input.slice(cursor);
      const inserted=`${before&&!/\s$/.test(before)?" ":""}@${path}${after&&!/^\s/.test(after)?" ":""}`;
      state.input=before+inserted+after;state.inputCursor=before.length+inserted.length;
      rememberDraft(state);state.form=null;state.focus="composer";return;
    }
    if (form.kind === "app-skill-input") {
      if(!state.activeAppSkill)throw new Error("This skill is no longer open.");
      state.appPreparedRun=prepareTuiAppsSkillRun(state.activeAppSkill,form);state.form=buildTuiAppsRunConfirmation(state.appPreparedRun);render();return;
    }
    if(form.kind==="app-skill-confirm"){
      if(!state.appPreparedRun)throw new Error("Prepare this skill again before running.");const request=state.routeVersion;
      const result=await executeTuiAppsSkill(client,state.appPreparedRun,form);
      if(request!==state.routeVersion||state.form!==form)return;
      state.activeAppResult=result;state.screen="app-result";state.appPreparedRun=null;
      if(result.status!=="unsaved")state.appResults={...state.appResults,offset:0,items:[{embedId:result.embedId,appId:result.appId,skillId:result.skillId,status:result.status,createdAt:Math.floor(Date.now()/1000)},...state.appResults.items.filter((item)=>item.embedId!==result.embedId)]};
    }
    else if (form.kind === "workspace-search") { state.filter = formValue(form,"query"); state.selectedIndex = 0; state.scrollOffset = 0; }
    else if (form.kind.startsWith("task-")) {
      const projectId=state.workspace==='projects'?state.activeProject?.id:undefined;
      const before=state.activeTask,projectIds=new Set([...(before?.linkedProjectIds??[]),...(projectId?[projectId]:[])]);
      const snapshots=new Map<string,typeof state.tasks>();
      const allTasks=await readCachedTuiWorkspace<typeof state.tasks>(client,'tasks:list',ownerCurrent);
      if(allTasks)snapshots.set('tasks:list',allTasks);
      for(const id of projectIds){
        const key=`project:${id}:tasks`,saved=await readCachedTuiWorkspace<typeof state.tasks>(client,key,ownerCurrent);
        if(saved)snapshots.set(key,saved);
        await invalidateCachedTuiWorkspace(client,key,ownerCurrent);
      }
      await invalidateCachedTuiWorkspace(client,'tasks:list',ownerCurrent);
      if(!current())return;
      const result = await submitTaskForm(client, form, state.activeTask ?? undefined, state.workspace === "projects" ? state.activeProject?.id : undefined);
      if(!current())return;
      if (result.deleted) { state.tasks = state.tasks.filter((task) => task.taskId !== state.activeTask?.taskId); state.activeTask = null; state.screen = "tasks"; }
      if (result.task) {
        state.tasks = [result.task, ...state.tasks.filter((t) => t.taskId !== result.task!.taskId)]; state.activeTask = result.task; state.screen = "task";
        state.taskContext = null; state.status = result.task.queueState !== "none" ? `Queue: ${result.task.queueState}` : "Task saved.";
      }
      for(const [key,saved] of snapshots){
        const updated=saved.filter(task=>task.taskId!==before?.taskId&&task.taskId!==result.task?.taskId);
        if(result.task)updated.push(result.task);
        await writeCachedTuiWorkspace(client,key,updated,ownerCurrent);
      }
      await writeCachedTuiWorkspace(client,projectId?`project:${projectId}:tasks`:'tasks:list',state.tasks,ownerCurrent);
    } else if (form.kind.startsWith("project-")) {
      await invalidateCachedTuiWorkspace(client,'projects:list',ownerCurrent);
      if(!current())return;
      const project = await submitProjectForm(client, form);
      if(!current())return;
      state.projects = [project, ...state.projects.filter((p) => p.id !== project.id)]; state.activeProject = project;
      state.workspace = "projects"; state.screen = "project"; state.projectTab = "overview"; state.projectFiles = project.files;
      await writeCachedTuiWorkspace(client,'projects:list',state.projects,ownerCurrent);
      await writeCachedTuiWorkspace(client,`project:${project.id}:detail`,project,ownerCurrent);
    } else if(form.kind==="workflow-create"){
      const description=formValue(form,"description").trim();if(!description)throw new Error("Describe what this workflow should do.");
      const request=state.routeVersion,session=await client.startWorkflowInput({text:description,inputType:"text",optimisticSave:true,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,idempotencyKey:randomUUID()});
      if(request!==state.routeVersion||state.form!==form)return;
      const workflow=session.workflow??session.workflows?.[0];
      if(workflow){state.activeWorkflow=workflow;state.screen="workflow";state.workflowTab="graph";state.workflowInputSessionId=null;}
      else state.workflowInputSessionId=session.session_id;
      state.status=session.error??session.message??(workflow?"Workflow created.":"Creating workflow. Use /refresh to check progress.");
    } else if (form.kind.startsWith("workflow-")) {
      if (!state.activeWorkflow) throw new Error("Workflow is no longer selected.");
      await invalidateCachedTuiWorkspace(client,'workflows:list',ownerCurrent);
      await invalidateCachedTuiWorkspace(client,`workflow:${state.activeWorkflow.id}:detail`,ownerCurrent);
      if(!current())return;
      const workflow=await submitWorkflowNodeForm(client, state.activeWorkflow, form);
      await writeCachedTuiWorkspace(client,`workflow:${workflow.id}:detail`,workflow,ownerCurrent);
      if(!current())return;
      state.activeWorkflow=workflow;
      const hasSummary=state.workflows.some(item=>item.id===workflow.id);
      state.workflows=state.workflows.map(item=>item.id===workflow.id?workflow:item);
      if(hasSummary)await writeCachedTuiWorkspace(client,'workflows:list',state.workflows,ownerCurrent);
      state.status = "Workflow step saved.";
    }
    if(!current())return;
    state.form = null; state.focus = "content"; state.scrollOffset = 0;
  } catch (error) { form.error = error instanceof Error ? error.message : String(error); }
  finally { form.busy = false; render(); }
}

export async function handleWorkspaceKey(context: WorkspaceContext, chunk: string, key: TerminalKey): Promise<boolean> {
  const {state, render, client} = context;
  if(state.modelSelector?.open&&context.modelShell)return context.modelShell.key(chunk,key);
  if(key.meta&&key.name==='m'&&isTuiAiComposer(state)&&!state.form&&!state.settings&&!state.chrome&&!state.paletteOpen){
    if(context.modelShell)await context.modelShell.open();return true;
  }
  if(key.ctrl&&key.name==='g'){
    if(state.chrome&&'busy' in state.chrome&&state.chrome.busy)return true;
    state.chrome=null;
    state.questionEditor=null;state.textSelection=false;state.focus='navigation';state.navigationIndex=WORKSPACES.indexOf(state.workspace);render();return true;
  }
  if (key.ctrl && key.name === 'y') { state.textSelection = !state.textSelection;render();return true; }
  if (state.textSelection) {
    if(key.name==='escape'){state.textSelection=false;render();}
    return true;
  }
  if(state.chrome&&state.focus!=='navigation'&&await handleHeaderKey(context,chunk,key))return true;
  if(state.settings&&state.focus!=='navigation'&&await handleSettingsKey(context,chunk,key))return true;
  if(key.meta&&key.name==='h'&&isTuiFullscreen(state)){state.focus='header';state.headerActionIndex=0;render();return true;}
  if(state.focus==='header'){
    const controls=fullscreenHeaderControls(state,Math.max(1,context.terminal.width-4));
    if(key.name==='left'||key.name==='right'||key.name==='tab')state.headerActionIndex=(state.headerActionIndex+(key.name==='left'||key.shift?-1:1)+controls.length)%controls.length;
    else if(key.name==='return'){const control=controls[state.headerActionIndex];if(control)await context.command(control.command);}
    else if(key.name==='escape'){closeTuiFullscreen(state);}
    else if(key.ctrl&&key.name==='y')state.textSelection=!state.textSelection;
    else return true;
    render();return true;
  }
  if(state.focus!=='navigation'&&await handleQuestionKey(context,chunk,key))return true;
  if(state.focus==='navigation'&&['left','right','return','escape'].includes(key.name??'')){
    if(key.name==='left'||key.name==='right')state.navigationIndex=(state.navigationIndex+(key.name==='left'?-1:1)+WORKSPACES.length+1)%(WORKSPACES.length+1);
    else if(key.name==='return'){state.paletteOpen=false;await context.command(state.navigationIndex===WORKSPACES.length?"/settings":`/${WORKSPACES[state.navigationIndex]}`);}
    else state.focus=state.settings?'settings':state.screen==='chat'||state.screen==='example'?'composer':'content';
    render();return true;
  }
  if (state.form) {
    const form = state.form, field = form.fields[form.fieldIndex];
    if (!field) {if(key.name === "escape" && !form.busy) state.form=null;else if(key.name === "return" || key.ctrl && key.name === "s") await saveForm(context);render();return true;}
    if (key.name === "escape" && !form.busy) state.form = null;
    else if (key.ctrl && key.name === "s") await saveForm(context);
    else if (form.busy) return true;
    else if (key.name === "tab") form.fieldIndex = (form.fieldIndex + (key.shift ? -1 : 1) + form.fields.length) % form.fields.length;
    else if ((key.name === "left" || key.name === "right") && field.options) { const index = field.options.indexOf(field.value); field.value = field.options[(index + (key.name === "left" ? -1 : 1) + field.options.length) % field.options.length]; }
    else if (key.name === "backspace") field.value = eraseGrapheme(field.value);
    else if (key.name === "return") { if (key.meta && field.multiline) field.value += "\n"; else if (form.fieldIndex < form.fields.length - 1) form.fieldIndex++; else await saveForm(context); }
    else if (key.ctrl && key.name === "u") field.value = "";
    else if (!key.ctrl && !key.meta && chunk && !field.options) field.value += terminalText(chunk);
    render(); return true;
  }
  if (state.paletteOpen) {
    const actions = paletteActions(state.paletteQuery);
    if (key.name === "escape") state.paletteOpen = false;
    else if (key.name === "up" || key.name === "down") state.paletteIndex = Math.max(0, Math.min(actions.length - 1, state.paletteIndex + (key.name === "up" ? -1 : 1)));
    else if (key.name === "return") { const action = actions[state.paletteIndex]; state.paletteOpen = false; if (action) await context.command(action.command); }
    else if (key.name === "backspace") {state.paletteQuery = eraseGrapheme(state.paletteQuery); state.paletteIndex = 0;}
    else if (!key.ctrl && !key.meta && chunk) {state.paletteQuery += terminalText(chunk); state.paletteIndex = 0;}
    render(); return true;
  }
  if(state.screen==='results-view'&&state.focus==='content'&&!key.ctrl&&!key.meta&&['m','c','l'].includes(key.name??'')) {
    await context.command(`/view ${state.activeResultsView??1} ${{m:'map',c:'calendar',l:'list'}[key.name!]}`);return true;
  }
  if(state.screen==="embed" && state.embedChoices.length && state.focus==="content" && ["up","down"].includes(key.name ?? "")) {
    state.selectedIndex=Math.max(0,Math.min(state.embedChoices.length-1,state.selectedIndex+(key.name==="up"?-1:1)));render();return true;
  }
  if (key.ctrl && key.name === "b") { await handleWorkspaceCommand(context,"/sidebar"); return true; }
  if (key.ctrl && key.name === "p") { state.paletteOpen = true; state.paletteQuery = ""; state.paletteIndex = 0; render(); return true; }
  if (key.ctrl && key.name === "n") { await handleWorkspaceCommand(context,"/new"); return true; }
  if(key.ctrl && key.name==="o" && isWorkspaceHome(state)){state.focus="inspiration";state.scrollOffset=0;render();return true;}
  if (state.workflowEdit) return false;
  const chatHome=state.screen==="start"||state.screen==="chats", carouselHome=chatHome||['apps','projects','workflows'].includes(state.screen);
  if(['chat','example'].includes(state.screen)&&state.focus==='content'&&['left','right','return'].includes(key.name??'')){
    const refs=chatEmbedReferences(state);
    if(refs.length){
      const selected=Math.max(0,refs.findIndex(ref=>ref.value===state.chatSelectedEmbedId));
      if(key.name==='return')await context.command(`/embed ${aliasForEmbed(state,refs[selected].value)}`);
      else {state.chatSelectedEmbedId=refs[Math.max(0,Math.min(refs.length-1,selected+(key.name==='left'?-1:1)))].value;state.followSelection=true;}
      render();return true;
    }
  }
  if (state.focus === 'sidebar' && ['pageup','pagedown','home','end','scrollup','scrolldown'].includes(key.name ?? '')) {
    const direction = ['pageup','scrollup'].includes(key.name ?? '') ? -1 : 1;
    const step = key.name?.startsWith('page') ? Math.max(1,(context.terminal.height ?? 24)-9) : 3;
    const edge = key.name === 'home' ? 'first' : key.name === 'end' ? 'last' : undefined;
    if (state.workspace === 'chats') moveTuiChatSidebarSelection(state, direction * step, edge);
    else {
      const count = state.workspace === 'projects' ? state.projects.length : state.workspace === 'tasks' ? state.tasks.length : state.workspace === 'apps' ? state.apps.length : state.workflows.length;
      state.sidebarIndex = edge === 'first' ? 0 : edge === 'last' ? Math.max(0,count-1) : Math.max(0,Math.min(Math.max(0,count-1),state.sidebarIndex + direction * step));
    }
    render(); return true;
  }
  if (["pageup","pagedown","home","end","scrollup","scrolldown"].includes(key.name ?? "") || (carouselHome || state.screen==="project"&&state.projectTab==="overview") && ["up","down"].includes(key.name??"") && ["composer","content"].includes(state.focus) && !state.input.startsWith("/")) {
    const bottom=state.screen==="chat";
    state.followSelection=false;
    if(key.name==="home")state.scrollOffset=bottom?10000:0;
    else if(key.name==="end")state.scrollOffset=bottom?0:10000;
    else {
      const direction=["pageup","scrollup","up"].includes(key.name??"")?-1:1;
      const step=key.name?.startsWith("page")?Math.max(1,(context.terminal.height??24)-9):key.name?.startsWith("scroll")?3:1;
      state.scrollOffset=Math.max(0,state.scrollOffset+direction*(bottom?-step:step));
    }
    render();return true;
  }
  if (key.name === "escape") {
    if (state.chatProjectBusy) return true;
    if (state.chatProjectOperation) { state.chatProjectOperation = null; state.status = null; render(); return true; }
    if (state.focus === "sidebar") { state.sidebarOpen = false; state.focus = chatHome ? "content" : state.workspace === "chats" ? "composer" : "content"; }
    else if (state.screen === "task") {state.screen = state.workspace === "projects" ? "project" : "tasks"; state.focus = "content"; state.scrollOffset = 0;}
    else if (state.screen === "workflow") {state.screen = "workflows"; state.focus = "content"; state.scrollOffset = 0;}
    else if (state.screen === "project") {state.screen = "projects"; state.focus = "content"; state.scrollOffset = 0;}
    else if(state.screen==="app-result"){state.screen=state.activeAppSkill?"app-skill":"app";state.appSkillTab="embeds";state.appTab="embeds";state.focus="content";state.scrollOffset=0;}
    else if(state.screen==="app-skill"){state.screen="app";state.appTab="skills";state.focus="content";state.scrollOffset=0;}
    else if(state.screen==="app"){state.screen="apps";state.focus="content";state.scrollOffset=0;}
    else if (closeTuiFullscreen(state)) { /* Restore the actual origin and its draft. */ }
    else { state.input = ""; state.focus = state.workspace === "chats" ? "composer" : "content"; }
    render(); return true;
  }
  if (key.name === "tab") {
    if (state.input.startsWith("/")) {const choices = TUI_ACTIONS.filter((a) => a.command.startsWith(state.input)); if (choices.length) state.input = choices[state.paletteIndex % choices.length].command + " ";}
    else {const focuses = ["content","composer",...(isWorkspaceHome(state)?["inspiration"]:[]),...(state.sidebarOpen?["sidebar"]:[]),...(isTuiFullscreen(state)?["header"]:[]),"navigation"] as TuiState["focus"][]; state.focus = focuses[(focuses.indexOf(state.focus) + (key.shift ? -1 : 1) + focuses.length) % focuses.length];}
    render(); return true;
  }
  if(state.focus==="inspiration"){
    if(key.name==="left"||key.name==="right"){
      const count=Math.max(1,workspaceInspirations(state).length);state.inspirationIndices[state.workspace]=((state.inspirationIndices[state.workspace]??0)+(key.name==="left"?-1:1)+count)%count;
    } else if(key.name==="return")await context.command("/inspiration");
    render();return true;
  }
  if(carouselHome&&state.focus==="content"&&(key.name==="left"||key.name==="right")){
    const count=chatHome?homeContinueItems(state).length:state.screen==='projects'?filteredProjects(state.projects,state.filter).length:state.screen==='workflows'?state.workflows.filter(w=>w.title.toLowerCase().includes(state.filter.toLowerCase())).length:homeTuiApps(state.apps,state.filter,state.homeShowAll).length;
    state.homeSelectionMoved=true;
    state.selectedIndex=Math.max(0,Math.min(Math.max(0,count-1),state.selectedIndex+(key.name==="left"?-1:1)));
    state.followSelection=true;render();return true;
  }
  // Typing from the home previews starts a draft; Enter still opens the selected card.
  if(chatHome&&state.focus==="content"&&!key.ctrl&&!key.meta&&chunk&&chunk>=" "&&key.name!=="return")state.focus="composer";
  if(state.focus==="content"&&(["up","down","return"].includes(key.name??"")||state.screen==="workflow"&&["g","r","e","E","x","c"].includes(chunk)))state.followSelection=true;
  if (state.focus === "navigation") {
    if (key.name === "left" || key.name === "right") state.navigationIndex = (state.navigationIndex + (key.name === "left" ? -1 : 1) + WORKSPACES.length) % WORKSPACES.length;
    else if (key.name === "return") await context.command(`/${WORKSPACES[state.navigationIndex]}`);
    else if (chunk !== "/") return true;
    render(); if (chunk !== "/") return true;
  }
  if (state.focus === "sidebar") {
    const chatRows = tuiChatSidebarRows(state);
    const count = state.workspace === "chats" ? chatRows.length : state.workspace === "projects" ? state.projects.length : state.workspace === "tasks" ? state.tasks.length : state.workspace==="apps"?state.apps.length:state.workflows.length;
    if (key.name === "up" || key.name === "down") {
      if (state.workspace === 'chats') moveTuiChatSidebarSelection(state, key.name === 'up' ? -1 : 1);
      else state.sidebarIndex = Math.max(0, Math.min(Math.max(0,count - 1), state.sidebarIndex + (key.name === 'up' ? -1 : 1)));
    }
    else if (key.name === "return") {
      if (state.workspace === 'chats') {
        if (state.chatProjectBusy) return true;
        const row = chatRows[state.sidebarIndex];
        if (row?.kind === 'new') await context.command('/new');
        else if (row?.kind === 'chat') await context.command(`/chat ${row.chatId}`);
        else if (row?.kind === 'path') state.chatSidebarAncestors = !state.chatSidebarAncestors;
        else if (row?.kind === 'create' && state.chatProjectOperation) await context.command(`/chat-create-project ${state.chatProjectOperation.chatIds.join(' ')}`);
        else if (row?.kind === 'choose' && state.chatProjectOperation) {
          const operation = state.chatProjectOperation;
          state.chatProjectBusy = true;
          try {
            await placeTuiChats(state, client, operation.chatIds, { projectId: row.projectId!, folderId: row.folderId ?? null }, operation.mode);
            state.chatProjectOperation = null; state.status = null;
          } finally { state.chatProjectBusy = false; await refreshTuiChatSidebar(state, client, render, true); }
        } else if (row && ['project','folder','up'].includes(row.kind)) {
          state.chatSidebarLocation = row.kind === 'up' && row.folderId === undefined ? null : { projectId: row.projectId!, folderId: row.folderId ?? null };
          state.chatSidebarAncestors = false; state.sidebarIndex = 0;
        }
      }
      else if (state.workspace === "projects") await context.command(`/project ${state.projects[state.sidebarIndex]?.id}`);
      else if (state.workspace === "tasks") await openTask(context,state.tasks[state.sidebarIndex]?.taskId ?? "");
      else if (state.workspace === "workflows") await context.command(`/workflow ${state.workflows[state.sidebarIndex]?.id}`);
      else if(state.workspace==="apps")await context.command(`/app ${state.apps[state.sidebarIndex]?.id}`);
    } else if (chunk !== "/") return true;
    render(); if (chunk !== "/") return true;
  }
  if(state.focus==="content"&&state.workspace==="apps"){
    if(state.screen==="app-result"&&(key.name==="up"||key.name==="down")){state.scrollOffset=Math.max(0,state.scrollOffset+(key.name==="up"?-1:1));render();return true;}
    if(state.screen==="app"&&/^[1-5]$/.test(chunk)){
      ++state.routeVersion;
      state.appTab=(["skills","focus_modes","settings_memories","embeds","workflows"] as const)[Number(chunk)-1];state.selectedIndex=0;state.scrollOffset=0;
      if(state.appTab==="embeds")await context.command("/app-results");if(state.appTab==="workflows")await context.command("/app-workflows");render();return true;
    }
    if(state.screen==="app-skill"&&/^[1-3]$/.test(chunk)){
      ++state.routeVersion;
      state.appSkillTab=(["overview","embeds","workflows"] as const)[Number(chunk)-1];state.selectedIndex=0;state.scrollOffset=0;
      if(state.appSkillTab==="embeds")await context.command("/app-results");if(state.appSkillTab==="workflows")await context.command("/app-workflows");render();return true;
    }
    const resultsTab=state.screen==="app"?state.appTab==="embeds":state.screen==="app-skill"&&state.appSkillTab==="embeds";
    const workflowsTab=state.screen==="app"?state.appTab==="workflows":state.screen==="app-skill"&&state.appSkillTab==="workflows";
    const count=state.screen==="apps"?homeTuiApps(state.apps,state.filter,state.homeShowAll).length:resultsTab?state.appResults.items.length:workflowsTab?state.appWorkflows.items.length:state.activeApp?.skills.length??0;
    if(key.name==="up"||key.name==="down"){state.selectedIndex=Math.max(0,Math.min(count-1,state.selectedIndex+(key.name==="up"?-1:1)));render();return true;}
    if(key.name==="return"){
      if(state.screen==="apps"){const app=homeTuiApps(state.apps,state.filter,state.homeShowAll)[state.selectedIndex];if(app)await context.command(`/app ${app.id}`);}
      else if(resultsTab){const result=state.appResults.items[state.selectedIndex];if(result)await context.command(`/app-result ${result.embedId}`);}
      else if(workflowsTab){const workflow=state.appWorkflows.items[state.selectedIndex];if(workflow)await context.command(`/workflow ${workflow.id}`);}
      else if(state.screen==="app-skill")await context.command("/app-run");
      else if(state.appTab==="skills"&&state.activeApp){const skill=state.activeApp.skills[state.selectedIndex];if(skill)await context.command(`/app-skill ${state.activeApp.id}/${skill.id}`);}
      return true;
    }
    if((chunk==="]"||chunk==="[")&&resultsTab){await context.command(`/app-results ${Math.max(0,state.appResults.offset+(chunk==="]"?20:-20))}`);return true;}
    if((chunk==="]"||chunk==="[")&&workflowsTab){await context.command(`/app-workflows ${Math.max(0,state.appWorkflows.offset+(chunk==="]"?20:-20))}`);return true;}
  }
  if (chunk === "/" && !state.input) {state.focus = "composer"; state.input = "/"; state.inputCursor = null; render(); return true;}
  if (state.input.startsWith("/") && key.name === "return") {const command=state.input.trim(); state.input=""; state.inputCursor=null; await context.command(command); return true;}
  if (state.focus === "content" && state.screen === "project") {
    if (key.name === "backspace" && state.projectTab === "files" && state.activeProject) {
      const project=state.activeProject;
      const folderId=state.projectFolderId?parentTuiProjectFolderId(project,state.projectFolderId):null;
      const path=state.projectSourceId?state.projectPath.split("/").slice(0,-1).join("/")||".":"";
      ++state.routeVersion;state.projectFiles=[];state.projectFolderId=folderId;state.projectPath=path;state.selectedIndex=0;state.filter='';render();
      await projectFiles(context,project,state.projectSourceId?{sourceId:state.projectSourceId,path}:{folderId:folderId??undefined});
      render();return true;
    }
    if (["1", "2", "3"].includes(chunk)) {
      // An early tab key must not invalidate the pending Project detail request.
      if(!state.activeProject)return true;
      ++state.routeVersion;const projectId=state.activeProject?.id;
      state.projectTab = chunk === "1" ? "overview" : chunk === "2" ? "files" : "tasks"; state.selectedIndex = 0; state.scrollOffset = 0;
      if (state.projectTab === "tasks" && projectId) {state.tasks=[];render();await projectTasks(context,projectId);}
      else if(state.projectTab==='files'&&state.activeProject)await projectFiles(context,state.activeProject,{folderId:state.projectFolderId??undefined,sourceId:state.projectSourceId??undefined,path:state.projectSourceId?state.projectPath:undefined});
      render(); return true;
    }
    if (chunk === "n") {await context.command("/project-chat"); return true;}
    if (key.name === "return") {
      if (state.projectTab === "tasks") {const task=filterTasks(state.tasks,state.filter)[state.selectedIndex]; if(task) await openTask(context,task.taskId);}
      else if (state.projectTab === "files" && state.activeProject) {
        const file=filteredProjectFiles(state.projectFiles,state.filter)[state.selectedIndex],project=state.activeProject,request=state.routeVersion;
        if (file?.kind === "folder") {++state.routeVersion;state.projectPath=file.path;state.projectFolderId=file.sourceId?null:file.id;state.projectSourceId=file.sourceId??null;state.projectFiles=[];state.selectedIndex=0;state.filter='';render();await projectFiles(context,project,file.sourceId?{path:file.path,sourceId:file.sourceId}:{folderId:file.id});}
        else if(file) {const text=await readTuiProjectFile(context.client,project,file);if(request===state.routeVersion&&state.activeProject?.id===project.id){state.detailTitle=file.name;state.detailLines=text.split("\n");state.screen="embed";state.scrollOffset=0;}}
      }
      render();return true;
    }
  }
  if (state.focus === "content" && (state.screen === "task" || state.screen === "tasks")) {
    if(state.screen==="tasks"&&(key.name==="left"||key.name==="right")){
      const selected=selectedTask(state),current=TASK_STATUSES.indexOf((state.taskStatusFilter||selected?.status||"todo") as UserTaskStatus);
      state.taskStatusFilter=TASK_STATUSES[(current+(key.name==="left"?-1:1)+TASK_STATUSES.length)%TASK_STATUSES.length];state.selectedIndex=0;state.scrollOffset=0;render();return true;
    }
    const kinds:Record<string,string>={c:"task-create",e:"task-edit",m:"task-status",a:"task-activity",s:"task-start",d:"task-complete",b:"task-block",u:"task-unblock",k:"task-skip",x:"task-delete",r:"task-reorder",p:"task-assignee"};
    if(kinds[chunk]) {const task=selectedTask(state);if(chunk!=="c"&&!task)return true;if(chunk!=="c")state.activeTask=task??null;state.form=buildTaskForm(kinds[chunk],chunk==="c"?undefined:task??undefined);render();return true;}
  }
  if (state.focus === "content" && state.screen === "workflow" && chunk === "E") {await context.command("/workflow-edit");return true;}
  if (state.focus === "content" && state.screen === "workflow" && chunk === "t") {await context.command("/workflow-toggle");return true;}
  if (state.focus === "content" && (key.name === "up" || key.name === "down") && ["start","tasks","projects","project","chats"].includes(state.screen)) {
    const count=state.screen==="tasks"||state.screen==="project"&&state.projectTab==="tasks" ? filterTasks(state.tasks,state.filter,state.taskStatusFilter as UserTaskStatus||undefined).length
      :state.screen==="projects"?filteredProjects(state.projects,state.filter).length
      :state.screen==="project"?filteredProjectFiles(state.projectFiles,state.filter).length:homeContinueItems(state).length;
    state.selectedIndex=Math.max(0,Math.min(count-1,state.selectedIndex+(key.name==="up"?-1:1)));render();return true;
  }
  if (state.focus === "content" && key.name === "return") {
    if (state.screen === "tasks") {const task=filterTasks(state.tasks,state.filter,state.taskStatusFilter as UserTaskStatus||undefined)[state.selectedIndex];if(task)await openTask(context,task.taskId);return true;}
    if (state.screen === "projects") {const project=filteredProjects(state.projects,state.filter)[state.selectedIndex];if(project)await openProject(context,project.id);return true;}
    if (state.screen === "chats"||state.screen==="start") {
      const item=homeContinueItems(state)[state.selectedIndex];
      if(item?.kind==="embed")await context.command(`/embed ${item.embedId}`);
      else if(item){const chat=item.chat;if(chat.source==="example")await context.command(`/example ${chat.slug||chat.id}`);else await openSavedChat(context,chat.id);}
      return true;
    }
    if(state.screen==="embed" && state.embedChoices.length){await context.command(`/embed ${state.embedChoices[state.selectedIndex]}`);return true;}
  }
  if (state.focus === "composer") {
    if(key.name==='return'&&state.workspace==='chats'&&state.isBusy&&!state.input.startsWith('/')){
      rememberDraft(state);state.status='The previous reply is still running. Your draft is kept.';render();return true;
    }
    if (key.name === "return" && state.workspace !== "chats") {
      const value=state.input.trim();state.input="";state.inputCursor=null;
      if(value&&state.screen==="projects"){state.form=buildProjectForm();const name=state.form.fields.find((f)=>f.name==="name");if(name)name.value=value;}
      else if(value&&state.screen==="tasks"){state.form=buildTaskForm("task-create");const title=state.form.fields.find((f)=>f.name==="title");if(title)title.value=value;}
      else if(value&&state.screen==="workflows")await context.command(`/workflow-create ${value}`);
      else state.filter=value;
      state.selectedIndex=0;state.scrollOffset=0;state.focus="content";render();return true;
    }
    if (key.name === "return" && state.screen === "chats" && state.input.trim()) {
      const text=state.input.trim();newChat(state);await context.send(text);return true;
    }
    const cursor = state.inputCursor ?? state.input.length;
    if (key.name === "left" || key.name === "right") {state.inputCursor=moveGraphemeCursor(state.input,cursor,key.name==="left"?-1:1);render();return true;}
    if (key.ctrl && key.name === "u") {state.input="";state.inputCursor=null;rememberDraft(state);render();return true;}
    if (key.ctrl && key.name === "a") {state.inputCursor=0;render();return true;}
    if (key.ctrl && key.name === "e") {state.inputCursor=state.input.length;render();return true;}
    if (key.name === "backspace") {const before=eraseGrapheme(state.input.slice(0,cursor));state.input=before+state.input.slice(cursor);state.inputCursor=before.length;rememberDraft(state);render();return true;}
    if ((key.meta && key.name === "return") || key.ctrl && key.name === "j") {state.input=state.input.slice(0,cursor)+"\n"+state.input.slice(cursor);state.inputCursor=cursor+1;rememberDraft(state);render();return true;}
    if (key.name === "paste" || !key.ctrl && !key.meta && chunk && chunk >= " ") {
      const text=terminalText(chunk);state.input=state.input.slice(0,cursor)+text+state.input.slice(cursor);state.inputCursor=cursor+text.length;rememberDraft(state);
      if (context.modelShell && isTuiAiComposer(state) && /\s/.test(text) && !state.input.startsWith("/"))
        await context.modelShell.consumeMention(state.input);
      render();return true;
    }
  }
  return false;
}
