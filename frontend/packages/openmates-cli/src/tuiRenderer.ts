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
import { parseEmbedContentObject, type DailyInspiration, type DecryptedEmbed, type ChatListItem, type UserTaskStatus, type WorkflowDetail, type WorkflowGraph, type WorkflowRunDetail, type WorkflowSummary } from "./client.js";
import { APP_GRADIENTS, PRIMARY_GRADIENT } from "../../appGradientTheme.js";
import { type DecryptedUserTask } from "./tasksCli.js";
import type { TuiForm } from "./tuiForms.js";
import type { TuiProject, TuiProjectFile } from "./tuiProjectsWorkspace.js";
import { renderProjectList, renderProjectDetail, renderProjectIdentity, renderProjectTabs, filteredProjectFiles } from "./tuiProjectsWorkspace.js";
import { renderTaskBoard, renderTaskDetails, filterTasks, type TaskContext } from "./tuiTasksWorkspace.js";
import { renderWorkflowWorkspace, renderWorkflowPreviewCard, renderWorkflowIdentity } from "./tuiWorkflowWorkspace.js";
import { renderWorkspaceFrame } from "./tuiLayout.js";
import { cells, wrapCells, truncateCells, type TuiColorMode, type TuiLine } from "./tuiText.js";
import { homeHeader, renderHomeChatCards } from "./tuiHome.js";
import { visibleTuiApps, renderTuiAppsHome, renderTuiApp, renderTuiAppIdentity, renderTuiAppTabs, renderTuiAppsSkill, renderTuiAppsSkillIdentity, renderTuiAppsSkillTabs, renderTuiAppsResults, renderTuiAppsResult, renderTuiAppsWorkflows,
  type TuiApp, type TuiAppsTab, type TuiAppsSkillTab, type TuiAppsSkillDetails, type TuiAppsResultsPage, type TuiAppsSavedResult, type TuiAppsPreparedRun, type TuiAppsWorkflowPage } from "./tuiAppsWorkspace.js";
import { parseMessageSegments } from "./messageSegments.js";
import { formatEmbedPreviewLines } from "./embedRenderers.js";

export type TuiScreen = "start" | "help" | "interests" | "examples" | "example" | "chats" | "chat" | "embed" | "apps" | "app" | "app-skill" | "app-result" | "projects" | "project" | "workflows" | "workflow" | "tasks" | "task" | "status";
export type TuiWorkspace = "chats" | "apps" | "projects" | "tasks" | "workflows";
export type TuiFocus = "composer" | "content" | "inspiration" | "sidebar" | "navigation";

export type TuiMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  title?: string | null;
  embedIds?: string[];
};

export type TuiWorkflowEdit = {
  nodeId: string;
  field: "title" | "config";
  value: string;
};

export type TuiState = {
  username: string | null;
  inspirations: DailyInspiration[];
  inspirationIndices: Partial<Record<TuiWorkspace,number>>;
  homeLoading: boolean;
  homeError: string | null;
  homeLoadVersion: number;
  homeShowAll: boolean;
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
  form: TuiForm | null;
  paletteOpen: boolean;
  paletteQuery: string;
  paletteIndex: number;
  filter: string;
  taskStatusFilter: string;
  taskContext: TaskContext | null;
  recentChats: ChatListItem[];
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
    username:null,inspirations:[],inspirationIndices:{},homeLoading:false,homeError:null,homeLoadVersion:0,homeShowAll:false,
    apps:[],activeApp:null,activeAppSkill:null,appTab:"skills",appSkillTab:"overview",appResults:{items:[],hasMore:false,offset:0},
    appWorkflows:{items:[],hasMore:false,offset:0},activeAppResult:null,appPreparedRun:null,
    workspace: "chats", sidebarOpen: false, sidebarIndex: 0, navigationIndex: 0,
    focus: "content", signedIn: false, form: null, paletteOpen: false,
    paletteQuery: "", paletteIndex: 0, filter: "", taskStatusFilter: "",
    taskContext: null, recentChats: [], activeChatId: null, activeChat: null,
    headerState: "new", headerError: null, followUpSuggestions: [], drafts: {}, routeVersion: 0, inputCursor: null, aiTaskId: null,
    detailTitle: "", detailLines: [], projects: [], activeProject: null,
    projectFiles: [], projectTab: "overview", projectPath: "", projectFolderId: null, projectSourceId: null, selectedProjectId: null,
    workflowRunGraph: null,workflowInputSessionId:null,
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

export function renderTuiFrame(state: TuiState, width: number, height: number, options: { colorMode?: TuiColorMode; ascii?: boolean } = {}): string {
  const sidebarWidth = state.sidebarOpen && width >= 90 ? 27 : 0;
  const bodyWidth = Math.max(1, width - 4 - sidebarWidth);
  const stickyRows=state.screen==="project"&&state.activeProject?renderProjectIdentity(state.activeProject,{width:bodyWidth}).length+renderProjectTabs(state.projectTab,bodyWidth).length:
    state.screen==="app"&&state.activeApp?renderTuiAppIdentity(state.activeApp,bodyWidth).length+renderTuiAppTabs(state.appTab,bodyWidth).length:
    state.screen==="app-skill"&&state.activeAppSkill?renderTuiAppsSkillIdentity(state.activeAppSkill,bodyWidth).length+renderTuiAppsSkillTabs(state.appSkillTab,bodyWidth).length:
    state.screen==="workflow"&&state.activeWorkflow?renderWorkflowIdentity(state.activeWorkflow,{width:bodyWidth,run:state.workflowTab==="runs"?state.workflowRuns[state.selectedWorkflowRunIndex]:undefined}).length+(bodyWidth<36?7:4):0;
  return renderWorkspaceFrame(state, width, height, renderBody(state, bodyWidth,height), { ...options,stickyRows, headerRows: state.screen === "chat" || state.screen === "example" ? renderChatHeader(state, bodyWidth).length : undefined });
}

function coloredHero(lines:string[],rows:number,gradient=PRIMARY_GRADIENT):TuiLine[]{return lines.map((text,index)=>index<rows?{text,background:gradient.start}:text);}
const blueHero=(lines:string[],rows:number)=>coloredHero(lines,rows);
/** Keep each stacked home card centered and independently colored. */
function homeCards(lines:string[],width:number,gradients:Array<{start:string;end:string}>):TuiLine[] {
  const groups:string[][]=[[]];
  for(const line of lines){if(line===""){if(groups.at(-1)!.length)groups.push([]);}else groups.at(-1)!.push(line);}
  return groups.filter((group)=>group.length).flatMap((group,index)=>{
    const cardWidth=Math.min(width,Math.max(...group.map(cells))),inset=Math.max(0,Math.floor((width-cardWidth)/2));
    return [...group.map((text)=>({text,background:(gradients[index]??PRIMARY_GRADIENT).start,inset})),""];
  });
}
function renderBody(state: TuiState, width: number,height:number): TuiLine[] {
  switch (state.screen) {
    case "help":
      return renderHelp(width);
    case "interests":
      return renderInterests(state, width);
    case "examples":
      return renderExamples(state, width);
    case "example":
      return renderExampleChat(state, width);
    case "chat":
      return renderChat(state, width);
    case "chats":
      return renderHomeChatCards(state,width,height);
    case "apps": {
      const apps=visibleTuiApps(state.apps,state.filter),visible=state.homeShowAll||state.filter?apps:apps.slice(0,Math.max(6,state.selectedIndex+1));
      return [...homeHeader(state,width,height),...homeCards(renderTuiAppsHome(visible,{width:Math.min(width,88),selectedId:state.focus==="content"?apps[state.selectedIndex]?.id:undefined}),width,visible.map((app)=>APP_GRADIENTS[app.id]??PRIMARY_GRADIENT)),"Show all  ·  /search Search apps"];
    }
    case "app": {
      const app=state.activeApp;if(!app)return ["Loading app…"];
      const header=renderTuiAppIdentity(app,width),gradient=APP_GRADIENTS[app.id]??PRIMARY_GRADIENT;
      if(state.appTab==="embeds"||state.appTab==="workflows")return [...coloredHero(header,header.length,gradient),...renderTuiAppTabs(state.appTab,width),
        ...state.appTab==="embeds"?renderTuiAppsResults(state.appResults,{width,selectedId:state.appResults.items[state.selectedIndex]?.embedId}):renderTuiAppsWorkflows(state.appWorkflows,{width,selectedId:state.appWorkflows.items[state.selectedIndex]?.id})];
      return coloredHero(renderTuiApp(app,{width,tab:state.appTab,selectedId:state.activeApp.skills[state.selectedIndex]?.id}),header.length,gradient);
    }
    case "app-skill": {
      const skill=state.activeAppSkill;if(!skill)return ["Loading skill…"];
      const header=renderTuiAppsSkillIdentity(skill,width),gradient=APP_GRADIENTS[skill.appId]??PRIMARY_GRADIENT;
      if(state.appSkillTab==="embeds"||state.appSkillTab==="workflows")return [...coloredHero(header,header.length,gradient),...renderTuiAppsSkillTabs(state.appSkillTab,width),
        ...state.appSkillTab==="embeds"?renderTuiAppsResults(state.appResults,{width,selectedId:state.appResults.items[state.selectedIndex]?.embedId}):renderTuiAppsWorkflows(state.appWorkflows,{width,selectedId:state.appWorkflows.items[state.selectedIndex]?.id})];
      return coloredHero(renderTuiAppsSkill(skill,{width,tab:state.appSkillTab}),header.length,gradient);
    }
    case "app-result": return state.activeAppResult ? renderTuiAppsResult(state.activeAppResult,width):["Loading saved result…"];
    case "projects":
      return [...homeHeader(state,width,height),...homeCards(renderProjectList(state.projects, { width, selectedId: state.projects.filter((p) => `${p.name} ${p.description}`.toLowerCase().includes(state.filter.toLowerCase()))[state.selectedIndex]?.id, query: state.filter }),width,[])];
    case "project":
      return state.activeProject ? state.projectTab === "tasks"
        ? [...blueHero(renderProjectIdentity(state.activeProject,{width}),renderProjectIdentity(state.activeProject,{width}).length),...renderProjectTabs("tasks",width),"",...renderTaskBoard(state.tasks, { width, selectedTaskId: filterTasks(state.tasks, state.filter)[state.selectedIndex]?.taskId, query: state.filter })]
        : blueHero(renderProjectDetail(state.activeProject, { width, tab: state.projectTab, files: state.projectFiles, selectedFileId: filteredProjectFiles(state.projectFiles,state.filter)[state.selectedIndex]?.id, query: state.filter, folderId:state.projectFolderId??undefined, sourceId:state.projectSourceId??undefined, path:state.projectPath }),renderProjectIdentity(state.activeProject,{width}).length) : ["Projects", "Loading project…"];
    case "status":
      return renderStatus(state, width);
    case "embed":
      return [state.detailTitle || "Embed", "", ...state.detailLines].flatMap((line) => wrap(line, width));
    case "workflows":
      return [...homeHeader(state,width,height),...homeCards(state.workflows.filter((w)=>w.title.toLowerCase().includes(state.filter.toLowerCase())).flatMap((w,i)=>[...renderWorkflowPreviewCard(w,{width:Math.min(width,88),selected:state.focus==="content"&&i===state.selectedIndex}),""]),width,[]),"Show my workflows  ·  /search Search"];
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
    "  /embed <id>        Open an embed detail view",
    "  /exit              Leave OpenMates and restore terminal",
    "",
    "Outside TUI: openmates --help, openmates chats --help, openmates apps --help",
  ].flatMap((line) => wrap(line, width));
}

function renderTasks(state: TuiState, width: number): string[] {
  return renderTaskBoard(state.tasks, { width, selectedTaskId: filterTasks(state.tasks, state.filter, (state.taskStatusFilter || undefined) as UserTaskStatus | undefined)[state.selectedIndex]?.taskId, query: state.filter, status: (state.taskStatusFilter || undefined) as UserTaskStatus | undefined });
}

function renderTaskDetail(state: TuiState, width: number): string[] {
  if (!state.activeTask) return renderTasks(state, width);
  return renderTaskDetails(state.activeTask, { width, activity: state.taskContext?.activity, dependencies: state.taskContext?.dependencies });
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
  return blueHero(lines,renderWorkflowIdentity(state.activeWorkflow,{width,run:state.workflowTab==="runs"?state.workflowRuns[state.selectedWorkflowRunIndex]:undefined}).length);
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

function renderExampleChat(state: TuiState, width: number): string[] {
  const convo = state.activeExample;
  if (!convo) return renderExamples(state, width);
  const embeds = new Map<string, DecryptedEmbed>((convo.embeds ?? []).map((embed) => {
    const content = parseEmbedContentObject(embed.content);
    return [embed.embed_id, {id: embed.embed_id, embedId: embed.embed_id, type: embed.type, content, textPreview: null,
      appId: typeof content.app_id === "string" ? content.app_id : null,
      skillId: typeof content.skill_id === "string" ? content.skill_id : null, createdAt: null}];
  }));
  const lines = [
    ...renderChatHeader(state, width),
    `Example chat: ${convo.chat.title ?? convo.chat.slug}`,
    "",
  ];
  for (const message of convo.messages) {
    lines.push(labelForRole(message.role));
    lines.push(...renderMessageContent(message.content, width, embeds));
    lines.push("");
  }
  if (convo.followUpSuggestions.length > 0) {
    lines.push("Follow-up ideas:");
    for (const [index, suggestion] of convo.followUpSuggestions.slice(0, 3).entries()) {
      lines.push(`  ${index + 1}. ${suggestion}`);
    }
  }
  return lines.flatMap((line) => wrap(line, width));
}

function renderChat(state: TuiState, width: number): string[] {
  const lines = renderChatHeader(state, width);
  for (const message of state.messages) {
    lines.push(message.title ?? labelForRole(message.role));
    lines.push(...renderMessageContent(message.content, width));
    lines.push("");
  }
  if (state.isBusy) lines.push("Sophia is typing...");
  if (state.followUpSuggestions.length) lines.push("", "Suggestions", ...state.followUpSuggestions.slice(0, 3).map((s, i) => `  ${i + 1}. ${s}`));
  if (state.status) lines.push("", state.status);
  return lines.flatMap((line) => wrap(line, width));
}

export function renderChatHeader(state: TuiState, width: number): string[] {
  const chat = state.screen === "example" ? state.activeExample?.chat : state.activeChat;
  const title = state.headerState === "loading" && !chat?.title ? "Creating new chat…"
    : state.headerState === "error" ? state.headerError || "Could not send message"
    : chat?.title || (state.messages.length ? "Chat" : "New chat");
  const category = chat?.category?.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  const summary = chat?.summary || (state.messages.length ? "" : "What would you like to work on?");
  const badges = state.screen === "example" ? "Example chat" : state.input && !state.messages.length ? "Draft" : "";
  const timestamp = chat && "createdAt" in chat ? chat.createdAt : null;
  const when = timestamp ? `Started ${relativeTime(timestamp)}` : "";
  const meta = [category, when, badges, state.selectedProjectId && state.activeProject?.name].filter(Boolean).join("  ·  ");
  return ["", ...wrap(`  ${title}`, width), ...wrap(`  ${summary}`, width).slice(0, 2), meta ? truncateCells(`  ${meta}`, width) : "", ""];
}

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
  return parseMessageSegments(content, {preserveCodeFences: true}).flatMap((segment) => {
    if (segment.type === "text") return renderTextContent(segment.value, width);
    const meta = segment.meta ?? {};
    const saved = embeds.get(segment.value);
    if (saved) {
      const embed = {...saved, content: {...meta, ...saved.content},
        appId: saved.appId ?? (typeof meta.app_id === "string" ? meta.app_id : null),
        skillId: saved.skillId ?? (typeof meta.skill_id === "string" ? meta.skill_id : null)};
      return formatEmbedPreviewLines(embed, 2).map((line) => line.startsWith("└─") ? `└─ /embed ${embed.embedId}` : line).flatMap((line) => wrap(line, width));
    }
    const app = typeof meta.app_id === "string" ? meta.app_id : "Embed";
    const skill = typeof meta.skill_id === "string" ? `/${meta.skill_id}` : "";
    const title = [meta.title, meta.name, meta.query].find((value) => typeof value === "string");
    return [`┌─ ${app}${skill}${title ? ` · ${title}` : ""}`, `└─ /embed ${segment.value}`].flatMap((line) => wrap(line, width));
  });
}

function renderTextContent(content: string, width: number): string[] {
  const lines: string[] = [];
  const rawLines = content.replace(/\n{3,}/g, "\n\n").split("\n");
  let inFence = false;
  let fenceLines = 0;
  for (const rawLine of rawLines) {
    if (rawLine.startsWith("```") || rawLine.startsWith("~~~")) {
      inFence = !inFence;
      fenceLines = 0;
      lines.push(rawLine);
      continue;
    }
    if (inFence) {
      if (fenceLines < CONTENT_PREVIEW_LINES) {
        lines.push(rawLine);
      } else if (fenceLines === CONTENT_PREVIEW_LINES) {
        lines.push("...");
      }
      fenceLines += 1;
      continue;
    }
    lines.push(...wrap(rawLine, width));
  }
  return lines;
}

function interestScore(haystack: string, interest: string): number {
  let score = haystack.includes(interest) ? 10 : 0;
  for (const token of interest.split(/\s+|&/).filter((part) => part.length > 2)) {
    if (haystack.includes(token)) score += 2;
  }
  return score;
}

function labelForRole(role: string): string {
  if (role === "user") return "You";
  if (role === "system") return "System";
  return "Sophia";
}

function wrap(line: string, width: number): string[] {
  return wrapCells(line, width);
}
