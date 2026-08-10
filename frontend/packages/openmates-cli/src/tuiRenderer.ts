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
import type { WorkflowDetail, WorkflowNode, WorkflowNodeRun, WorkflowRunDetail, WorkflowSummary } from "./client.js";
import { openMatesAsciiLogo } from "./branding.js";
import type { DecryptedUserTask } from "./tasksCli.js";

export type TuiScreen = "start" | "help" | "interests" | "examples" | "example" | "chat" | "embed" | "workflows" | "workflow" | "tasks" | "task" | "status";

export type TuiMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  title?: string | null;
};

export type TuiWorkflowEdit = {
  nodeId: string;
  field: "title" | "config";
  value: string;
};

export type TuiState = {
  screen: TuiScreen;
  input: string;
  scrollOffset: number;
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

const MIN_WIDTH = 48;
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
    screen: "start",
    input: "",
    scrollOffset: 0,
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

export function renderTuiFrame(state: TuiState, width: number, height: number): string {
  const safeWidth = Math.max(MIN_WIDTH, width);
  const safeHeight = Math.max(12, height);
  const innerWidth = safeWidth - 4;
  const header = topBorder(safeWidth);
  const footer = bottomBorder(safeWidth);
  const contentHeight = safeHeight - 4;
  const body = renderBody(state, innerWidth);
  const visible = sliceForScroll(body, contentHeight, state.scrollOffset, state.screen === "chat");
  const inputLine = state.screen === "interests" || state.screen === "examples" || state.screen === "workflows" || state.screen === "workflow" || state.screen === "tasks" || state.screen === "task"
    ? renderHintLine(state, innerWidth)
    : `> ${state.input || inputPlaceholder(state)}`;
  const lines = [
    header,
    ...padLines(visible, contentHeight, innerWidth).map((line) => boxed(line, innerWidth)),
    separator(safeWidth),
    boxed(truncateVisible(inputLine, innerWidth), innerWidth),
    footer,
  ];
  return lines.join("\n");
}

function renderBody(state: TuiState, width: number): string[] {
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
    case "status":
      return renderStatus(state, width);
    case "embed":
      return renderStatus(state, width);
    case "workflows":
      return renderWorkflows(state, width);
    case "workflow":
      return renderWorkflowDetail(state, width);
    case "tasks":
      return renderTasks(state, width);
    case "task":
      return renderTaskDetail(state, width);
    case "start":
    default:
      return renderStart(width);
  }
}

function renderStart(width: number): string[] {
  return [
    "",
    ...openMatesAsciiLogo(width),
    "",
    "AI team mates.",
    "For everyday tasks & learning.",
    "With privacy & safety by design.",
    "",
    "Type a message to start chatting.",
    "Check example chats via /examples",
    "",
    "File references:",
    "Type @./notes.md, @~/Downloads/report.pdf, or @src/app.ts in your message.",
    "Images, PDFs, audio, and code files are attached as encrypted embeds when you are signed in.",
    "",
    "Shortcuts: /help  /login  /signup  /examples  /tasks  /exit",
  ].flatMap((line) => wrap(line, width));
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
  const lines = ["Tasks", ""];
  if (state.tasks.length === 0) {
    lines.push("No tasks found.", "Create one outside TUI with: openmates tasks create --title <title>");
    return lines.flatMap((line) => wrap(line, width));
  }
  const visibleCount = Math.max(1, CONTENT_PREVIEW_LINES);
  const start = Math.max(0, Math.min(state.selectedIndex, state.tasks.length - visibleCount));
  for (let i = 0; i < state.tasks.slice(start, start + visibleCount).length; i += 1) {
    const absoluteIndex = start + i;
    const task = state.tasks[absoluteIndex];
    const cursor = absoluteIndex === state.selectedIndex ? ">" : " ";
    const assignee = task.assigneeType === "ai" ? "OpenMates" : (task.assigneeHash ?? "user");
    lines.push(`${cursor} ${task.shortId}  ${task.status}  ${assignee}  ${task.title}`);
    if (task.queueState !== "none") lines.push(`    queue: ${task.queueState}`);
    if (task.description) lines.push(`    ${task.description}`);
    lines.push("");
  }
  return lines.flatMap((line) => wrap(line, width));
}

function renderTaskDetail(state: TuiState, width: number): string[] {
  const task = state.activeTask;
  if (!task) return renderTasks(state, width);
  const assignee = task.assigneeType === "ai" ? "OpenMates" : (task.assigneeHash ?? "user");
  const lines = [
    `Task: ${task.shortId}`,
    `Title: ${task.title}`,
    `Status: ${task.status}`,
    `Assignee: ${assignee}`,
    `Queue: ${task.queueState}`,
    `ID: ${task.taskId}`,
    task.description ? `Description: ${task.description}` : null,
    task.primaryChatId ? `Chat: ${task.primaryChatId}` : null,
    task.linkedProjectIds.length > 0 ? `Projects: ${task.linkedProjectIds.join(", ")}` : null,
    task.blockedReasonCode ? `Blocked reason: ${task.blockedReasonCode}` : null,
    task.aiExecutionState ? `AI state: ${task.aiExecutionState}` : null,
    "",
    "Actions: c create, e edit, x delete, r reorder, s start, d done, b block, u unblock, k skip, Esc back",
  ].filter((line): line is string => line !== null);
  return lines.flatMap((line) => wrap(line, width));
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

function renderWorkflowDetail(state: TuiState, width: number): string[] {
  const workflow = state.activeWorkflow;
  if (!workflow) return renderWorkflows(state, width);
  const graphNodes = workflow.graph?.nodes ?? [];
  const selectedRun = state.workflowRuns[state.selectedWorkflowRunIndex] ?? null;
  const lines = [
    `Workflow: ${workflow.title}`,
    `ID: ${workflow.id}`,
    `Status: ${workflow.enabled ? "enabled" : "disabled"}`,
    workflow.trigger_summary ? `Trigger: ${workflow.trigger_summary}` : null,
    workflow.next_run_at ? `Next run: ${formatTimestamp(workflow.next_run_at)}` : null,
    workflow.last_run_status ? `Last run: ${workflow.last_run_status}` : null,
    "",
    state.workflowTab === "graph" ? "[Graph]  Runs" : "Graph  [Runs]",
    "",
  ].filter((line): line is string => line !== null);
  if (state.workflowTab === "runs") {
    lines.push(...renderRunSelector(state, width), "");
    if (selectedRun) {
      lines.push(`Run graph: ${selectedRun.id} (${selectedRun.status})`);
      lines.push(...renderWorkflowGraph({ nodes: graphNodes, state, width, run: selectedRun }));
    } else {
      lines.push("No runs yet.");
    }
  } else {
    lines.push("Graph");
    lines.push(...renderWorkflowGraph({ nodes: graphNodes, state, width, run: null }));
    if (state.workflowEdit) lines.push("", `Editing ${state.workflowEdit.field}: ${state.workflowEdit.value}`);
  }
  if (state.status) lines.push("", state.status);
  return lines.flatMap((line) => wrap(line, width));
}

function renderRunSelector(state: TuiState, width: number): string[] {
  if (state.workflowRuns.length === 0) return ["Runs", "No runs yet."];
  const lines = ["Runs"];
  const visibleRuns = state.workflowRuns.slice(0, 5);
  for (let index = 0; index < visibleRuns.length; index += 1) {
    const run = visibleRuns[index];
    const cursor = index === state.selectedWorkflowRunIndex ? ">" : " ";
    lines.push(`${cursor} ${run.id}  ${run.status}  ${formatTimestamp(run.started_at)}`);
  }
  return lines.map((line) => truncateVisible(line, width));
}

function renderWorkflowGraph(params: {
  nodes: WorkflowNode[];
  state: TuiState;
  width: number;
  run: WorkflowRunDetail | null;
}): string[] {
  const { nodes, state, run } = params;
  if (nodes.length === 0) return ["No graph nodes available."];
  const lines: string[] = [];
  const selectedIndex = state.workflowTab === "runs" ? selectedRunGraphNodeIndex(nodes, state) : state.selectedWorkflowNodeIndex;
  const expandedId = state.workflowTab === "runs" ? state.expandedWorkflowRunNodeId : state.expandedWorkflowNodeId;
  const nodeRunsById = new Map((run?.node_runs ?? []).map((nodeRun) => [nodeRun.node_id, nodeRun]));
  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    const nodeRun = nodeRunsById.get(node.id) ?? null;
    const cursor = index === selectedIndex ? ">" : " ";
    const status = nodeRun ? ` [${nodeRun.status}]` : "";
    lines.push(`${cursor} [${nodeTypeLabel(node.type)}] ${node.title ?? cardSummary(node)}${status}`);
    if (nodeRun?.output_summary) lines.push(`    output: ${summarizeObject(nodeRun.output_summary)}`);
    if (nodeRun?.error_summary) lines.push(`    error: ${nodeRun.error_summary}`);
    if (expandedId === node.id) {
      lines.push(...renderExpandedNode(node, nodeRun));
    }
    if (index < nodes.length - 1) lines.push("    |");
  }
  return lines;
}

function selectedRunGraphNodeIndex(nodes: WorkflowNode[], state: TuiState): number {
  const run = state.workflowRuns[state.selectedWorkflowRunIndex];
  const nodeRun = run?.node_runs?.find((candidate) => candidate.node_id === state.expandedWorkflowRunNodeId);
  if (!nodeRun) return Math.min(state.selectedWorkflowNodeIndex, Math.max(0, nodes.length - 1));
  return Math.max(0, nodes.findIndex((node) => node.id === nodeRun.node_id));
}

function renderExpandedNode(node: WorkflowNode, nodeRun: WorkflowNodeRun | null): string[] {
  const lines = [
    `    id: ${node.id}`,
    `    type: ${node.type}`,
  ];
  if (node.config && Object.keys(node.config).length > 0) lines.push(`    config: ${summarizeObject(node.config)}`);
  if (node.input_mapping && Object.keys(node.input_mapping).length > 0) lines.push(`    input: ${summarizeObject(node.input_mapping)}`);
  if (nodeRun?.input_summary) lines.push(`    run input: ${summarizeObject(nodeRun.input_summary)}`);
  if (nodeRun?.output_summary) lines.push(`    run output: ${summarizeObject(nodeRun.output_summary)}`);
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

function renderExampleChat(state: TuiState, width: number): string[] {
  const convo = state.activeExample;
  if (!convo) return renderExamples(state, width);
  const lines = [
    `Example chat: ${convo.chat.title ?? convo.chat.slug}`,
    "",
  ];
  for (const message of convo.messages) {
    lines.push(labelForRole(message.role));
    lines.push(...renderMessageContent(message.content, width));
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
  const lines = ["OpenMates", ""];
  for (const message of state.messages) {
    lines.push(message.title ?? labelForRole(message.role));
    lines.push(...renderMessageContent(message.content, width));
    lines.push("");
  }
  if (state.isBusy) lines.push("Sophia is typing...");
  if (state.status) lines.push("", state.status);
  return lines.flatMap((line) => wrap(line, width));
}

function renderStatus(state: TuiState, width: number): string[] {
  return ["OpenMates", "", state.status ?? "Working..."]
    .flatMap((line) => wrap(line, width));
}

export function renderMessageContent(content: string, width: number): string[] {
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

function renderHintLine(state: TuiState, width: number): string {
  if (state.screen === "interests") return truncateVisible("↑/↓ move   Space select   Enter continue   Esc back", width);
  if (state.screen === "tasks") return truncateVisible("↑/↓ choose   Enter open   c create   Esc back", width);
  if (state.screen === "task") return truncateVisible("c create   e edit   x delete   r reorder   s start   d done   b block   u unblock   k skip", width);
  if (state.screen === "workflows") return truncateVisible("↑/↓ choose   Enter open   Esc back", width);
  if (state.screen === "workflow" && state.workflowEdit) return truncateVisible("Enter save title   Esc cancel edit", width);
  if (state.screen === "workflow") return truncateVisible("g graph   r runs   ↑/↓ select   Enter expand   e title   E config   x run   u refresh   c cancel", width);
  return truncateVisible("↑/↓ choose   Enter open   /search filter   Esc back", width);
}

function inputPlaceholder(state: TuiState): string {
  if (state.screen === "example") return "Continue from this example, or ask your own question...";
  if (state.screen === "chat") return "Ask a follow-up, use @file, or type /help";
  if (state.screen === "workflow" || state.screen === "workflows" || state.screen === "tasks" || state.screen === "task") return "Use shortcuts below, or type /help";
  return "Ask anything...";
}

function nodeTypeLabel(type: string): string {
  switch (type) {
    case "manual_trigger": return "manual trigger";
    case "schedule_trigger": return "schedule";
    case "app_skill_action": return "app skill";
    case "send_notification": return "notification";
    case "ask_user": return "ask user";
    default: return type.replaceAll("_", " ");
  }
}

function cardSummary(node: WorkflowNode): string {
  const config = node.config ?? {};
  if (node.type === "app_skill_action") {
    const app = typeof config.app === "string" ? config.app : "app";
    const skill = typeof config.skill === "string" ? config.skill : "skill";
    return `${app}.${skill}`;
  }
  if (node.type === "decision") return "If condition";
  if (node.type === "send_notification") return "Send notification";
  if (node.type === "ask_user") return "Ask for user input";
  return node.id;
}

function formatTimestamp(value?: number | null): string {
  if (!value) return "-";
  return new Date(value * 1000).toISOString().replace("T", " ").slice(0, 16);
}

function summarizeObject(value: Record<string, unknown>): string {
  const entries = Object.entries(value).slice(0, 3).map(([key, item]) => `${key}=${String(item)}`);
  return entries.join(", ") || "object";
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

function sliceForScroll(lines: string[], height: number, scrollOffset: number, bottomAnchored: boolean): string[] {
  const maxStart = Math.max(0, lines.length - height);
  const start = bottomAnchored
    ? Math.max(0, Math.min(maxStart, maxStart - scrollOffset))
    : Math.max(0, Math.min(maxStart, scrollOffset));
  return lines.slice(start, start + height);
}

function wrap(line: string, width: number): string[] {
  if (line.length <= width) return [line];
  const out: string[] = [];
  let remaining = line;
  while (remaining.length > width) {
    const boundary = Math.max(1, remaining.slice(0, width + 1).lastIndexOf(" "));
    out.push(remaining.slice(0, boundary).trimEnd());
    remaining = remaining.slice(boundary).trimStart();
  }
  out.push(remaining);
  return out;
}

function padLines(lines: string[], height: number, width: number): string[] {
  const padded = [...lines];
  while (padded.length < height) padded.push("");
  return padded.slice(0, height).map((line) => truncateVisible(line, width));
}

function truncateVisible(line: string, width: number): string {
  return line.length > width ? `${line.slice(0, Math.max(0, width - 1))}…` : line;
}

function topBorder(width: number): string {
  return `┌${"─".repeat(width - 2)}┐`;
}

function separator(width: number): string {
  return `├${"─".repeat(width - 2)}┤`;
}

function bottomBorder(width: number): string {
  return `└${"─".repeat(width - 2)}┘`;
}

function boxed(line: string, width: number): string {
  return `│ ${line.padEnd(width)} │`;
}
