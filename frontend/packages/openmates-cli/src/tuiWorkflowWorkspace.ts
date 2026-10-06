/** Compact, edge-aware Workflow workspace for the terminal. */
import type { OpenMatesClient, WorkflowDetail, WorkflowGraph, WorkflowNode, WorkflowNodeRun, WorkflowRunDetail, WorkflowSummary } from "./client.js";
import type { TuiForm } from "./tuiForms.js";
import { formValue } from "./tuiForms.js";
import { cells, padCells, terminalText, truncateCells, wrapCells, type TuiLine } from "./tuiText.js";
import { centeredCarouselText, renderCardCarousel } from "./tuiCarousel.js";
import { PRIMARY_GRADIENT } from "../../appGradientTheme.js";

export type WorkflowWorkspaceOptions = {
  width: number;
  tab: "graph" | "runs";
  selectedNodeIndex?: number;
  expandedNodeId?: string | null;
  run?: WorkflowRunDetail | null;
  runs?: WorkflowRunDetail[];
  selectedRunIndex?: number;
  runGraph?: WorkflowGraph | null;
  edit?: {nodeId:string;field:"title"|"config";value:string};
};

/** Workflow summaries in the shared horizontal card viewport. */
export function renderWorkflowCarousel(workflows: WorkflowSummary[], width: number, selectedIndex: number, focused: boolean): TuiLine[] {
  if (!workflows.length) return [];
  const selected = Math.max(0, Math.min(workflows.length - 1, selectedIndex));
  const clean = (value: string) => terminalText(value).replace(/\s+/g, " ").trim();
  const cards = workflows.map((workflow) => ({
    title: clean(workflow.title),
    description: [workflow.description ? truncateCells(clean(workflow.description), 32) : "",
      truncateCells(clean(workflow.trigger_summary || "Manual"), 32)].filter(Boolean).join("\n"),
    footer: `${workflow.enabled ? "Enabled" : "Paused"}${workflow.last_run_status ? ` · Last: ${clean(workflow.last_run_status)}` : ""}`,
    background: PRIMARY_GRADIENT.start,
  }));
  return [...renderCardCarousel(cards, width, selected, focused), "",
    centeredCarouselText(`Workflow ${selected + 1} of ${workflows.length} · ←/→ choose workflow · Enter open`, width)];
}

export function renderWorkflowPreviewCard(workflow: WorkflowSummary, options: { width: number; selected?: boolean }): string[] {
  const status = workflow.enabled ? "Enabled" : "Paused";
  const lastRun = workflow.last_run_status ? `Last run: ${workflow.last_run_status}` : null;
  return panel("Workflow card", [
    `${options.selected ? "> " : "  "}${workflow.title}`,
    `${status}${workflow.trigger_summary ? ` · ${workflow.trigger_summary}` : ""}`,
    ...(lastRun ? [lastRun] : []),
  ], Math.max(1, options.width));
}

/** Full-width identity block. The frame renderer may style these rows as one hero. */
export function renderWorkflowIdentity(workflow: WorkflowSummary, options: { width: number;run?:WorkflowRunDetail }): string[] {
  const rows = [
    `Workflow: ${workflow.title}`,
    `Workflow ${workflow.enabled ? "on" : "off"} · ${workflow.trigger_summary || "Manual"}`,
    ...(workflow.description ? [workflow.description] : []),
    ...(workflow.next_run_at ? [`Next run: ${new Date(workflow.next_run_at * 1000).toISOString()}`] : []),
    `ID: ${workflow.id}`,
    ...(options.run?[`Run ${options.run.id} · ${options.run.status}`]:[]),
  ];
  return panel("Workflow", rows, Math.max(1, options.width), "center");
}

const NODE_FIELDS: Partial<Record<WorkflowNode["type"], string[]>> = {
  schedule_trigger: ["schedule.type", "schedule.time", "schedule.timezone"],
  app_skill_action: ["app_id", "skill_id", "input"],
  check: ["predicate"],
  send_chat_message: ["title", "message", "chat_id"],
  start_new_chat: ["title", "message"],
  wait: ["seconds", "minutes", "until"],
  repeat: ["count"],
  create_chat_report: ["title", "prompt"],
  send_notification: ["title", "body", "link"],
  send_email_notification: ["subject", "body", "to"],
  ask_user: ["question"],
  custom_code: ["code"],
};

function compact(value: unknown, max = 80): string {
  const text = typeof value === "string" ? value
    : Array.isArray(value) ? value.map((item) => compact(item, max)).join(", ")
    : value && typeof value === "object" ? Object.entries(value).map(([key, item]) => `${key.replaceAll("_", " ")}: ${compact(item, max)}`).join(" · ")
    : String(value);
  const oneLine = text.replace(/\s+/g, " ");
  return truncateCells(oneLine, max);
}

function label(node: WorkflowNode): string {
  return node.title?.trim() || node.type.replaceAll("_", " ");
}

function centered(value: string, width: number): string {
  const extra = Math.max(0, width - cells(value));
  return `${" ".repeat(Math.floor(extra / 2))}${value}`;
}

function panel(title: string, rows: string[], width: number, align: "left" | "center" = "left"): string[] {
  if (width < 8) return [title, ...rows].flatMap((row) => wrapCells(row, Math.max(1, width)));
  const inner = width - 4;
  const heading = truncateCells(title, width - 4);
  const top = `╭─ ${heading}${"─".repeat(Math.max(0, width - 4 - cells(heading)))}╮`;
  return [top, ...rows.flatMap((row) => wrapCells(row, inner).map((part) => `│ ${padCells(align === "center" ? centered(part, inner) : part, inner)} │`)), `╰${"─".repeat(width - 2)}╯`];
}

function tabBox(title: string, shortcut: string, selected: boolean, width: number): string[] {
  const inner = Math.max(1, width - 4);
  const label = truncateCells(`${title} · ${shortcut}`, inner);
  const horizontal = selected ? "═" : "─";
  const left = selected ? "║" : "│";
  const right = left;
  const topLeft = selected ? "╔" : "╭";
  const topRight = selected ? "╗" : "╮";
  const bottomLeft = selected ? "╚" : "╰";
  const bottomRight = selected ? "╝" : "╯";
  return [
    `${topLeft}${horizontal.repeat(Math.max(0, width - 2))}${topRight}`,
    `${left} ${padCells(label, inner)} ${right}`,
    `${bottomLeft}${horizontal.repeat(Math.max(0, width - 2))}${bottomRight}`,
  ];
}

function workflowTabs(width: number, tab: "graph" | "runs"): string[] {
  if (width < 36) {
    const tabWidth = Math.max(4, Math.min(18, width));
    return [...tabBox("Template", "g", tab === "graph", tabWidth), ...tabBox("Runs", "r", tab === "runs", tabWidth)];
  }
  const tabWidth = 18;
  const left = tabBox("Template", "g", tab === "graph", tabWidth);
  const right = tabBox("Runs", "r", tab === "runs", tabWidth);
  const inset = " ".repeat(Math.floor((width - tabWidth * 2 - 2) / 2));
  return left.map((line, index) => `${inset}${line}  ${right[index]}`);
}

function orderedNodes(graph: WorkflowGraph): WorkflowNode[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const incoming = new Map(graph.nodes.map((node) => [node.id, 0]));
  for (const edge of graph.edges ?? []) if (incoming.has(edge.to) && byId.has(edge.from)) incoming.set(edge.to, incoming.get(edge.to)! + 1);
  const ready = graph.nodes.filter((node) => !incoming.get(node.id));
  ready.sort((a, b) => Number(b.id === graph.trigger_node_id) - Number(a.id === graph.trigger_node_id));
  const result: WorkflowNode[] = [];
  while (ready.length) {
    const node = ready.shift()!;
    result.push(node);
    for (const edge of graph.edges ?? []) {
      if (edge.from !== node.id || !incoming.has(edge.to)) continue;
      const next = incoming.get(edge.to)! - 1;
      incoming.set(edge.to, next);
      if (next === 0) ready.push(byId.get(edge.to)!);
    }
  }
  return [...result, ...graph.nodes.filter((node) => !result.includes(node))];
}

function nodeSummary(node: WorkflowNode): string | null {
  const config = node.config ?? {};
  if (node.type === "app_skill_action") return [config.app_id ?? config.app, config.skill_id ?? config.skill].filter(Boolean).join("  |  ") || null;
  if (node.type === "schedule_trigger") {
    const schedule = config.schedule as Record<string, unknown> | undefined;
    return schedule ? [schedule.type, schedule.time, schedule.timezone].filter(Boolean).map(String).join(" · ") : null;
  }
  if (node.type === "check" || node.type === "decision") return config.question ? compact(config.question, 70) : config.predicate ? compact(config.predicate, 70) : null;
  if (node.type === "send_chat_message" || node.type === "send_notification") return compact(config.message ?? config.body ?? config.title ?? "", 70) || null;
  return null;
}

function readableRows(value: unknown, indent = "", depth = 0): string[] {
  if (value === null || value === undefined) return [`${indent}Unavailable`];
  if (Array.isArray(value)) return value.length ? value.flatMap((item, index) => [`${indent}${index + 1}.`, ...readableRows(item, `${indent}  `, depth + 1)]) : [`${indent}No items`];
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return [`${indent}No values`];
    return entries.flatMap(([key, item]) => {
      const name = key.replaceAll("_", " ");
      return item && typeof item === "object" && depth < 3
        ? [`${indent}${name}:`, ...readableRows(item, `${indent}  `, depth + 1)]
        : [`${indent}${name}: ${compact(item, 100)}`];
    });
  }
  return [`${indent}${String(value)}`];
}

function expandedStepRows(node: WorkflowNode, nodeRun: WorkflowNodeRun | undefined, readOnly: boolean, edit?: WorkflowWorkspaceOptions["edit"]): string[] {
  const rows = ["", "Step details", ...(edit?.nodeId===node.id?[`Editing ${edit.field}: ${edit.value}_`,"Enter saves · Esc cancels"]:[]), `id: ${node.id}`, `type: ${node.type.replaceAll("_", " ")}`];
  if (nodeRun) rows.push(`State: ${nodeRun.status}`);
  if (node.config && Object.keys(node.config).length) rows.push("", "Configuration", ...readableRows(node.config));
  if (node.input_mapping && Object.keys(node.input_mapping).length) rows.push("", "Input mapping", ...readableRows(node.input_mapping));
  if (nodeRun?.input_summary) rows.push("", "Run input", ...readableRows(nodeRun.input_summary));
  if (nodeRun?.output_summary) rows.push("", "Run output", ...readableRows(nodeRun.output_summary));
  if (nodeRun?.error_summary) rows.push("", `Error: ${nodeRun.error_summary}`);
  if (nodeRun?.skipped_reason) rows.push("", `Skipped: ${nodeRun.skipped_reason}`);
  rows.push("", readOnly ? "Recorded step · read-only" : "e Edit title · E Edit config", "Enter closes details");
  return rows;
}

function graphCanvas(graph: WorkflowGraph, options: WorkflowWorkspaceOptions, run: WorkflowRunDetail | null, width: number): string[] {
  if (!graph.nodes.length) return panel("Graph canvas", ["No graph nodes available."], width);
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const nodeRuns = new Map((run?.node_runs ?? []).map((nodeRun) => [nodeRun.node_id, nodeRun]));
  const selected = graph.nodes[Math.max(0, Math.min(graph.nodes.length - 1, options.selectedNodeIndex ?? 0))]?.id;
  const innerWidth = Math.max(8, width - 4);
  const rows: string[] = [];
  for (const node of orderedNodes(graph)) {
    const nodeRun = nodeRuns.get(node.id);
    const typeLabel = node.type === "app_skill_action" ? "app skill" : node.type.replaceAll("_", " ");
    const badge = graph.trigger_node_id === node.id ? " · trigger" : "";
    const summary = nodeSummary(node);
    const expanded = options.expandedNodeId === node.id;
    const cardWidth = expanded ? Math.min(68, innerWidth) : Math.min(38, innerWidth);
    const cardInset = Math.max(0, Math.floor((innerWidth - cardWidth) / 2));
    const cardRows = [
      `${node.id === selected ? ">" : " "} [${typeLabel}]`,
      label(node),
      ...((badge || nodeRun) ? [`${badge.replace(/^ · /, "")}${nodeRun ? `${badge ? " · " : ""}${nodeRun.status}` : ""}`] : []),
      ...(summary ? [summary] : []),
      ...(!expanded && nodeRun?.output_summary && Object.keys(nodeRun.output_summary).length ? ["Output", ...readableRows(nodeRun.output_summary)] : []),
      ...(!expanded && nodeRun?.error_summary ? [`Error: ${nodeRun.error_summary}`] : []),
      ...(expanded ? expandedStepRows(node, nodeRun, options.tab === "runs", options.edit) : []),
    ];
    rows.push(...panel(expanded ? "Step details" : "Step", cardRows, cardWidth, expanded ? "left" : "center").map((line) => `${" ".repeat(cardInset)}${line}`));
    const outgoing = (graph.edges ?? []).filter((edge) => edge.from === node.id);
    const connector = " ".repeat(cardInset + 2);
    for (const edge of outgoing) rows.push(`${connector}│ ${edge.branch ? `→ [${edge.branch}] ` : "then → "}${byId.get(edge.to) ? label(byId.get(edge.to)!) : edge.to}`);
    if (node.type === "check") {
      const branches = node.config?.mode === "ai" ? [["true", "If true"], ["false", "Else"], ["unsure", "If unsure"]] : [["yes", "If true"], ["no", "Else"]];
      for (const [branch, title] of branches) {
        const aliases = branch === "yes" ? ["yes", "true"] : branch === "no" ? ["no", "false"] : [branch];
        if (!outgoing.some((edge) => aliases.includes(edge.branch ?? ""))) rows.push(`${connector}┆ ${title}: no step`);
      }
    }
    if (outgoing.length) rows.push(`${connector}│`);
  }
  return panel(run ? "Run graph" : "Template graph", rows, width);
}

export function renderWorkflowWorkspace(workflow: WorkflowDetail, options: WorkflowWorkspaceOptions): string[] {
  const runs = options.runs ?? [];
  const run = options.run ?? runs[options.selectedRunIndex ?? 0] ?? null;
  const width = Math.max(1, options.width);
  const lines = [
    ...renderWorkflowIdentity(workflow, { width,run:options.tab==="runs"?run??undefined:undefined }),
    ...workflowTabs(width, options.tab),
    "",
  ];
  const graph = options.tab === "graph" ? workflow.graph : options.runGraph ?? null;
  if (options.tab === "runs") {
    lines.push("Run history");
    if (!runs.length) lines.push("No runs yet.");
    for (const [index, item] of runs.entries()) {
      const marker = index === (options.selectedRunIndex ?? 0) ? ">" : " ";
      lines.push(`${marker} ${item.id} · ${item.status}${item.started_at ? ` · ${new Date(item.started_at * 1000).toISOString()}` : ""}`);
    }
    if (run) {
      lines.push("", `Run ${run.id} · ${run.status} · version ${run.version_id}`);
      if (run.error_summary) lines.push(`Error: ${run.error_summary}`);
      if (run.output_summary) lines.push("Output", ...readableRows(run.output_summary));
      if (run.cost_summary) lines.push("Cost", ...readableRows(run.cost_summary));
    }
  }
  if (!graph) lines.push("Run graph unavailable. Load its recorded version to inspect nodes.");
  else {
    const canvasWidth = Math.min(width, 76);
    const inset = " ".repeat(Math.max(0, Math.floor((width - canvasWidth) / 2)));
    lines.push(...graphCanvas(graph, options, options.tab === "runs" ? run : null, canvasWidth).map((line) => `${inset}${line}`));
  }
  return lines.flatMap((line) => wrapCells(line, width));
}

/** Historical runs must always use their recorded immutable version. */
export async function loadWorkflowRunGraph(
  client: Pick<OpenMatesClient, "getWorkflowVersion">,
  workflow: WorkflowDetail,
  run: WorkflowRunDetail,
): Promise<WorkflowGraph> {
  if (run.workflow_id !== workflow.id) throw new Error("Run does not belong to this workflow.");
  if (!run.version_id) throw new Error("Run has no recorded workflow version.");
  if (run.version_id === workflow.current_version_id) return workflow.graph;
  const version = await client.getWorkflowVersion(workflow.id, run.version_id);
  if (!version?.graph) throw new Error(`Workflow version ${run.version_id} has no graph.`);
  return version.graph;
}

function valueAt(source: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((value, segment) => value && typeof value === "object" ? (value as Record<string, unknown>)[segment] : undefined, source);
}

function fieldValue(value: unknown): string {
  return value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value);
}

export function buildWorkflowNodeForm(workflow: WorkflowDetail, node: WorkflowNode, kind = "workflow-node"): TuiForm {
  if (!workflow.graph.nodes.some((candidate) => candidate.id === node.id)) throw new Error(`Unknown workflow node ${node.id}.`);
  const config = node.config ?? {};
  const schemaKeys = NODE_FIELDS[node.type] ?? [];
  const currentKeys = Object.keys(config).flatMap((key) => {
    const value = config[key];
    if (key === "schedule" && value && typeof value === "object" && !Array.isArray(value)) {
      return Object.keys(value).map((part) => `schedule.${part}`);
    }
    return [key];
  });
  const keys = [...new Set([...schemaKeys, ...currentKeys])];
  return {
    kind,
    title: `Edit ${label(node)}`,
    contextId: node.id,
    fieldIndex: 0,
    fields: [
      { name: "title", label: "Node title", value: node.title ?? "" },
      ...keys.map((key) => {
        const value = valueAt(config, key);
        return { name: `config.${key}`, label: key.replaceAll("_", " "), value: fieldValue(value), multiline: typeof value === "object" || /(?:message|body|prompt|code)$/i.test(key) };
      }),
    ],
  };
}

function parsedField(raw: string, oldValue: unknown): unknown {
  if (typeof oldValue === "boolean") {
    if (raw !== "true" && raw !== "false") throw new Error("Use true or false for boolean fields.");
    return raw === "true";
  }
  if (typeof oldValue === "number") {
    const value = Number(raw);
    if (!raw.trim() || !Number.isFinite(value)) throw new Error("Enter a valid number.");
    return value;
  }
  if (oldValue !== null && typeof oldValue === "object") return JSON.parse(raw);
  return raw;
}

function setPath(config: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split(".");
  let target = config;
  for (const part of parts.slice(0, -1)) {
    const existing = target[part];
    target[part] = existing && typeof existing === "object" && !Array.isArray(existing) ? { ...existing } : {};
    target = target[part] as Record<string, unknown>;
  }
  target[parts.at(-1)!] = value;
}

export async function submitWorkflowNodeForm(
  client: Pick<OpenMatesClient, "updateWorkflow">,
  workflow: WorkflowDetail,
  form: TuiForm,
): Promise<WorkflowDetail> {
  const nodeId = form.contextId;
  const node = workflow.graph.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) throw new Error(`Unknown workflow node ${nodeId ?? ""}.`);
  const config = { ...node.config };
  for (const field of form.fields) {
    if (!field.name.startsWith("config.")) continue;
    const path = field.name.slice("config.".length);
    const oldValue = valueAt(node.config ?? {}, path);
    if (oldValue === undefined && !field.value.trim()) continue;
    try { setPath(config, path, parsedField(field.value, oldValue)); }
    catch (error) { throw new Error(`${field.label}: ${error instanceof Error ? error.message : "Invalid value"}`); }
  }
  const graph: WorkflowGraph = {
    ...workflow.graph,
    nodes: workflow.graph.nodes.map((candidate) => candidate.id === node.id
      ? { ...candidate, title: formValue(form, "title"), config }
      : candidate),
  };
  return client.updateWorkflow(workflow.id, { graph });
}
