/** Workspace navigation and forms reuse the encrypted client contracts. */
import { parseEmbedContentObject, type OpenMatesClient, type UserTaskStatus } from "./client.js";
import { randomUUID } from "node:crypto";
import type { TuiState, TuiScreen, TuiWorkspace } from "./tuiRenderer.js";
import type { TuiTerminal, TerminalKey } from "./tuiTerminal.js";
import { buildTaskForm, filterTasks, loadTaskContext, submitTaskForm } from "./tuiTasksWorkspace.js";
import { loadTuiProjects, loadTuiProject, loadTuiProjectFiles, readTuiProjectFile, buildProjectForm, submitProjectForm, filteredProjectFiles, parentTuiProjectFolderId } from "./tuiProjectsWorkspace.js";
import { buildWorkflowNodeForm, submitWorkflowNodeForm } from "./tuiWorkflowWorkspace.js";
import { decryptUserTasks, TASK_STATUSES } from "./tasksCli.js";
import { formValue } from "./tuiForms.js";
import { WORKSPACES, workspaceGeometry } from "./tuiLayout.js";
import { tuiChatSidebarRows, refreshTuiChatSidebar, placeTuiChats, createTuiChatProject } from './tuiChatSidebar.js';
import { encryptWithAesGcmCombined } from './crypto.js';
import { paletteActions, TUI_ACTIONS } from "./tuiActions.js";
import { eraseGrapheme, moveGraphemeCursor, terminalText } from "./tuiText.js";
import { formatEmbedPreviewLines } from "./embedRenderers.js";
import { currentInspiration, homeChatItems, isWorkspaceHome, loadHomeData, workspaceInspirations } from "./tuiHome.js";
import { loadTuiApps, homeTuiApps, loadTuiAppsSkill, buildTuiAppsSkillForm, prepareTuiAppsSkillRun, buildTuiAppsRunConfirmation, executeTuiAppsSkill, loadTuiAppsResults, loadTuiAppsResult, loadTuiAppsWorkflows } from "./tuiAppsWorkspace.js";

export type WorkspaceContext = {
  state: TuiState; client: OpenMatesClient; terminal: TuiTerminal; render: () => void;
  command: (command: string) => Promise<void>; send: (message: string) => Promise<void>;
};

function chatDraftKey(state: TuiState) { return state.screen === "example" ? `example:${state.activeExample?.chat.id}` : state.activeChatId ?? "new"; }
function selectedTask(state:TuiState) {return state.screen==="tasks"?filterTasks(state.tasks,state.filter,state.taskStatusFilter as UserTaskStatus||undefined)[state.selectedIndex]:state.activeTask;}
export function rememberDraft(state: TuiState): void {
  if (state.workspace === "chats" && !state.input.startsWith("/")) state.drafts[chatDraftKey(state)] = state.input;
}
export function route(state: TuiState, workspace: TuiWorkspace, screen: TuiScreen): number {
  if (state.input) rememberDraft(state);
  state.workspace = workspace; state.screen = screen;
  state.navigationIndex = WORKSPACES.indexOf(workspace); state.focus = workspace === "chats" && !["start","chats"].includes(screen) ? "composer" : "content";
  state.input = ""; state.inputCursor = null; state.filter = ""; state.scrollOffset = 0; state.selectedIndex = 0;
  state.sidebarIndex = 0;
  state.homeShowAll = false;
  state.status = null;
  state.form = null; state.workflowEdit = null;
  return ++state.routeVersion;
}
function newChat(state: TuiState): void {
  route(state, "chats", "start");
  state.activeChatId = null; state.activeChat = null; state.activeExample = null;
  state.messages = []; state.headerState = "new"; state.headerError = null; state.followUpSuggestions = [];
  state.input = state.drafts.new ?? "";
}
async function recent(context: WorkspaceContext): Promise<void> {
  const {state, client, render} = context;
  if (!state.signedIn || typeof client.listChats !== "function") return;
  const request=state.routeVersion,homeRequest=state.homeLoadVersion;
  const chats=(await client.listChats(50, 1)).chats;
  if(request!==state.routeVersion||homeRequest!==state.homeLoadVersion||!state.signedIn)return;
  state.recentChats = chats;
  render();
  await refreshTuiChatSidebar(state, client, render, true);
}

export async function openSavedChat(context: WorkspaceContext, id: string): Promise<void> {
  const {state, client, render} = context;
  const request = route(state, "chats", "chat");
  state.status = "Loading chat…"; render();
  const result = await client.getChatMessages(id);
  if (state.routeVersion !== request) return;
  state.activeChatId = result.chat.id; state.activeChat = result.chat; state.activeExample = null;
  state.selectedProjectId = null;
  state.messages = result.messages.map((m) => ({role: m.role === "user" ? "user" : m.role === "system" ? "system" : "assistant", content: m.content, title: m.senderName, embedIds: m.embedIds}));
  state.headerState = "ready"; state.headerError = null;
  const remoteDraft = state.drafts[id] === undefined && typeof client.getDraft === "function" ? await client.getDraft(result.chat.id) : null;
  if (state.routeVersion !== request) return;
  state.input = state.drafts[result.chat.id] ?? remoteDraft?.markdown ?? "";
  state.status = null; render();
}
async function openProject(context: WorkspaceContext, id: string): Promise<void> {
  const {state, client, render} = context;
  const request = route(state, "projects", "project");
  state.status = "Loading Project…"; render();
  const project = await loadTuiProject(client, id);
  if (state.routeVersion !== request) return;
  const files = await loadTuiProjectFiles(client, project);
  if (state.routeVersion !== request) return;
  state.activeProject = project; state.projectFiles = files; state.projectTab = "overview"; state.projectPath = ""; state.projectFolderId = null; state.projectSourceId = null;
  state.status = null; render();
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

export async function handleWorkspaceCommand(context: WorkspaceContext, command: string): Promise<boolean> {
  const {state, client, render} = context;
  const space = command.indexOf(" ");
  const name = space < 0 ? command : command.slice(0, space);
  const arg = space < 0 ? "" : command.slice(space + 1).trim();
  switch (name) {
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
      const selected = state.focus === 'sidebar' ? tuiChatSidebarRows(state)[state.sidebarIndex]?.chatId :
        ['start','chats'].includes(state.screen) ? homeChatItems(state)[state.selectedIndex]?.id : state.activeChatId;
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
    case "/sidebar": state.sidebarOpen = !state.sidebarOpen; state.focus = state.sidebarOpen ? "sidebar" : state.workspace === "chats" && !["start","chats"].includes(state.screen) ? "composer" : "content"; render(); if (state.sidebarOpen) await recent(context); return true;
    case "/chats": route(state, "chats", "chats"); await recent(context); render(); return true;
    case "/chat": if (!arg) return handleWorkspaceCommand(context, "/chats"); await openSavedChat(context, arg); return true;
    case "/projects": {
      const request = route(state, "projects", "projects"); state.status = "Loading Projects…"; render();
      const projects = await loadTuiProjects(client);
      if (request === state.routeVersion) { state.projects = projects; state.status = null; }
      render(); return true;
    }
    case "/project": if (!arg) return handleWorkspaceCommand(context, "/projects"); await openProject(context, arg); return true;
    case "/project-create": state.form = buildProjectForm(); render(); return true;
    case "/workflow-create": state.form={kind:"workflow-create",title:"Describe new workflow",fieldIndex:0,fields:[{name:"description",label:"What do you want to automate?",value:arg,multiline:true}]};render();return true;
    case "/project-source": {
      if (!state.activeProject) throw new Error("Open a Project first.");
      if (!arg) {state.status = state.activeProject.sources.map((source) => `${source.name ?? source.id}: /project-source ${source.id}`).join("  ") || "This Project has no connected sources.";render();return true;}
      const request = state.routeVersion, project = state.activeProject;
      const files = await loadTuiProjectFiles(client, project, {sourceId:arg, path:"."});
      if (request === state.routeVersion) {state.projectFiles=files;state.projectTab="files";state.projectSourceId=arg;state.projectFolderId=null;state.projectPath=".";state.selectedIndex=0;state.filter="";}
      render(); return true;
    }
    case "/project-chat": {
      const project = state.activeProject;
      if (!project) throw new Error("Open a Project first.");
      newChat(state); state.selectedProjectId = project.id; state.activeProject = project;
      state.status = `Chat in Project: ${project.name}`; render(); return true;
    }
    case "/search": {
      if (arg) { state.filter = arg; state.selectedIndex = 0; state.scrollOffset = 0; render(); }
      else state.form = { kind: "workspace-search", title: `Search ${state.workspace}`, fields: [{name:"query", label:"Search", value:state.filter}], fieldIndex:0 };
      render(); return true;
    }
    case "/embed": {
      const request = route(state, state.workspace, "embed"); state.detailTitle = "Embeds";
      if (!arg) {
        const ids = [...new Set(state.messages.flatMap((message) => message.embedIds ?? []))];
        state.detailLines = ids.length ? ids.map((id) => `/embed ${id}`) : ["No saved embeds in this chat yet."];
      } else {
        const example = state.activeExample?.embeds?.find((embed) => embed.embed_id === arg);
        const content = example ? parseEmbedContentObject(example.content) : null;
        const embed = example && content ? {id:arg, embedId:arg, type:example.type, content, textPreview:null,
          appId:typeof content.app_id==="string"?content.app_id:null, skillId:typeof content.skill_id==="string"?content.skill_id:null, createdAt:null} : await client.getEmbed(arg);
        if (request !== state.routeVersion) return true;
        state.detailTitle = embed.textPreview || (embed.appId ? `${embed.appId}${embed.skillId ? `/${embed.skillId}` : ""}` : embed.type?.replaceAll("_", " ")) || "Embed";
        const body = embed.content as Record<string, unknown>;
        const text = ["code", "markdown", "content", "text", "transcript"].map((key) => body?.[key]).find((value) => typeof value === "string");
        state.detailLines = typeof text === "string" ? text.split("\n") : formatEmbedPreviewLines(embed, 100);
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
      else if (state.screen === "project" && state.activeProject) await openProject(context, state.activeProject.id);
      else if (state.screen === "task" && state.activeTask) await openTask(context, state.activeTask.taskId);
      else if (state.screen === "chat" && state.activeChatId) await openSavedChat(context, state.activeChatId);
      else {if(isWorkspaceHome(state))await loadHomeData(state,client,render);await context.command(`/${state.workspace}`);}
      return true;
    }
    case "/workflow-edit": {
      const workflow = state.activeWorkflow, node = workflow?.graph.nodes[state.selectedWorkflowNodeIndex];
      if (!workflow || !node || state.workflowTab !== "graph") throw new Error("Select a Template step first.");
      state.form = buildWorkflowNodeForm(workflow, node); render(); return true;
    }
    case "/workflow-toggle": {
      if (!state.activeWorkflow) throw new Error("Open a workflow first.");
      state.activeWorkflow = await client.updateWorkflow(state.activeWorkflow.id, {enabled: !state.activeWorkflow.enabled}); render(); return true;
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
  form.busy = true; form.error = undefined; render();
  try {
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
      const result = await submitTaskForm(client, form, state.activeTask ?? undefined, state.workspace === "projects" ? state.activeProject?.id : undefined);
      if (result.deleted) { state.tasks = state.tasks.filter((task) => task.taskId !== state.activeTask?.taskId); state.activeTask = null; state.screen = "tasks"; }
      if (result.task) {
        state.tasks = [result.task, ...state.tasks.filter((t) => t.taskId !== result.task!.taskId)]; state.activeTask = result.task; state.screen = "task";
        state.taskContext = null; state.status = result.task.queueState !== "none" ? `Queue: ${result.task.queueState}` : "Task saved.";
      }
    } else if (form.kind.startsWith("project-")) {
      const project = await submitProjectForm(client, form);
      state.projects = [project, ...state.projects.filter((p) => p.id !== project.id)]; state.activeProject = project;
      state.workspace = "projects"; state.screen = "project"; state.projectTab = "overview"; state.projectFiles = project.files;
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
      state.activeWorkflow = await submitWorkflowNodeForm(client, state.activeWorkflow, form);
      state.status = "Workflow step saved.";
    }
    state.form = null; state.focus = "content"; state.scrollOffset = 0;
  } catch (error) { form.error = error instanceof Error ? error.message : String(error); }
  finally { form.busy = false; render(); }
}

export async function handleWorkspaceKey(context: WorkspaceContext, chunk: string, key: TerminalKey): Promise<boolean> {
  const {state, render, client} = context;
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
  if (key.ctrl && key.name === "b") { await handleWorkspaceCommand(context,"/sidebar"); return true; }
  if (key.ctrl && key.name === "p") { state.paletteOpen = true; state.paletteQuery = ""; state.paletteIndex = 0; render(); return true; }
  if (key.ctrl && key.name === "n") { await handleWorkspaceCommand(context,"/new"); return true; }
  if(key.ctrl && key.name==="o" && isWorkspaceHome(state)){state.focus="inspiration";state.scrollOffset=0;render();return true;}
  if (state.workflowEdit) return false;
  const chatHome=state.screen==="start"||state.screen==="chats", carouselHome=chatHome||state.screen==="apps";
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
    else if (state.screen === "embed") {state.screen = state.workspace === "projects" ? "project" : "chat"; state.focus = state.workspace === "chats" ? "composer" : "content";}
    else { state.input = ""; state.focus = state.workspace === "chats" ? "composer" : "content"; }
    render(); return true;
  }
  if (key.name === "tab") {
    if (state.input.startsWith("/")) {const choices = TUI_ACTIONS.filter((a) => a.command.startsWith(state.input)); if (choices.length) state.input = choices[state.paletteIndex % choices.length].command + " ";}
    else {const focuses = ["content","composer",...(isWorkspaceHome(state)?["inspiration"]:[]),...(state.sidebarOpen?["sidebar"]:[]),"navigation"] as TuiState["focus"][]; state.focus = focuses[(focuses.indexOf(state.focus) + (key.shift ? -1 : 1) + focuses.length) % focuses.length];}
    render(); return true;
  }
  if(state.focus==="inspiration"){
    if(key.name==="left"||key.name==="right"){
      const count=Math.max(1,workspaceInspirations(state).length);state.inspirationIndices[state.workspace]=((state.inspirationIndices[state.workspace]??0)+(key.name==="left"?-1:1)+count)%count;
    } else if(key.name==="return")await context.command("/inspiration");
    render();return true;
  }
  if(carouselHome&&state.focus==="content"&&(key.name==="left"||key.name==="right")){
    const count=chatHome?homeChatItems(state).length:homeTuiApps(state.apps,state.filter,state.homeShowAll).length;
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
    if (key.name === "up" || key.name === "down") state.sidebarIndex = Math.max(0, Math.min(count - 1, state.sidebarIndex + (key.name === "up" ? -1 : 1)));
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
      const request=state.routeVersion, project=state.activeProject;
      const folderId=state.projectFolderId?parentTuiProjectFolderId(project,state.projectFolderId):null;
      const path=state.projectSourceId?state.projectPath.split("/").slice(0,-1).join("/")||".":"";
      const files=await loadTuiProjectFiles(context.client,project,state.projectSourceId?{sourceId:state.projectSourceId,path}:{folderId:folderId??undefined});
      if(request===state.routeVersion){state.projectFiles=files;state.projectFolderId=folderId;state.projectPath=path;state.selectedIndex=0;state.filter="";}
      render();return true;
    }
    if (["1", "2", "3"].includes(chunk)) {
      const request=++state.routeVersion,projectId=state.activeProject?.id;
      state.projectTab = chunk === "1" ? "overview" : chunk === "2" ? "files" : "tasks"; state.selectedIndex = 0; state.scrollOffset = 0;
      if (state.projectTab === "tasks" && projectId) {const tasks=await decryptUserTasks(await context.client.listUserTasks({projectId}),context.client.getMasterKeyBytes());if(request===state.routeVersion&&state.activeProject?.id===projectId&&state.projectTab==="tasks")state.tasks=tasks;}
      render(); return true;
    }
    if (chunk === "n") {await context.command("/project-chat"); return true;}
    if (key.name === "return") {
      if (state.projectTab === "tasks") {const task=filterTasks(state.tasks,state.filter)[state.selectedIndex]; if(task) await openTask(context,task.taskId);}
      else if (state.projectTab === "files" && state.activeProject) {
        const file=filteredProjectFiles(state.projectFiles,state.filter)[state.selectedIndex],project=state.activeProject,request=state.routeVersion;
        if (file?.kind === "folder") {const files=await loadTuiProjectFiles(context.client,project,file.sourceId?{path:file.path,sourceId:file.sourceId}:{folderId:file.id});if(request===state.routeVersion&&state.activeProject?.id===project.id){state.projectPath=file.path;state.projectFolderId=file.sourceId?null:file.id;state.projectSourceId=file.sourceId??null;state.projectFiles=files;state.selectedIndex=0;state.filter="";}}
        else if(file) {const text=await readTuiProjectFile(context.client,project,file);if(request===state.routeVersion&&state.activeProject?.id===project.id){state.detailTitle=file.name;state.detailLines=text.split("\n");state.screen="embed";state.scrollOffset=0;}}
      }
      render();return true;
    }
  }
  if (state.focus === "content" && (state.screen === "task" || state.screen === "tasks")) {
    if(state.screen==="tasks"&&(key.name==="left"||key.name==="right")&&workspaceGeometry(state,context.terminal.width).contentWidth<110){
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
      :state.screen==="projects"?state.projects.filter((p)=>`${p.name} ${p.description}`.toLowerCase().includes(state.filter.toLowerCase())).length
      :state.screen==="project"?filteredProjectFiles(state.projectFiles,state.filter).length:homeChatItems(state).length;
    state.selectedIndex=Math.max(0,Math.min(count-1,state.selectedIndex+(key.name==="up"?-1:1)));render();return true;
  }
  if (state.focus === "content" && key.name === "return") {
    if (state.screen === "tasks") {const task=filterTasks(state.tasks,state.filter,state.taskStatusFilter as UserTaskStatus||undefined)[state.selectedIndex];if(task)await openTask(context,task.taskId);return true;}
    if (state.screen === "projects") {const project=state.projects.filter((p)=>`${p.name} ${p.description}`.toLowerCase().includes(state.filter.toLowerCase()))[state.selectedIndex];if(project)await openProject(context,project.id);return true;}
    if (state.screen === "chats"||state.screen==="start") {const chat=homeChatItems(state)[state.selectedIndex];if(chat){if(chat.source==="example")await context.command(`/example ${chat.slug||chat.id}`);else await openSavedChat(context,chat.id);}return true;}
  }
  if (state.focus === "composer") {
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
    if (key.name === "paste" || !key.ctrl && !key.meta && chunk && chunk >= " ") {const text=terminalText(chunk);state.input=state.input.slice(0,cursor)+text+state.input.slice(cursor);state.inputCursor=cursor+text.length;rememberDraft(state);render();return true;}
  }
  return false;
}
