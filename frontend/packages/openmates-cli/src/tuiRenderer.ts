import { ENHANCED_ANONYMIZATION_LABEL } from "./privacyModel.js";
/*
 * OpenMates CLI TUI pure renderer.
 *
 * Purpose: turn terminal chat state into deterministic line-based frames.
 * Architecture: no stream writes, no network access, no terminal mutation.
 * This keeps the TUI testable and lets the event loop redraw whole frames.
 * Security: renders file-reference guidance without reading local files.
 * Tests: frontend/packages/openmates-cli/tests/tui.test.ts
 */

import type { ExampleChatConversation, ExampleChatListItem } from "./exampleChats.js";
import { MATE_NAMES, type DailyInspiration, type DecryptedEmbed, type ChatListItem, type UserTaskStatus, type WorkflowDetail, type WorkflowGraph, type WorkflowRunDetail, type WorkflowSummary } from "./client.js";
import { APP_GRADIENTS, PRIMARY_GRADIENT } from "../../appGradientTheme.js";
import { type DecryptedUserTask } from "./tasksCli.js";
import type { TuiForm } from "./tuiForms.js";
import type { TuiProject, TuiProjectFile } from "./tuiProjectsWorkspace.js";
import { renderProjectCarousel, renderProjectDetail, renderProjectIdentity, renderProjectTabs, renderProjectPointerTabs, filteredProjects, filteredProjectFiles } from "./tuiProjectsWorkspace.js";
import { renderTaskBoard, renderTaskDetails, filterTasks, type TaskContext } from "./tuiTasksWorkspace.js";
import { renderWorkflowWorkspace, renderWorkflowCarousel, renderWorkflowIdentity } from "./tuiWorkflowWorkspace.js";
import { chatBackground, renderWorkspaceFrame, workspaceGeometry } from "./tuiLayout.js";
import { cells, wrapCells, truncateCells, padCells, foreground, lineText, type TuiColorMode, type TuiLine } from "./tuiText.js";
import type { TuiStartupScreen } from "./tuiStartup.js";
import { centeredCarouselText, renderLineCarousel } from "./tuiCarousel.js";
import { homeHeader, renderHomeChatCards } from "./tuiHome.js";
import { homeTuiApps, renderTuiAppsHome, renderTuiApp, renderTuiAppIdentity, renderTuiAppTabs, renderTuiAppsSkill, renderTuiAppsSkillIdentity, renderTuiAppsSkillTabs, renderTuiAppsResults, renderTuiAppsResult, renderTuiAppsWorkflows,
  type TuiApp, type TuiAppsTab, type TuiAppsSkillTab, type TuiAppsSkillDetails, type TuiAppsResultsPage, type TuiAppsSavedResult, type TuiAppsPreparedRun, type TuiAppsWorkflowPage } from "./tuiAppsWorkspace.js";
import { parseMessageSegments } from "./messageSegments.js";
import { aliasForEmbed, chatEmbedReferences, exampleEmbedMap, type TuiEmbedTarget } from './tuiEmbeds.js';
import { renderTuiEmbedPreview } from './tuiEmbedPreviews.js';
import { parseTuiMarkdown } from './tuiMarkdown.js';
import { buildTuiResultsViewData, renderTuiResultsViewLines, type TuiResultsViewDescriptor, type TuiResultsViewMode } from './tuiResultsViews.js';
import { chatResultsViews, messageResultsViews } from './tuiChatResults.js';
import { parseChatContextContent, chatContextSummary } from "./chatContextEvents.js";
import type { ProjectFocusCountdown } from "./projectFocusCountdown.js";
import {chatQuestions, messageQuestions, renderQuestionCard, type TuiQuestionEditor} from './tuiInteractiveQuestions.js';
import {fenceTuiSettingsView} from './tuiSettingsShell.js';
import type {TuiSettingsState} from './tuiSettings.js';
import type {TuiModelSelectorState} from './tuiModelSelector.js';
import type {TuiChromeState} from './tuiHeaderActions.js';
import {fullscreenHeaderLines,type TuiViewOrigin} from './tuiFullscreenChrome.js';
import {beginPointerFrame,pointerLine} from './tuiPointer.js';

export type TuiScreen = "start" | "help" | "interests" | "examples" | "example" | "chats" | "chat" | "embed" | "results-view" | "apps" | "app" | "app-skill" | "app-result" | "projects" | "project" | "workflows" | "workflow" | "tasks" | "task" | "status";
export type TuiWorkspace = "chats" | "apps" | "projects" | "tasks" | "workflows";
export type TuiFocus = "composer" | "content" | "inspiration" | "sidebar" | "navigation" | "settings" | "header";

export type TuiMessage = {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  title?: string | null;
  category?: string | null;
  embedIds?: string[];
};

export type TuiWorkflowEdit = {
  nodeId: string;
  field: "title" | "config";
  value: string;
};

export type TuiState = {
  modelSelector:TuiModelSelectorState|null;
  settings:TuiSettingsState|null;
  settingsOwnerCurrent:(()=>boolean)|null;
  settingsRestore:{focus:TuiFocus;sidebarOpen:boolean}|null;
  chrome:TuiChromeState|null;
  chatOrigin:TuiViewOrigin|null;
  headerActionIndex:number;
  questionEditor:TuiQuestionEditor|null;
  textSelection: boolean;
  chatEmbeds: Record<string, DecryptedEmbed>;
  chatEmbedLoads: Set<string>;
  embedAliases: Record<string, TuiEmbedTarget>;
  chatSelectedEmbedId: string | null;
  resultsViewModes: Record<number, TuiResultsViewMode>;
  activeResultsView: number | null;
  resultsViewOrigin: TuiState["embedOrigin"];
  username: string | null;
  inspirations: DailyInspiration[];
  inspirationIndices: Partial<Record<TuiWorkspace,number>>;
  homeLoading: boolean;
  homeChatsLoading: boolean;
  homeAbortController: AbortController | null;
  homeError: string | null;
  homeLoadVersion: number;
  homeShowAll: boolean;
  homeSelectionMoved: boolean;
  homeContextKey: string | null;
  continueData: {memories: import("./client.js").DecryptedMemoryEntry[]; reminders: Array<Record<string,unknown>>} | null;
  detailEmbed: DecryptedEmbed | null;
  embedOrigin: TuiViewOrigin | null;
  embedChoices: string[];
  apps: TuiApp[];
  activeApp: TuiApp | null;
  activeAppSkill: TuiAppsSkillDetails | null;
  appTab: TuiAppsTab;
  appSkillTab: TuiAppsSkillTab;
  appResults: TuiAppsResultsPage;
  appWorkflows: TuiAppsWorkflowPage;
  activeAppResult: TuiAppsSavedResult | null;
  appPreparedRun: TuiAppsPreparedRun | null;
  workspace: TuiWorkspace;
  sidebarOpen: boolean;
  sidebarIndex: number;
  navigationIndex: number;
  focus: TuiFocus;
  signedIn: boolean;
  privacyOffer: boolean;
  privacyInstalling: boolean;
  startup: TuiStartupScreen | null;
  form: TuiForm | null;
  paletteOpen: boolean;
  paletteQuery: string;
  paletteIndex: number;
  filter: string;
  taskStatusFilter: string;
  taskContext: TaskContext | null;
  recentChats: ChatListItem[];
  runningChatIds: string[];
  activityChats: ChatListItem[];
  sidebarLinkedChats: ChatListItem[];
  activityFrame: number;
  chatSidebarProjects: TuiProject[];
  chatSidebarLoadVersion: number;
  chatActivityLoadVersion: number;
  chatSidebarLocation: { projectId: string; folderId: string | null } | null;
  chatSidebarAncestors: boolean;
  chatProjectOperation: { chatIds: string[]; mode: 'add' | 'move' } | null;
  chatProjectBusy: boolean;
  activeChatId: string | null;
  activeChat: ChatListItem | null;
  headerState: "new" | "loading" | "ready" | "error";
  headerError: string | null;
  followUpSuggestions: string[];
  drafts: Record<string, string>;
  routeVersion: number;
  inputCursor: number | null;
  aiTaskId: string | null;
  detailTitle: string;
  detailLines: string[];
  projects: TuiProject[];
  activeProject: TuiProject | null;
  projectFiles: TuiProjectFile[];
  projectTab: "overview" | "files" | "tasks";
  projectPath: string;
  projectFolderId: string | null;
  projectSourceId: string | null;
  selectedProjectId: string | null;
  workflowRunGraph: WorkflowGraph | null;
  workflowInputSessionId: string | null;
  screen: TuiScreen;
  input: string;
  scrollOffset: number;
  followSelection: boolean;
  selectedIndex: number;
  selectedInterests: string[];
  examples: ExampleChatListItem[];
  activeExample: ExampleChatConversation | null;
  workflows: WorkflowSummary[];
  activeWorkflow: WorkflowDetail | null;
  workflowRuns: WorkflowRunDetail[];
  tasks: DecryptedUserTask[];
  activeTask: DecryptedUserTask | null;
  workflowTab: "graph" | "runs";
  selectedWorkflowNodeIndex: number;
  selectedWorkflowRunIndex: number;
  expandedWorkflowNodeId: string | null;
  expandedWorkflowRunNodeId: string | null;
  workflowEdit: TuiWorkflowEdit | null;
  messages: TuiMessage[];
  projectFocusPending: ProjectFocusCountdown | null;
  chatContextAuthoringControls: Record<string, { stop: () => void; approve?: () => void; reviewLines?: string[]; reviewed?: boolean; watching?: boolean }>;
  chatContextAuthoringJobs: Record<string, { projectId: string; jobId: string | null; status: string; approvalDigest?: string }>;
  status: string | null;
  isBusy: boolean;
};

const CONTENT_PREVIEW_LINES = 12;

export const TUI_INTERESTS = [
  "software development",
  "use the CLI",
  "writing",
  "research",
  "learning",
  "travel",
  "privacy & security",
  "image generation",
  "everyday tasks",
  "news",
  "events",
  "apartments",
];

export function createInitialTuiState(): TuiState {
  return {
    modelSelector:null,
    settings:null,settingsOwnerCurrent:null,settingsRestore:null,chrome:null,chatOrigin:null,headerActionIndex:0,
    questionEditor:null,
    textSelection:false,chatEmbeds:{},chatEmbedLoads:new Set(),embedAliases:{},chatSelectedEmbedId:null,username:null,inspirations:[],inspirationIndices:{},homeLoading:false,homeChatsLoading:false,homeAbortController:null,homeError:null,homeLoadVersion:0,homeShowAll:false,homeSelectionMoved:false,homeContextKey:null,continueData:null,detailEmbed:null,embedOrigin:null,embedChoices:[],
    apps:[],activeApp:null,activeAppSkill:null,appTab:"skills",appSkillTab:"overview",appResults:{items:[],hasMore:false,offset:0},
    appWorkflows:{items:[],hasMore:false,offset:0},activeAppResult:null,appPreparedRun:null,
    workspace: "chats", sidebarOpen: false, sidebarIndex: 0, navigationIndex: 0,
    focus: "content", signedIn: false, privacyOffer: false, privacyInstalling: false, startup: null, form: null, paletteOpen: false,
    paletteQuery: "", paletteIndex: 0, filter: "", taskStatusFilter: "",
    taskContext: null, recentChats: [], runningChatIds: [], activityChats: [], sidebarLinkedChats: [], activityFrame: 0,
    chatSidebarProjects: [], chatSidebarLoadVersion: 0, chatActivityLoadVersion: 0, chatSidebarLocation: null, chatSidebarAncestors: false, chatProjectOperation: null, chatProjectBusy: false,
    activeChatId: null, activeChat: null,
    headerState: "new", headerError: null, followUpSuggestions: [], drafts: {}, routeVersion: 0, inputCursor: null, aiTaskId: null,
    detailTitle: "", detailLines: [], projects: [], activeProject: null,
    projectFiles: [], projectTab: "overview", projectPath: "", projectFolderId: null, projectSourceId: null, selectedProjectId: null,
    workflowRunGraph: null,workflowInputSessionId:null,
    resultsViewModes: {}, activeResultsView: null, resultsViewOrigin:null,
    screen: "start",
    input: "",
    scrollOffset: 0,
    followSelection: false,
    selectedIndex: 0,
    selectedInterests: [],
    examples: [],
    activeExample: null,
    workflows: [],
    activeWorkflow: null,
    workflowRuns: [],
    tasks: [],
    activeTask: null,
    workflowTab: "graph",
    selectedWorkflowNodeIndex: 0,
    selectedWorkflowRunIndex: 0,
    expandedWorkflowNodeId: null,
    expandedWorkflowRunNodeId: null,
    workflowEdit: null,
    messages: [],
    projectFocusPending: null, chatContextAuthoringJobs: {}, chatContextAuthoringControls: {},
    status: null,
    isBusy: false,
  };
}

export function programmaticQuickstart(): string {
  return `OpenMates CLI

Interactive:
  openmates                         Open the terminal chat UI
  openmates --help                  Show all commands

Ask from scripts:
  openmates chats new "Explain SQLite strict tables"
  openmates chats new "Explain SQLite strict tables" --json
  openmates chats send --chat <chat-id> "Continue" --json

Account:
  openmates login                   Pair-auth login
  openmates signup                  Create an account
  openmates whoami --json           Show current account

Chats and examples:
  openmates chats list
  openmates chats show example-gigantic-airplanes
  openmates chats search "flight"

Files:
  openmates chats new "Review @./src/app.ts"
  openmates chats new "Summarize @~/Downloads/report.pdf"

More:
  openmates apps list
  openmates workflows list
  openmates mentions list
  openmates embeds show <embed-id>
  openmates help
`;
}

export function rankExamples(
  examples: ExampleChatListItem[],
  interests: string[],
): ExampleChatListItem[] {
  const needles = interests.map((interest) => interest.toLowerCase());
  return [...examples]
    .map((example, index) => {
      const haystack = [example.title, example.summary, example.slug, example.category]
        .join(" ")
        .toLowerCase();
      const score = needles.reduce((total, interest) => total + interestScore(haystack, interest), 0);
      return { example, index, score };
    })
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.example);
}

/** Invalidate private views and pending responses when an interactive session ends. */
export function resetEndedTuiSession(state: TuiState, hasSession: boolean): boolean {
  if (!state.signedIn || hasSession) return false;
  state.homeAbortController?.abort();
  Object.values(state.chatContextAuthoringControls).forEach(control => control.stop());
  const routeVersion = state.routeVersion + 1, homeLoadVersion = state.homeLoadVersion + 1;
  Object.assign(state, createInitialTuiState(), {routeVersion, homeLoadVersion, status: "Session ended. Sign in to reopen your work."});
  return true;
}

export function renderTuiFrame(state: TuiState, width: number, height: number, options: { colorMode?: TuiColorMode; ascii?: boolean } = {}): string {
  fenceTuiSettingsView(state);
  beginPointerFrame(state,width,height);
  if (state.startup || state.privacyOffer) return renderStartupFrame(state, width, height, options.colorMode ?? "none");
  const bodyWidth = workspaceGeometry(state, width).contentWidth;
  const header=fullscreenHeaderLines(state,bodyWidth);
  const embedHero=state.screen==="embed"?renderEmbedHero(state,bodyWidth,height):null;
  const stickyRows=state.screen==="embed"?embedHero!.length+1:state.screen==="results-view"?2:state.screen==="project"&&state.activeProject?renderProjectIdentity(state.activeProject,{width:bodyWidth}).length+renderProjectTabs(state.projectTab,bodyWidth).length:
    state.screen==="app"&&state.activeApp?renderTuiAppIdentity(state.activeApp,bodyWidth).length+renderTuiAppTabs(state.appTab,bodyWidth).length:
    state.screen==="app-skill"&&state.activeAppSkill?renderTuiAppsSkillIdentity(state.activeAppSkill,bodyWidth).length+renderTuiAppsSkillTabs(state.appSkillTab,bodyWidth).length:
    state.screen==="workflow"&&state.activeWorkflow?renderWorkflowIdentity(state.activeWorkflow,{width:bodyWidth,run:state.workflowTab==="runs"?state.workflowRuns[state.selectedWorkflowRunIndex]:undefined}).length+(bodyWidth<36?7:4):0;
  return renderWorkspaceFrame(state, width, height, [...header,...renderBody(state, bodyWidth,height,embedHero??undefined)],
    { ...options,stickyRows:stickyRows+header.length,stickyFallbackRows:embedHero?header.length:undefined });
}

function renderStartupFrame(state: TuiState, width: number, height: number, colorMode: TuiColorMode): string {
  width = Math.max(1, Math.floor(width)); height = Math.max(1, Math.floor(height));
  const screen = state.startup ?? { kind: "privacy", selected: 1, busy: false, status: null, update: null };
  const privacy = screen.kind === "privacy", checking = screen.kind === "checking";
  const title = checking ? "Starting OpenMates…" : privacy ? ENHANCED_ANONYMIZATION_LABEL : "Software update available";
  const paragraphs = checking ? ["Checking startup preferences and software updates…"] : privacy ? [
    "Use enhanced offline personal data detection?",
    "Detect names and addresses locally, alongside existing detection. Your text stays on this device.",
    "Download: about 1.6 GB. RAM when active: about 2 GB.",
    "Choosing No keeps existing detection. You can enable it later with /privacy install.",
  ] : [
    `OpenMates ${screen.update?.latestVersion ?? ""} is available (installed: ${screen.update?.plan.currentVersion ?? ""}).`,
    "Update now to install the new version and reopen OpenMates.",
    "Skip for now to continue. We will ask again when you open the TUI after 24 hours.",
  ];
  const contentWidth = Math.max(1, Math.min(72, width - 4));
  const center = (text: string) => padCells(" ".repeat(Math.max(0, Math.floor((width - cells(text)) / 2))) + text, width);
  const body = [title, "", ...paragraphs.flatMap(text => [...wrapCells(text, contentWidth), ""])].map(center);
  const buttons = checking ? [] : [
    `${screen.selected === 0 ? "> " : "  "}${privacy ? "[F6 / Y] Download and enable" : "[F6 / Y] Update now"}`,
    `${screen.selected === 1 ? "> " : "  "}${privacy ? "[F7 / N] No, continue" : "[F7 / N] Skip for now"}`,
    ...(privacy ? ["Later: /privacy install or /privacy later"] : []),
  ];
  const footer = [...(screen.status ? wrapCells(screen.status, contentWidth) : []), ...buttons,
    checking ? "Ctrl+C exit" : screen.busy ? "Please wait…  Ctrl+C exit" : "Tab / arrows choose   Enter confirm   Ctrl+C exit"].map(center);
  const bodyRoom = Math.max(0, height - footer.length - 2);
  const lines = [foreground(padCells("OpenMates", width), "#5a85eb", colorMode, true), " ".repeat(width), ...body.slice(0, bodyRoom)];
  while (lines.length < height - footer.length) lines.push(" ".repeat(width));
  return [...lines.slice(0, Math.max(0, height - footer.length)), ...footer.slice(-height)].join("\n");
}

function coloredHero(lines:TuiLine[],rows:number,gradient=PRIMARY_GRADIENT):TuiLine[]{
  return lines.map((line,index)=>index<rows
    ? typeof line==='string'?{text:line,background:gradient.start}:{...line,background:gradient.start}
    : line);
}
function appsHomeCommandLine(showAll:boolean,width:number):TuiLine {
  const browse=showAll?'/browse Featured apps':'/browse Show all';
  const separator='  ·  ',search='/search Search apps';
  const visible=truncateCells(browse+separator+search,width);
  const text=centeredCarouselText(browse+separator+search,width);
  const left=text.slice(0,text.length-visible.length);
  const shownBrowse=visible.slice(0,browse.length);
  const shownSeparator=visible.slice(browse.length,browse.length+separator.length);
  const shownSearch=visible.slice(browse.length+separator.length);
  return {text,spans:[
    {text:left},
    {text:shownBrowse,action:{kind:'command',command:'/browse'}},
    {text:shownSeparator},
    {text:shownSearch,action:shownSearch.startsWith('/search')?{kind:'command',command:'/search'}:undefined},
  ]};
}
function renderBody(state: TuiState, width: number,height:number,embedHero?:TuiLine[]): TuiLine[] {
  return renderScreenBody(state, width, height, embedHero);
}
function renderScreenBody(state: TuiState, width: number,height:number,embedHero?:TuiLine[]): TuiLine[] {
  switch (state.screen) {
    case "help":
      return renderHelp(width);
    case "interests":
      return renderInterests(state, width);
    case "examples":
      return renderExamples(state, width);
    case "example":
      return renderExampleChat(state, width, height);
    case "chat":
      return renderChat(state, width, height);
    case "chats":
      return renderHomeChatCards(state,width,height);
    case "apps": {
      const apps=homeTuiApps(state.apps,state.filter,state.homeShowAll);
      return [...homeHeader(state,width,height),...renderTuiAppsHome(apps,{width,selectedIndex:state.selectedIndex,selectedId:state.focus==="content"?apps[state.selectedIndex]?.id:undefined}),"",
        appsHomeCommandLine(state.homeShowAll,width)];
    }
    case "app": {
      const app=state.activeApp;if(!app)return ["Loading app…"];
      const header=renderTuiAppIdentity(app,width),gradient=APP_GRADIENTS[app.id]??PRIMARY_GRADIENT;
      if(state.appTab==="embeds"||state.appTab==="workflows")return [...coloredHero(header,header.length,gradient),...renderTuiAppTabs(state.appTab,width,{pointer:true}),
        ...state.appTab==="embeds"?renderTuiAppsResults(state.appResults,{width,selectedId:state.appResults.items[state.selectedIndex]?.embedId,pointer:true}):renderTuiAppsWorkflows(state.appWorkflows,{width,selectedId:state.appWorkflows.items[state.selectedIndex]?.id,pointer:true})];
      return coloredHero(renderTuiApp(app,{width,tab:state.appTab,selectedId:app.skills[state.selectedIndex]?.id,pointer:true}),header.length,gradient);
    }
    case "app-skill": {
      const skill=state.activeAppSkill;if(!skill)return ["Loading skill…"];
      const header=renderTuiAppsSkillIdentity(skill,width),gradient=APP_GRADIENTS[skill.appId]??PRIMARY_GRADIENT;
      if(state.appSkillTab==="embeds"||state.appSkillTab==="workflows")return [...coloredHero(header,header.length,gradient),...renderTuiAppsSkillTabs(state.appSkillTab,width,{pointer:true}),
        ...state.appSkillTab==="embeds"?renderTuiAppsResults(state.appResults,{width,selectedId:state.appResults.items[state.selectedIndex]?.embedId,pointer:true}):renderTuiAppsWorkflows(state.appWorkflows,{width,selectedId:state.appWorkflows.items[state.selectedIndex]?.id,pointer:true})];
      return coloredHero(renderTuiAppsSkill(skill,{width,tab:state.appSkillTab,pointer:true}),header.length,gradient);
    }
    case "app-result": return state.activeAppResult ? renderTuiAppsResult(state.activeAppResult,width):["Loading saved result…"];
    case "projects":
      return [...homeHeader(state,width,height),...renderProjectCarousel(filteredProjects(state.projects,state.filter),width,state.selectedIndex,state.focus==='content')];
    case "project":
      return state.activeProject ? state.projectTab === "tasks"
        ? [...renderProjectIdentity(state.activeProject,{width}),...renderProjectPointerTabs("tasks",width),"",...renderTaskBoard(state.tasks, { width, selectedTaskId: filterTasks(state.tasks, state.filter)[state.selectedIndex]?.taskId, query: state.filter })]
        : renderProjectDetail(state.activeProject, { width, tab: state.projectTab, files: state.projectFiles, selectedFileId: filteredProjectFiles(state.projectFiles,state.filter)[state.selectedIndex]?.id, query: state.filter, folderId:state.projectFolderId??undefined, sourceId:state.projectSourceId??undefined, path:state.projectPath }) : ["Projects", "Loading project…"];
    case "status":
      return renderStatus(state, width);
    case "results-view": {
      const key = state.activeResultsView ?? 1, descriptor = chatResultsViews(state)[key-1];
      return descriptor ? [...pointerResultsView(state,descriptor,key,width), '',
        {text:'m Map · c Calendar · l List · Esc back',spans:[
          {text:'m Map',action:{kind:'command',command:`/view ${key} map`}},
          {text:' · '},{text:'c Calendar',action:{kind:'command',command:`/view ${key} calendar`}},
          {text:' · '},{text:'l List',action:{kind:'command',command:`/view ${key} list`}},
          {text:' · '},{text:'Esc back',action:{kind:'key',name:'escape'}},
        ]}] : ['Results view unavailable. Escape returns to the chat.'];
    }
    case "embed": {
      const header=embedHero??renderEmbedHero(state,width,height);
      const details=(state.embedChoices.length ? state.embedChoices.map((alias,index)=>
        pointerLine(`${index===state.selectedIndex?">":" "} /embed ${alias} · Enter open`,
          {kind:'command',command:`/embed ${alias}`})) : state.detailLines).flatMap(line=>
        wrap(lineText(line),width).map(text=>typeof line==='string'?text:{...line,text,spans:undefined}));
      return [...header,"",...details];
    }
    case "workflows":
      return [...homeHeader(state,width,height),...renderWorkflowCarousel(state.workflows.filter(w=>w.title.toLowerCase().includes(state.filter.toLowerCase())),width,state.selectedIndex,state.focus==='content')];
    case "workflow":
      return renderWorkflowDetail(state, width);
    case "tasks":
      return [...homeHeader(state,width,height),...renderTasks(state, width)];
    case "task":
      return renderTaskDetail(state, width);
    case "start":
    default:
      return renderHomeChatCards(state,width,height);
  }
}

function renderHelp(width: number): string[] {
  return [
    "Help",
    "",
    "Chat",
    "  Enter              Send message",
    "  @./file.md         Attach a file from current directory",
    "  @~/file.pdf        Attach a file from home directory",
    "  @/abs/path.png     Attach a file by absolute path",
    "",
    "Navigation",
    "  Up/Down            Scroll or move selection",
    "  PageUp/PageDown    Scroll faster",
    "  Home/End           Jump to start/end",
    "",
    "Commands",
    "  /examples          Choose example chats",
    "  /workflows         List and run saved workflows",
    "  /workflow <id>     Open a workflow by ID",
    "  /tasks             Open your task workspace",
    "  /login             Pair-auth login",
    "  /signup            Leave TUI and run guided signup",
    "  /embed <shortcut>  Open an embed (UUIDs also work)",
    "  /embed             List this chat's embed shortcuts",
    "  /wiki <title>      Read the linked Wikipedia article",
    "  /question <n>      Answer a question · Ctrl+Q latest",
    "  /view <n> <mode>   Open map, calendar or list results",
    "  Ctrl+Y             Select and copy text using the terminal",
    "  Esc                Back from embed, then back to chats",
    "  /exit              Leave OpenMates and restore terminal",
    "",
    "Outside TUI: openmates --help, openmates chats --help, openmates apps --help",
  ].flatMap((line) => wrap(line, width));
}

function renderTasks(state: TuiState, width: number): TuiLine[] {
  return renderTaskBoard(state.tasks, { width, selectedTaskId: filterTasks(state.tasks, state.filter, (state.taskStatusFilter || undefined) as UserTaskStatus | undefined)[state.selectedIndex]?.taskId, query: state.filter, status: (state.taskStatusFilter || undefined) as UserTaskStatus | undefined });
}

function renderTaskDetail(state: TuiState, width: number): TuiLine[] {
  if (!state.activeTask) return renderTasks(state, width);
  return renderTaskDetails(state.activeTask, { width, activity: state.taskContext?.activity,
    dependencies: state.taskContext?.dependencies, pointer:true });
}

function renderWorkflows(state: TuiState, width: number): string[] {
  const lines = ["Workflows", ""];
  if (state.workflows.length === 0) {
    lines.push("No workflows found.", "Create one outside TUI with: openmates workflows create --file workflow.yml");
    return lines.flatMap((line) => wrap(line, width));
  }
  const visibleCount = Math.max(1, CONTENT_PREVIEW_LINES);
  const start = Math.max(0, Math.min(state.selectedIndex, state.workflows.length - visibleCount));
  for (let i = 0; i < state.workflows.slice(start, start + visibleCount).length; i += 1) {
    const absoluteIndex = start + i;
    const workflow = state.workflows[absoluteIndex];
    const cursor = absoluteIndex === state.selectedIndex ? ">" : " ";
    const status = workflow.enabled ? "enabled" : "disabled";
    const lastRun = workflow.last_run_status ? ` last: ${workflow.last_run_status}` : "";
    lines.push(`${cursor} ${workflow.title} (${status})${lastRun}`);
    lines.push(`    ${workflow.id}`);
    if (workflow.trigger_summary) lines.push(`    ${workflow.trigger_summary}`);
    lines.push("");
  }
  return lines.flatMap((line) => wrap(line, width));
}

function renderWorkflowDetail(state: TuiState, width: number): TuiLine[] {
  if (!state.activeWorkflow) return renderWorkflows(state, width);
  const lines = renderWorkflowWorkspace(state.activeWorkflow, {
    width, tab: state.workflowTab, selectedNodeIndex: state.selectedWorkflowNodeIndex,
    expandedNodeId: state.workflowTab === "runs" ? state.expandedWorkflowRunNodeId : state.expandedWorkflowNodeId,
    run: state.workflowRuns[state.selectedWorkflowRunIndex], runs: state.workflowRuns,
    selectedRunIndex: state.selectedWorkflowRunIndex, runGraph: state.workflowRunGraph ?? (state.workflowRuns[state.selectedWorkflowRunIndex]?.version_id === state.activeWorkflow.current_version_id ? state.activeWorkflow.graph : undefined),
    edit: state.workflowEdit ?? undefined,
  });
  if (state.status) lines.push("", state.status);
  return lines;
}

function renderInterests(state: TuiState, width: number): string[] {
  const lines = [
    "Private local personalization",
    "What are you interested in?",
    "",
    "Use Space to select, Enter to continue.",
    "",
  ];
  for (let i = 0; i < TUI_INTERESTS.length; i += 1) {
    const interest = TUI_INTERESTS[i];
    const marker = state.selectedInterests.includes(interest) ? "◉" : "○";
    const cursor = i === state.selectedIndex ? ">" : " ";
    lines.push(`${cursor} ${marker} ${interest}`);
  }
  lines.push("", "Your choices stay local in this terminal session for v1.");
  return lines.flatMap((line) => wrap(line, width));
}

function renderExamples(state: TuiState, width: number): string[] {
  const interests = state.selectedInterests.length > 0 ? state.selectedInterests.join(", ") : "recent examples";
  const lines = ["Example chats", `Recommended from your interests: ${interests}`, ""];
  const visibleCount = Math.max(1, CONTENT_PREVIEW_LINES);
  const start = Math.max(0, Math.min(state.selectedIndex, state.examples.length - visibleCount));
  const examples = state.examples.slice(start, start + visibleCount);
  for (let i = 0; i < examples.length; i += 1) {
    const absoluteIndex = start + i;
    const example = examples[i];
    const cursor = absoluteIndex === state.selectedIndex ? ">" : " ";
    lines.push(`${cursor} ${absoluteIndex + 1}. ${example.title ?? example.slug}`);
    if (example.summary) lines.push(`     ${example.summary}`);
    lines.push("");
  }
  return lines.flatMap((line) => wrap(line, width));
}

function renderExampleChat(state: TuiState, width: number, height: number): TuiLine[] {
  const convo = state.activeExample;
  if (!convo) return renderExamples(state, width);
  const embeds = new Map(Object.entries(exampleEmbedMap(state)));
  const lines = [
    ...renderChatHeader(state, width, height),
    `Example chat: ${convo.chat.title ?? convo.chat.slug}`,
    "",
  ];
  let viewOffset = 0, questionOffset=0;
  for (const message of convo.messages) {
    lines.push({text: messageLabel(message.role,message.senderName,message.category,convo.chat),color:'#5a85eb',bold:true});
    lines.push(...renderMessageContentStyled(message.content, width, embeds,state,[],viewOffset,questionOffset,message.role==='assistant'));
    viewOffset += messageResultsViews(message.content).length;
    if(message.role==='assistant')questionOffset+=messageQuestions(message.content).length;
    lines.push("");
  }
  if (convo.followUpSuggestions.length > 0) {
    lines.push("Follow-up ideas:");
    for (const [index, suggestion] of convo.followUpSuggestions.slice(0, 3).entries()) {
      lines.push(`  ${index + 1}. ${suggestion}`);
    }
  }
  return lines.flatMap<TuiLine>(line=>typeof line==='string'?wrap(line,width):[line]);
}

function renderChat(state: TuiState, width: number, height: number): TuiLine[] {
  const lines = renderChatHeader(state, width, height);
  let contextIndex = 0, viewOffset = 0, questionOffset=0;
  for (const message of state.messages) {
    const event = message.role === "system" ? parseChatContextContent(message.content) : null;
    if (event) {
      contextIndex++;
      lines.push(`${chatContextSummary(event)} · /context ${contextIndex}`);
      if (event.type === "project_authoring_recommendation") {
        const job = state.chatContextAuthoringJobs[event.event_id];
        lines.push(job ? `Authoring: ${job.status} · ${job.status === "needs_write_approval" ? "/authoring-save" : "/authoring-refresh"} ${contextIndex}`
          : `[${event.action === "create" ? "Create" : "Update"} ${event.kind === "focus" ? "Focus" : "Workflow"}] /focus-author ${contextIndex}`);
      }
      lines.push("");
      continue;
    }
    lines.push({text:messageLabel(message.role,message.title,message.category,state.activeChat),color:'#5a85eb',bold:true});
    const embeds = new Map(Object.entries(state.chatEmbeds));
    lines.push(...renderMessageContentStyled(message.content, width, embeds,state,message.role==='assistant'?message.embedIds:undefined,viewOffset,questionOffset,message.role==='assistant'));
    viewOffset += messageResultsViews(message.content).length;
    if(message.role==='assistant')questionOffset+=messageQuestions(message.content).length;
    lines.push("");
  }
  if (state.projectFocusPending) lines.push("Project access starts after the countdown. /project-focus-reject to cancel.");
  if (state.isBusy) lines.push(`${messageLabel('assistant',null,null,state.activeChat)} is typing...`);
  if (state.followUpSuggestions.length) lines.push("", "Suggestions", ...state.followUpSuggestions.slice(0, 3).map((s, i) => `  ${i + 1}. ${s}`));
  if (state.status) lines.push("", state.status);
  return lines.flatMap<TuiLine>(line=>typeof line==='string'?wrap(line,width):[line]);
}

function renderEmbedHero(state:TuiState,width:number,height:number):TuiLine[] {
  const app=state.detailEmbed?.appId??"",gradient=APP_GRADIENTS[app]??PRIMARY_GRADIENT;
  const title=state.detailTitle||"Embed";
  const subtitle=state.detailEmbed?`${state.detailEmbed.type?.replaceAll("-"," ")??"Saved item"} · ${state.detailEmbed.embedId.slice(0,8)}`:"Saved embeds";
  return centeredHero(title,subtitle,"",width,height,gradient.start);
}

/** Terminal-sized equivalent of the centered, solid-color web ChatHeader/EmbedHeader banners. */
function centeredHero(title:string,subtitle:string,meta:string,width:number,height:number,background:string):TuiLine[] {
  width=Math.max(1,width);
  const textWidth=Math.max(1,Math.min(72,width-(width>=30?4:0)));
  const padding=height>=28&&width>=48?2:height>=18&&width>=28?1:0;
  const titleRows=wrapCells(title,textWidth).slice(0,height<16?1:2);
  const subtitleRows=height<12||!subtitle?[]:wrapCells(subtitle,textWidth).slice(0,height<20?1:2);
  const metaText=height>=14&&width>=20?truncateCells(meta,textWidth):"";
  const core=[...titleRows.map(text=>({text,bold:true})),...subtitleRows.map(text=>({text})),...(metaText?[{text:metaText}]:[])];
  const minimum=padding===2?7:padding===1?5:0;
  const extra=Math.max(0,minimum-core.length-padding*2);
  const rows:Array<{text:string;bold?:boolean}>=[
    ...Array.from({length:padding+Math.floor(extra/2)},()=>({text:""})),
    ...core,
    ...Array.from({length:padding+Math.ceil(extra/2)},()=>({text:""})),
  ];
  return rows.map(row=>({text:centeredCarouselText(row.text,width),background,bold:row.bold}));
}

export function renderChatHeader(state: TuiState, width: number, height=24): TuiLine[] {
  const chat = state.screen === "example" ? state.activeExample?.chat : state.activeChat;
  const title = state.headerState === "loading" && !chat?.title ? state.status === "Loading chat…" ? "Loading chat…" : "Creating new chat…"
    : state.headerState === "error" ? state.headerError || "Could not send message"
    : chat?.title || (state.messages.length ? "Chat" : "New chat");
  const category = chat?.category?.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  const summary = chat?.summary || (state.messages.length ? "" : "What would you like to work on?");
  const badges = state.screen === "example" ? "Example chat" : state.input && !state.messages.length ? "Draft" : "";
  const timestamp = chat && "createdAt" in chat ? chat.createdAt : null;
  const when = timestamp ? `Started ${relativeTime(timestamp)}` : "";
  const meta = [category, when, badges, state.selectedProjectId && state.activeProject?.name].filter(Boolean).join("  ·  ");
  const background=chatBackgroundFor(state);
  return centeredHero(title,summary,meta,width,height,background);
}

function chatBackgroundFor(state:TuiState):string { return chatBackground(state.screen==='example'?state.activeExample?.chat.category:state.activeChat?.category); }

function relativeTime(timestamp: number): string {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function renderStatus(state: TuiState, width: number): string[] {
  return ["OpenMates", "", state.status ?? "Working..."]
    .flatMap((line) => wrap(line, width));
}

export function renderMessageContent(content: string, width: number, embeds: Map<string, DecryptedEmbed> = new Map()): string[] {
  return renderMessageContentStyled(content,width,embeds).map(lineText);
}
export function renderMessageContentStyled(content: string, width: number, embeds: Map<string, DecryptedEmbed> = new Map(), state?:TuiState,extraIds:string[]=[],viewOffset=0,questionOffset=0,questionBlocks=true): TuiLine[] {
  const lines:TuiLine[]=[],segments=parseMessageSegments(content,{preserveCodeFences:true});
  let pending:Array<{value:string;meta?:Record<string,unknown>}>=[], viewIndex=viewOffset, questionIndex=questionOffset;
  const flush=()=>{
    if(!pending.length)return;
    const unique=pending.filter((ref,index)=>pending.findIndex(other=>other.value===ref.value)===index);
    const id=state?.chatSelectedEmbedId??(state?chatEmbedReferences(state)[0]?.value:undefined);
    const selected=unique.findIndex(ref=>ref.value===id),cardWidth=Math.min(width,62);
    const rawCards=unique.map(ref=>renderEmbedReference(ref,cardWidth,embeds,state));
    const height=Math.max(...rawCards.map(card=>card.length));
    // Keep the web basic-info bars aligned while detail areas have different heights.
    const cards=rawCards.map(card=>card.length<5?card:[...card.slice(0,-4),
      ...Array.from({length:height-card.length},()=>`│ ${padCells('',Math.max(0,cardWidth-4))} │`),...card.slice(-4)]);
    lines.push(...renderLineCarousel(cards,width,Math.max(0,selected),Boolean(state?.focus==='content'&&selected>=0),cardWidth));
    if(state&&selected>=0)lines.push(pointerLine(centeredCarouselText(`Embed ${selected+1}/${unique.length} · ←/→ choose · Enter open · /embed ${aliasForEmbed(state,id!)}`,width),
      {kind:'command',command:`/embed ${aliasForEmbed(state,id!)}`}));
    pending=[];
  };
  const text=(value:string)=>{
    for(const block of parseTuiMarkdown(value,width,{resolveEmbedAlias:id=>state?aliasForEmbed(state,id):id,questionBlocks})) {
      if(block.type==='line')lines.push(block.line);
      else if(block.type==='question'){
        const key=++questionIndex;
        const question=state?chatQuestions(state).find(item=>item.key===key&&item.payload.id===block.payload.id):undefined;
        lines.push(...renderQuestionCard(question??{key,messageIndex:0,payload:block.payload},width));
      }
      else if(block.type==='results-view') {
        const key=++viewIndex;
        if(state)lines.push(...pointerResultsView(state,block,key,width));
        else lines.push(...renderTuiResultsViewLines(buildTuiResultsViewData(block,embeds),{viewKey:key}).flatMap(row=>wrap(row,width)));
      }
    }
  };
  for(const segment of segments){
    if(segment.type==='embed')pending.push(segment);
    else if(segment.value.trim()){flush();text(segment.value);}
    else if(!pending.length)text(segment.value);
  }
  const inline=new Set(segments.filter(segment=>segment.type==='embed').map(segment=>segment.value));
  pending.push(...extraIds.filter(id=>!inline.has(id)).map(value=>({value})));
  flush();return lines;
}
function pointerResultsView(state:TuiState,descriptor:TuiResultsViewDescriptor,key:number,width:number):TuiLine[] {
  const data=buildTuiResultsViewData(descriptor,{...exampleEmbedMap(state),...state.chatEmbeds});
  const actions=data.entries.map((entry,index)=>{
    const alias=aliasForEmbed(state,entry.ref);
    return {index,title:entry.title,command:`/embed ${alias}`};
  }).filter(entry=>/^[\p{L}\p{N}_.:()-]{1,300}$/u.test(entry.command.slice(7)));
  const rows=renderTuiResultsViewLines(data,{viewKey:key,mode:state.resultsViewModes[key],
    aliasForEmbed:id=>aliasForEmbed(state,id)});
  return rows.flatMap((row,index)=>{
    const value=row.trim(),entry=actions.find(item=>value===item.command||
      value.startsWith(`${item.index+1}. ${item.title}`)||
      value.startsWith(`★ ${item.index+1}. ${item.title}`)||
      value.startsWith(`▶ ${item.index+1}. ${item.title}`));
    const action=index===1&&value.startsWith(`/view ${key} `)?{kind:'command' as const,command:`/view ${key}`}:
      entry?{kind:'command' as const,command:entry.command}:undefined;
    return wrap(row,width).map(text=>action?pointerLine(index===0?{text,bold:true,color:'#80caff'}:
      index===1?{text,color:'#85c9e8'}:text,action):
      index===0?{text,bold:true,color:'#80caff'}:index===1&&row.includes('/view')?{text,color:'#85c9e8'}:text);
  });
}
function renderEmbedReference(segment:{value:string;meta?:Record<string,unknown>},width:number,embeds:Map<string,DecryptedEmbed>,state?:TuiState):TuiLine[] {
  const meta=segment.meta??{}, saved=embeds.get(segment.value);
  const alias=state?aliasForEmbed(state,segment.value):segment.value;
  const app=typeof meta.app_id==='string'?meta.app_id:null,skill=typeof meta.skill_id==='string'?meta.skill_id:null;
  const embed:DecryptedEmbed=saved?{...saved,content:{...meta,...saved.content},appId:saved.appId??app,skillId:saved.skillId??skill}:
    {id:segment.value,embedId:segment.value,type:'app_skill_use',appId:app,skillId:skill,content:{...meta,status:meta.status??'processing'},textPreview:null,createdAt:null};
  return renderTuiEmbedPreview(embed,width,alias);
}

function interestScore(haystack: string, interest: string): number {
  let score = haystack.includes(interest) ? 10 : 0;
  for (const token of interest.split(/\s+|&/).filter((part) => part.length > 2)) {
    if (haystack.includes(token)) score += 2;
  }
  return score;
}

function messageLabel(role: string, sender?:string|null, category?:string|null, chat?:ChatListItem|null): string {
  if (role === "user") return "You";
  if (role === "system") return "System";
  if(sender&&!/^(assistant|ai assistant|ai|openmates)$/i.test(sender.trim()))return sender;
  return MATE_NAMES[category??''] || chat?.mateName || MATE_NAMES[chat?.category??''] || 'Assistant';
}

function wrap(line: string, width: number): string[] {
  return wrapCells(line, width);
}
