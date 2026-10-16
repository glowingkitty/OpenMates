/** Plain-text Tasks workspace model and mutations for the terminal UI. */
import type { OpenMatesClient, UserTaskStatus, WorkDependencyRecord } from "./client.js";
import { formValue, type TuiForm } from "./tuiForms.js";
import { cells, lineText, padCells, terminalText, truncateCells, wrapCells, type TuiLine, type TuiSpan } from "./tuiText.js";
import { pointerLine } from "./tuiPointer.js";
import {
  TASK_STATUSES,
  buildBlockUserTaskInput,
  buildCreateTaskActivityInput,
  buildCreateUserTaskInput,
  buildUpdateUserTaskInput,
  decryptTaskActivityEntries,
  decryptUserTask,
  decryptUserTasks,
  normalizeTaskStatus,
  taskIdentityDisplayName,
  type DecryptedTaskActivityEntry,
  type DecryptedUserTask,
} from "./tasksCli.js";

const STATUS_LABELS: Record<UserTaskStatus, string> = {
  backlog: "Backlog", todo: "Todo", in_progress: "In progress", blocked: "Blocked", done: "Done",
};
const STATUS_COLORS: Record<UserTaskStatus, string> = {
  backlog: "#bf5af2", todo: "#32ade6", in_progress: "#f0a050", blocked: "#ff6b6b", done: "#30d158",
};
const SELECTED_BACKGROUND = "#263b52";
type ColoredSpan = TuiSpan & { color?: string };

function styledLine(spans: ColoredSpan[]): TuiLine {
  return {text: spans.map((span) => span.text).join(""), spans};
}

function columnHeader(status: UserTaskStatus, count: number, width: number): TuiLine {
  const heading = truncateCells(`${STATUS_LABELS[status]} (${count})`, Math.max(0, width - 2));
  return styledLine([
    {text: "▌", color: STATUS_COLORS[status], bold: true},
    {text: ` ${heading}`, bold: true},
    {text: " ".repeat(Math.max(0, width - 2 - cells(heading)))},
  ]);
}

function joinColumns(rows: TuiLine[], width: number, gap: string): TuiLine {
  const spans: ColoredSpan[] = [];
  rows.forEach((row, index) => {
    if (index) spans.push({text: gap});
    if (typeof row === "string") spans.push({text: padCells(row, width)});
    else {
      spans.push(...(row.spans as ColoredSpan[] | undefined ?? [{text: row.text, background: row.background, bold: row.bold, color: row.color}])
        .map((span) => ({...span, action: span.action ?? row.action})));
      const padding = Math.max(0, width - cells(lineText(row)));
      if (padding) spans.push({text: " ".repeat(padding)});
    }
  });
  return styledLine(spans);
}

const oneLine = (value: string): string => terminalText(value).replace(/\s+/g, " ").trim();
const label = (task: DecryptedUserTask): string => task.shortId || task.slug || task.taskId;
const assignee = (task: DecryptedUserTask): string =>
  taskIdentityDisplayName(task.assigneeIdentity) ?? (task.assigneeType === "unassigned" ? "Unassigned" : task.assigneeType === "external_ai" ? "External AI" : task.assigneeType === "openmates" ? "OpenMates" : "User");
const queue = (task: DecryptedUserTask): string => task.queueState && task.queueState !== "none" ? ` · queue: ${task.queueState}` : "";
const sorted = (tasks: DecryptedUserTask[]): DecryptedUserTask[] => [...tasks].sort((a, b) => a.position - b.position || a.title.localeCompare(b.title));

export function filterTasks(tasks: DecryptedUserTask[], query: string, status?: UserTaskStatus): DecryptedUserTask[] {
  const words = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return sorted(tasks.filter((task) => {
    if (status && task.status !== status) return false;
    if (!words.length) return true;
    const haystack = [task.shortId, task.slug, task.title, task.description, task.labels.join(" "), task.tags.join(" "), task.status, task.assigneeIdentity ?? "", task.assigneeHash ?? "", task.queueState].join(" ").toLocaleLowerCase();
    return words.every((word) => haystack.includes(word));
  }));
}

/** Complete board row indices, start inclusive and end exclusive. */
type BoardViewport = { start: number; end: number; followSelection?: boolean };
type BoardCard = { task: DecryptedUserTask; index: number; start: number; end: number };
type TitleHeightCache = { title: string; widths: Map<number, { selected?: number; unselected?: number }> };
const titleHeightCache = new WeakMap<DecryptedUserTask, TitleHeightCache>();

function taskTitleLines(task: DecryptedUserTask, width: number, selected: boolean): string[] {
  return wrapCells(`${selected ? "› " : "  "}${task.title || "Untitled task"}`, Math.max(8, width - 2)).slice(0, 2);
}

/** Retain only a title row count; card content and pointer actions are always fresh. */
function taskTitleHeight(task: DecryptedUserTask, width: number, selected: boolean): number {
  let cache = titleHeightCache.get(task);
  if (!cache || cache.title !== task.title) {
    cache = {title: task.title, widths: new Map()};
    titleHeightCache.set(task, cache);
  }
  let counts = cache.widths.get(width);
  if (!counts) {
    if (cache.widths.size >= 3) {
      const oldest = cache.widths.keys().next().value;
      if (oldest !== undefined) cache.widths.delete(oldest);
    }
    counts = {};
    cache.widths.set(width, counts);
  }
  const key = selected ? "selected" : "unselected";
  return counts[key] ?? (counts[key] = taskTitleLines(task, width, selected).length);
}

/** Card height must use the same cell-aware title wrapping as taskCard. */
function taskCardHeight(task: DecryptedUserTask, width: number, selected: boolean): number {
  const titleRows = taskTitleHeight(task, width, selected);
  return 2 + titleRows + 1 + 1 + Number(task.linkedProjectIds.length > 0) + Number(Boolean(task.dueAt))
    + Number(task.priority > 1) + Number(Boolean(task.queueState && task.queueState !== "none"));
}

function cardPositions(group: DecryptedUserTask[], width: number, selectedTaskId: string | undefined, separatorRows: number): { cards: BoardCard[]; height: number } {
  let height = 0;
  const cards = group.map((task, index) => {
    const start = height;
    const end = start + taskCardHeight(task, width, task.taskId === selectedTaskId);
    height = end + separatorRows;
    return { task, index, start, end };
  });
  return {cards, height};
}

/** Clamp End jumps to the real tail and keep selection's neighboring rows ready. */
function boardWindows(viewport: BoardViewport, fullHeight: number, stackStart: number, selected?: BoardCard): BoardViewport[] {
  const requestedStart = Math.floor(viewport.start);
  const span = Math.min(fullHeight, Math.max(0, Math.ceil(viewport.end) - requestedStart));
  const start = Math.min(Math.max(0, requestedStart), Math.max(0, fullHeight - span));
  const end = start + span;
  const windows = [{start, end}];
  if (selected && viewport.followSelection !== false) {
    const padding = Math.max(1, end - start);
    windows.push({start: Math.max(0, stackStart + selected.start - padding), end: stackStart + selected.end + padding});
  }
  return windows;
}

function intersects(start: number, end: number, windows: BoardViewport[]): boolean {
  return windows.some((window) => start < window.end && end > window.start);
}

export function renderTaskBoard(tasks: DecryptedUserTask[], options: { width: number; selectedTaskId?: string; query?: string; status?: UserTaskStatus; viewport?: BoardViewport }): TuiLine[] {
  const width = Math.max(18, options.width);
  const visible = filterTasks(tasks, options.query ?? "");
  const chips = [...new Set(tasks.flatMap((task) => task.labels))].filter(Boolean).slice(0, 3);
  const search = options.query ? `Search: ${oneLine(options.query)}` : "Search: /search";
  const lines: TuiLine[] = [
    truncateCells(`Tasks board  ·  ${visible.length} ${visible.length === 1 ? "task" : "tasks"}`, width),
    truncateCells(width < 90 ? search : `${search}  ·  Filter: All statuses`, width),
    ...(width >= 90 && chips.length ? [truncateCells(`Tags  ${chips.map((chip) => `#${chip}`).join("  ")}`, width)] : []),
    "",
  ];
  const columns = TASK_STATUSES.map((status) => ({ status, tasks: visible.filter((task) => task.status === status) }));
  // Keep the selected status in view as the terminal narrows. A medium terminal
  // can still show adjacent Kanban columns without squeezing every card.
  const selected = visible.find((task) => task.taskId === options.selectedTaskId);
  const focused = options.status ?? selected?.status ?? columns.find((column) => column.tasks.length)?.status ?? "todo";
  const focusedIndex = TASK_STATUSES.indexOf(focused);
  const columnCount = width >= 110 ? 5 : width >= 96 ? 3 : width >= 70 ? 2 : 1;
  const firstColumn = Math.min(Math.max(focusedIndex - Math.floor(columnCount / 2), 0), columns.length - columnCount);
  if (columnCount > 1) {
    const gap = "  ";
    const shown = columns.slice(firstColumn, firstColumn + columnCount);
    const colWidth = Math.floor((width - gap.length * (columnCount - 1)) / columnCount);
    lines.push(truncateCells(`←/→ columns  ·  ${STATUS_LABELS[focused]} ${focusedIndex + 1}/5`, width));
    lines.push(joinColumns(shown.map(({status, tasks}) => pointerLine(columnHeader(status, tasks.length, colWidth),
      {kind:"select",target:"task",column:TASK_STATUSES.indexOf(status),index:0})), colWidth, gap));
    lines.push(shown.map(() => "─".repeat(colWidth)).join(gap));
    if (!options.viewport) {
      const stacks = shown.map(({tasks: group}) => group.length
        ? group.flatMap((task, index) => [...taskCard(task, colWidth, task.taskId === options.selectedTaskId,
            {kind:"select",target:"task",column:TASK_STATUSES.indexOf(task.status),index,id:task.taskId,activate:true}), ""])
        : [padCells("No tasks here.", colWidth)]);
      for (let row = 0; row < Math.max(...stacks.map((stack) => stack.length)); row++) {
        lines.push(joinColumns(stacks.map((stack) => stack[row] ?? ""), colWidth, gap));
      }
    } else {
      const stackStart = lines.length;
      const positions = shown.map(({tasks: group}) => cardPositions(group, colWidth, options.selectedTaskId, 1));
      const selectedCard = positions.flatMap(({cards}) => cards).find(({task}) => task.taskId === options.selectedTaskId);
      const totalRows = Math.max(...positions.map(({cards, height}) => cards.length ? height : 1));
      const windows = boardWindows(options.viewport, stackStart + totalRows, stackStart, selectedCard);
      const stacks = positions.map(({cards}) => {
        const rows = new Map<number, TuiLine>();
        if (!cards.length && intersects(stackStart, stackStart + 1, windows)) rows.set(0, padCells("No tasks here.", colWidth));
        for (const card of cards) {
          if (!intersects(stackStart + card.start, stackStart + card.end, windows)) continue;
          const rendered = taskCard(card.task, colWidth, card.task.taskId === options.selectedTaskId,
            {kind:"select",target:"task",column:TASK_STATUSES.indexOf(card.task.status),index:card.index,id:card.task.taskId,activate:true});
          rendered.forEach((line, offset) => rows.set(card.start + offset, line));
        }
        return rows;
      });
      for (let row = 0; row < totalRows; row++) {
        lines.push(intersects(stackStart + row, stackStart + row + 1, windows)
          ? joinColumns(stacks.map((stack) => stack.get(row) ?? ""), colWidth, gap) : "");
      }
    }
  } else {
    const group = columns[focusedIndex]?.tasks ?? [];
    lines.push(truncateCells(`←/→ columns  ·  ${STATUS_LABELS[focused]} ${focusedIndex + 1}/5`, width));
    lines.push(pointerLine(columnHeader(focused, group.length, Math.min(width, 52)),
      {kind:"select",target:"task",column:focusedIndex,index:0}), "─".repeat(Math.min(width, 52)));
    if (!group.length) lines.push("  No tasks here.");
    if (!options.viewport) {
      for (const [index, task] of group.entries()) {
        lines.push(...taskCard(task, Math.min(width, 52), task.taskId === options.selectedTaskId,
          {kind:"select",target:"task",column:focusedIndex,index,id:task.taskId,activate:true}));
      }
    } else {
      const stackStart = lines.length;
      const {cards, height} = cardPositions(group, Math.min(width, 52), options.selectedTaskId, 0);
      const windows = boardWindows(options.viewport, stackStart + height, stackStart, cards.find(({task}) => task.taskId === options.selectedTaskId));
      const rows: TuiLine[] = Array(height).fill("");
      for (const card of cards) {
        if (!intersects(stackStart + card.start, stackStart + card.end, windows)) continue;
        const rendered = taskCard(card.task, Math.min(width, 52), card.task.taskId === options.selectedTaskId,
          {kind:"select",target:"task",column:focusedIndex,index:card.index,id:card.task.taskId,activate:true});
        rendered.forEach((line, offset) => { rows[card.start + offset] = line; });
      }
      lines.push(...rows);
    }
  }
  return lines;
}

function taskCard(task: DecryptedUserTask, width: number, selected: boolean, action: TuiSpan["action"]): TuiLine[] {
  const inside = Math.max(8, width - 2);
  const edge = (selected ? "═" : "─").repeat(inside);
  const row = (value: string, title = false): TuiLine => {
    const content = padCells(value, inside);
    if (!selected) return `│${content}│`;
    return styledLine([
      {text: "║", color: STATUS_COLORS[task.status], background: SELECTED_BACKGROUND, bold: true},
      {text: content, background: SELECTED_BACKGROUND, bold: title},
      {text: "║", color: STATUS_COLORS[task.status], background: SELECTED_BACKGROUND, bold: true},
    ]);
  };
  const border = (top: boolean): TuiLine => {
    if (!selected) return top ? `╭${edge}╮` : `╰${edge}╯`;
    return styledLine([{text: top ? `╔${edge}╗` : `╚${edge}╝`, color: STATUS_COLORS[task.status], background: SELECTED_BACKGROUND, bold: true}]);
  };
  const titleLines = taskTitleLines(task, width, selected);
  const metadata = [task.linkedProjectIds.length ? "Project" : "", assignee(task), task.dueAt ? `Due ${new Date(task.dueAt * 1000).toISOString().slice(0, 10)}` : "", task.priority > 1 ? task.priorityLevel : ""].filter(Boolean);
  return [
    border(true),
    ...titleLines.map((title) => row(title, true)),
    row(`  ${label(task)}`),
    ...metadata.map((item) => row(`  ${item}`)),
    ...(task.queueState && task.queueState !== "none" ? [row(`Q ${task.queueState}`)] : []),
    border(false),
  ].map((line) => pointerLine(line, action!));
}

export type TaskContext = {
  activity: DecryptedTaskActivityEntry[];
  dependencies: { dependencies: WorkDependencyRecord[]; blockers: WorkDependencyRecord[] };
  nextCursor: string | null;
};

export async function loadTaskContext(client: OpenMatesClient, taskId: string): Promise<TaskContext> {
  const record = await client.getUserTask(taskId);
  if (!record) throw new Error(`Task ${taskId} was not found.`);
  const task = await decryptUserTask(record, client.getMasterKeyBytes());
  const [page, dependencies] = await Promise.all([
    client.listUserTaskActivity(taskId, { limit: 100, newestFirst: true }),
    client.getTaskDependencies(taskId),
  ]);
  return { activity: await decryptTaskActivityEntries(task, client.getMasterKeyBytes(), page.entries), dependencies, nextCursor: page.next_cursor };
}

export function renderTaskDetails(task:DecryptedUserTask,options:{width:number;activity?:DecryptedTaskActivityEntry[];dependencies?:TaskContext["dependencies"];pointer:true}):TuiLine[];
export function renderTaskDetails(task:DecryptedUserTask,options:{width:number;activity?:DecryptedTaskActivityEntry[];dependencies?:TaskContext["dependencies"]}):string[];
export function renderTaskDetails(task: DecryptedUserTask, options: { width: number; activity?: DecryptedTaskActivityEntry[]; dependencies?: TaskContext["dependencies"];pointer?:true }): TuiLine[] {
  const width = Math.max(18, options.width);
  const lines:TuiLine[] = [
    ...wrapCells(task.title || "Untitled task", width),
    truncateCells(`${label(task)}  ·  ${STATUS_LABELS[task.status]}`, width),
    "─".repeat(width),
    truncateCells(`Assigned to ${assignee(task)}  ·  Priority ${task.priorityLevel}${queue(task)}`, width),
  ];
  if (task.readOnly) lines.push("Read-only workflow task");
  if (task.linkedProjectIds.length) lines.push(truncateCells(`${task.linkedProjectIds.length} linked ${task.linkedProjectIds.length === 1 ? "Project" : "Projects"}`, width));
  if (task.labels.length) lines.push(truncateCells(`Labels: ${task.labels.join(", ")}`, width));
  if (task.dueAt) lines.push(`Due: ${new Date(task.dueAt * 1000).toISOString().slice(0, 16)} UTC`);
  if (task.blockedReason) lines.push(truncateCells(`Blocked: ${task.blockedReason}`, width));
  const firstActions="c create  e edit  m status  p assignee  r reorder";
  const secondActions="s start  d done  b block  u unblock  k skip  x delete";
  lines.push("", "Actions", ...(options.pointer?pointerTaskShortcuts(firstActions,width):wrapCells(firstActions,width)),
    ...(options.pointer?pointerTaskShortcuts(secondActions,width):wrapCells(secondActions,width)), "", "Description");
  lines.push(...wrapCells(task.description || "No description.", width));
  if (options.dependencies) {
    lines.push("", `Dependencies (${options.dependencies.dependencies.length})`);
    lines.push(...(options.dependencies.dependencies.length ? options.dependencies.dependencies.map((item) => truncateCells(`  → ${relationLabel(item.target_ref)}`, width)) : ["  None"]));
    lines.push(`Blockers (${options.dependencies.blockers.length})`);
    lines.push(...(options.dependencies.blockers.length ? options.dependencies.blockers.map((item) => truncateCells(`  ← ${relationLabel(item.source_ref)}`, width)) : ["  None"]));
  }
  if (options.activity) {
    lines.push("", `Activity (${options.activity.length} loaded)`);
    lines.push(...(options.activity.length ? options.activity.map((entry) => truncateCells(`  ${new Date(entry.createdAt * 1000).toISOString().slice(0, 16)} ${entry.actorDisplayName ?? taskIdentityDisplayName(entry.actorIdentity) ?? entry.actorType}: ${entry.kind === "comment" ? entry.message ?? "" : entry.nextStatus ? `→ ${STATUS_LABELS[entry.nextStatus]}` : entry.eventType}`, width)) : ["  No activity"]));
  }
  return lines;
}

/** Keep shortcut targets on their displayed cell fragments, including narrow wraps. */
function pointerTaskShortcuts(source:string,width:number):TuiLine[] {
  const ranges=[...source.matchAll(/(?:^| {2})([cemprsdbukx]) ([a-z]+)/g)].map((match)=>{
    const index=match.index+(match[0].startsWith("  ")?2:0);
    return {start:index,end:index+match[1].length+1+match[2].length,chunk:match[1]};
  });
  let rowStart=0;
  return wrapCells(source,width).map((row)=>{
    const rowEnd=rowStart+row.length,spans:TuiSpan[]=[];
    let cursor=rowStart;
    for(const range of ranges){
      const from=Math.max(rowStart,range.start),to=Math.min(rowEnd,range.end);
      if(to<=from)continue;
      if(from>cursor)spans.push({text:source.slice(cursor,from)});
      spans.push({text:source.slice(from,to),action:{kind:"key",name:"",chunk:range.chunk,focus:"content"}});
      cursor=to;
    }
    if(cursor<rowEnd)spans.push({text:source.slice(cursor,rowEnd)});
    rowStart=rowEnd;
    return {text:row,spans};
  });
}

function relationLabel(reference: string): string {
  const match = /^(task|plan):(.+)$/.exec(reference);
  if (!match) return truncateCells(reference, 32);
  const id = match[2];
  const readable = /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(id) || /^[0-9a-f]{32,}$/i.test(id)
    ? `${id.slice(0, 8)}…` : truncateCells(id, 24);
  return `${match[1] === "task" ? "Task" : "Plan"} ${readable}`;
}

export function buildTaskForm(kind: string, task?: DecryptedUserTask): TuiForm {
  const normalized = kind.startsWith("task-") ? kind : `task-${kind}`;
  const field = (name: string, labelText: string, value = "", options?: string[], multiline = false) => ({name, label: labelText, value, ...(options ? {options} : {}), ...(multiline ? {multiline} : {})});
  const fields: TuiForm["fields"] = normalized === "task-create" ? [
    field("title", "Title"), field("description", "Description", "", undefined, true), field("status", "Status", "todo", TASK_STATUSES), field("assignee", "Assignee", "user", ["user", "openmates", "codex", "unassigned"]),
  ] : normalized === "task-edit" ? [
    field("title", "Title", task?.title), field("description", "Description", task?.description, undefined, true),
  ] : normalized === "task-status" ? [field("status", "Status", task?.status ?? "todo", TASK_STATUSES)]
    : normalized === "task-assignee" ? [field("assignee", "Assignee", task?.assigneeIdentity ?? (task?.assigneeType === "unassigned" ? "unassigned" : "user"), ["user", "openmates", "codex", "unassigned"])]
    : normalized === "task-block" ? [field("reason", "Reason code", "needs_user_input", ["needs_user_input", "waiting_for_approval", "missing_credentials", "ambiguous_requirement", "external_dependency", "environment_unavailable", "verification_failed", "other"]), field("explanation", "Explanation (optional)", "", undefined, true)]
    : normalized === "task-activity" ? [field("message", "Activity message", "", undefined, true)]
    : normalized === "task-delete" ? [field("confirm", `Type DELETE to delete ${task ? label(task) : "task"}`)]
    : normalized === "task-reorder" ? [field("position", "Position", String(task?.position ?? ""))]
    : normalized === "task-dependency-add" ? [field("target", "Target task or plan reference")]
    : normalized === "task-dependency-remove" ? [field("target", "Target task or plan reference")]
    : normalized === "task-activity-delete" ? [field("entry", "Activity entry ID")]
    : [];
  const titles: Record<string, string> = {
    "task-create": "Create task", "task-edit": "Edit task", "task-status": "Move task", "task-assignee": "Assign task",
    "task-block": "Block task", "task-unblock": "Unblock task", "task-complete": "Complete task", "task-skip": "Skip task",
    "task-start": "Start task", "task-activity": "Add task activity", "task-activity-delete": "Delete task activity",
    "task-delete": "Delete task", "task-reorder": "Reorder task", "task-dependency-add": "Add task dependency",
    "task-dependency-remove": "Remove task dependency",
  };
  const title = titles[normalized] ?? `${normalized.slice(5).replace(/-/g, " ")} task`;
  return {kind: normalized, title: title + (task ? ` · ${label(task)}` : ""), fields, fieldIndex: 0, ...(task ? {contextId: task.taskId} : {})};
}

export async function submitTaskForm(client: OpenMatesClient, form: TuiForm, task?: DecryptedUserTask, projectId?: string): Promise<{ task?: DecryptedUserTask; deleted?: boolean }> {
  const kind = form.kind.startsWith("task-") ? form.kind : `task-${form.kind}`;
  const value = (name: string) => formValue(form, name).trim();
  const master = client.getMasterKeyBytes();
  if (kind === "task-create") {
    if (!value("title")) throw new Error("Task title is required.");
    const status = normalizeTaskStatus(value("status")) ?? "todo";
    const input = await buildCreateUserTaskInput(master, {title: value("title"), description: value("description"), status, assign: value("assignee") || "user", ...(projectId ? {projectIds: [projectId]} : {})});
    return {task: await decryptUserTask(await client.createUserTask(input), master)};
  }
  if (!task || form.contextId && form.contextId !== task.taskId) throw new Error("Task form context has changed.");
  if (task.readOnly) throw new Error("This workflow task is read-only.");
  if (kind === "task-edit") {
    if (!value("title")) throw new Error("Task title is required.");
    const patch = await buildUpdateUserTaskInput(task, master, {title: value("title"), description: value("description")});
    return {task: await decryptUserTask(await client.updateUserTask(task.taskId, patch), master)};
  }
  if (kind === "task-status" || kind === "task-assignee") {
    if (kind === "task-status" && !value("status")) throw new Error("Task status is required.");
    const options = kind === "task-status" ? {status: normalizeTaskStatus(value("status"))} : {assign: value("assignee") || "user"};
    const patch = await buildUpdateUserTaskInput(task, master, options);
    return {task: await decryptUserTask(await client.updateUserTask(task.taskId, patch), master)};
  }
  if (kind === "task-block") {
    const input = await buildBlockUserTaskInput(task, master, {reasonCode: value("reason"), ...(value("explanation") ? {reasonText: value("explanation")} : {})});
    return {task: await decryptUserTask(await client.blockUserTask(task.taskId, input), master)};
  }
  if (kind === "task-start") {
    if (task.assigneeType === "external_ai") throw new Error("A connected Codex task cannot start with OpenMates AI.");
    const result = await client.startUserTaskWithAI(task.taskId, {
      version: task.version, primary_chat_id: task.primaryChatId ?? undefined,
      linked_project_ids: task.linkedProjectIds, plaintext_title: task.title,
      plaintext_description: task.description, plaintext_latest_instruction: task.latestInstruction,
    });
    return {task: await decryptUserTask(result, master)};
  }
  if (kind === "task-unblock" || kind === "task-complete" || kind === "task-skip") {
    const input = {version: task.version};
    const result = kind === "task-unblock" ? await client.unblockUserTask(task.taskId, input) : kind === "task-complete" ? await client.completeUserTask(task.taskId, input) : await client.skipUserTask(task.taskId, input);
    return {task: await decryptUserTask(result, master)};
  }
  if (kind === "task-activity") {
    if (!value("message")) throw new Error("Activity message is required.");
    await client.createUserTaskActivity(task.taskId, await buildCreateTaskActivityInput(task, master, {message: value("message")}));
    return {task};
  }
  if (kind === "task-delete") {
    if (value("confirm") !== "DELETE") throw new Error("Type DELETE to confirm deletion.");
    const result = await client.deleteUserTask(task.taskId, task.version);
    if (!result.deleted) throw new Error("Task deletion was not confirmed by the server.");
    return {deleted: true};
  }
  if (kind === "task-reorder") {
    const position = Number(value("position"));
    if (!Number.isFinite(position)) throw new Error("Position must be a number.");
    const records = await client.reorderUserTasks({moves: [{task_id: task.taskId, version: task.version, position}]});
    const changed = (await decryptUserTasks(records, master)).find((item) => item.taskId === task.taskId);
    if (!changed) throw new Error("Reordered task was missing from the server response.");
    return {task: changed};
  }
  if (kind === "task-dependency-add") {
    if (!value("target")) throw new Error("Dependency reference is required.");
    await client.addTaskDependency(task.taskId, value("target"));
    return {task};
  }
  if (kind === "task-dependency-remove") {
    const target = value("target");
    const match = /^(task|plan):(.+)$/.exec(target);
    if (!match) throw new Error("Use task:<id> or plan:<id> to remove a dependency.");
    await client.removeTaskDependency(task.taskId, match[1] as "task" | "plan", match[2]);
    return {task};
  }
  if (kind === "task-activity-delete") {
    if (!value("entry")) throw new Error("Activity entry ID is required.");
    await client.deleteUserTaskActivity(task.taskId, value("entry"));
    return {task};
  }
  throw new Error(`Unsupported task form: ${kind}`);
}
