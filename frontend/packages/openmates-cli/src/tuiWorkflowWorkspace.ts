/** Compact, edge-aware Workflow workspace for the terminal. */
import type { OpenMatesClient, WorkflowCapability, WorkflowDetail, WorkflowGraph, WorkflowNode, WorkflowNodeRun, WorkflowRunDetail, WorkflowSummary } from "./client.js";
import type { TuiForm, TuiFormField } from "./tuiForms.js";
import { formValue } from "./tuiForms.js";
import { cells, padCells, terminalText, truncateCells, wrapCells, type TuiLine } from "./tuiText.js";
import { centeredCarouselText, renderCardCarousel } from "./tuiCarousel.js";
import { APP_GRADIENTS, PRIMARY_GRADIENT } from "../../appGradientTheme.js";
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";

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
export function workflowIdentityColor(workflow: WorkflowSummary): string {
  return CATEGORY_GRADIENTS[workflow.category ?? ""]?.start ?? CATEGORY_GRADIENTS.general_knowledge.start;
}

export function renderWorkflowIdentity(workflow: WorkflowSummary, options: { width: number;run?:WorkflowRunDetail }): TuiLine[] {
  const width = Math.max(1, options.width);
  const rows = [
    "Workflow", "", workflow.title,
    `Workflow ${workflow.enabled ? "on" : "off"}`,
    workflow.description || workflow.trigger_summary || "Manual trigger",
    "",
    workflow.enabled && workflow.next_run_at ? `Next run: ${new Date(workflow.next_run_at * 1000).toISOString()}`
      : `Created ${new Date(workflow.created_at * 1000).toISOString().slice(0, 10)}`,
    ...(options.run ? [`Run ${options.run.id} · ${options.run.status}`] : []),
  ];
  return rows.map((row, index) => {
    const value = truncateCells(terminalText(row), width);
    return { text: padCells(centered(value, width), width), background: workflowIdentityColor(workflow), color: "#ffffff", bold: index === 0 || index === 2 };
  });
}

const NODE_FIELDS: Partial<Record<WorkflowNode["type"], string[]>> = {
  wait: ["seconds", "minutes", "until"], repeat: ["count"],
  create_chat_report: ["title", "prompt"], send_notification: ["title", "body", "link"],
  send_email_notification: ["subject", "body", "to"], ask_user: ["question"], custom_code: ["code"],
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

export function orderedWorkflowNodes(graph: WorkflowGraph): WorkflowNode[] {
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
  if (node.type === "app_skill_action") {
    if (config.app_id === "ai" && config.skill_id === "ask") return compact((config.input as Record<string, unknown> | undefined)?.prompt ?? "Ask AI", 70);
    return [config.app_id ?? config.app, config.skill_id ?? config.skill].filter(Boolean).join("  |  ") || null;
  }
  if (node.type === "schedule_trigger") {
    const schedule = config.schedule as Record<string, unknown> | undefined;
    if (!schedule) return null;
    return [schedule.type, schedule.type === "once" ? schedule.at : schedule.type === "hourly" ? `:${String(schedule.minute ?? 0).padStart(2, "0")}` : schedule.time,
      ...(schedule.type === "weekly" && Array.isArray(schedule.weekdays) ? [schedule.weekdays.join(", ")] : []), schedule.timezone].filter(Boolean).map(String).join(" · ");
  }
  if (node.type === "check" || node.type === "decision") {
    if (config.mode === "ai") return compact(config.question ?? "AI judgment", 70);
    const predicate = config.predicate as Record<string, unknown> | undefined;
    return predicate ? compact(`${predicate.left ?? "?"} ${predicate.op ?? "?"} ${predicate.right ?? "?"}`, 70) : null;
  }
  if (node.type === "send_chat_message" || node.type === "start_new_chat") return config.chat_id ? `To chat ${compact(config.chat_id, 30)}` : "To new chat";
  if (node.type === "send_notification") return compact(config.body ?? config.title ?? "", 70) || null;
  return null;
}

function nodeKind(node: WorkflowNode): string {
  if (node.type === "schedule_trigger") return "Time trigger";
  if (node.type === "check" || node.type === "decision") return "Check";
  if (node.type === "app_skill_action" && node.config?.app_id === "ai" && node.config?.skill_id === "ask") return "Ask AI";
  if (node.type === "app_skill_action") return "Use app skill";
  if (node.type === "send_chat_message" || node.type === "start_new_chat") return "Send message";
  return node.type.replaceAll("_", " ");
}

export function workflowNodeColor(node: WorkflowNode): string | undefined {
  if (node.type === "schedule_trigger" || node.type === "check" || node.type === "decision" || node.type === "send_chat_message" || node.type === "start_new_chat") return PRIMARY_GRADIENT.start;
  if (node.type === "app_skill_action") return APP_GRADIENTS[String(node.config?.app_id ?? "")]?.start ?? PRIMARY_GRADIENT.start;
  return undefined;
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

function graphCanvas(graph: WorkflowGraph, options: WorkflowWorkspaceOptions, run: WorkflowRunDetail | null, width: number): TuiLine[] {
  if (!graph.nodes.length) return panel("Graph canvas", ["No graph nodes available."], width);
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const nodeRuns = new Map((run?.node_runs ?? []).map((nodeRun) => [nodeRun.node_id, nodeRun]));
  const nodes = orderedWorkflowNodes(graph);
  const selected = nodes[Math.max(0, Math.min(nodes.length - 1, options.selectedNodeIndex ?? 0))]?.id;
  const innerWidth = Math.max(8, width - 4);
  const rows: TuiLine[] = [];
  for (const node of nodes) {
    const nodeRun = nodeRuns.get(node.id);
    const typeLabel = nodeKind(node);
    const badge = graph.trigger_node_id === node.id ? " · trigger" : "";
    const summary = nodeSummary(node);
    const expanded = options.expandedNodeId === node.id;
    const cardWidth = expanded ? Math.min(68, innerWidth) : Math.min(38, innerWidth);
    const cardInset = Math.max(0, Math.floor((innerWidth - cardWidth) / 2));
    const cardRows = [
      `${node.id === selected ? ">" : " "} ${typeLabel}`,
      nodeSummary(node) ?? label(node),
      ...(nodeSummary(node) && nodeSummary(node) !== label(node) ? [label(node)] : []),
      ...((badge || nodeRun) ? [`${badge.replace(/^ · /, "")}${nodeRun ? `${badge ? " · " : ""}${nodeRun.status}` : ""}`] : []),
      ...(summary ? [summary] : []),
      ...(!expanded && nodeRun?.output_summary && Object.keys(nodeRun.output_summary).length ? ["Output", ...readableRows(nodeRun.output_summary)] : []),
      ...(!expanded && nodeRun?.error_summary ? [`Error: ${nodeRun.error_summary}`] : []),
      ...(expanded ? expandedStepRows(node, nodeRun, options.tab === "runs", options.edit) : []),
    ];
    const color = workflowNodeColor(node);
    rows.push(...panel(expanded ? "Step details" : "Step", cardRows, cardWidth, expanded ? "left" : "center").map((line): TuiLine => {
      const inset = " ".repeat(cardInset);
      const text = `${inset}${line}`;
      return color ? { text, spans: [{ text: inset }, { text: line, background: color, bold: line.includes(typeLabel) }] } : text;
    }));
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
  return [run ? "Run graph" : "Template graph", ...rows];
}

export function renderWorkflowWorkspace(workflow: WorkflowDetail, options: WorkflowWorkspaceOptions): TuiLine[] {
  const runs = options.runs ?? [];
  const run = options.run ?? runs[options.selectedRunIndex ?? 0] ?? null;
  const width = Math.max(1, options.width);
  const lines: TuiLine[] = [
    ...renderWorkflowIdentity(workflow, { width,run:options.tab==="runs"?run??undefined:undefined }),
    ...workflowTabs(width, options.tab),
    "",
  ];
  const upcoming = workflow.enabled && workflow.next_run_at && workflow.next_run_at > Date.now() / 1000 ? workflow.next_run_at : null;
  const graph = options.tab === "graph" ? workflow.graph : run ? options.runGraph ?? null : upcoming ? workflow.graph : null;
  if (options.tab === "runs") {
    lines.push("Run timeline  ·  ↑/↓ select retained run");
    if (upcoming) lines.push(`${run ? " " : ">"} Next · ${new Date(upcoming * 1000).toISOString()} · upcoming`);
    if (!runs.length && !upcoming) lines.push("No runs yet.");
    for (const [index, item] of runs.entries()) {
      const marker = index === (options.selectedRunIndex ?? 0) ? ">" : " ";
      lines.push(`${marker} ${item.id} · ${item.status}${item.started_at ? ` · ${new Date(item.started_at * 1000).toISOString()}` : ""}`);
    }
    if (run) {
      lines.push("", `Selected run ${run.id} · ${run.status} · version ${run.version_id}`);
      if (run.error_summary) lines.push(`Error: ${run.error_summary}`);
      if (run.output_summary) lines.push("Output", ...readableRows(run.output_summary));
      if (run.cost_summary) lines.push("Cost", ...readableRows(run.cost_summary));
    } else if (upcoming) lines.push("", `Upcoming run · ${new Date(upcoming * 1000).toISOString()}`);
  }
  if (!graph) lines.push("Run graph unavailable. Load its recorded version to inspect nodes.");
  else {
    const canvasWidth = Math.min(width, 76);
    const inset = " ".repeat(Math.max(0, Math.floor((width - canvasWidth) / 2)));
    lines.push(...graphCanvas(graph, options, options.tab === "runs" ? run : null, canvasWidth).map((line): TuiLine => typeof line === "string" ? `${inset}${line}` : {
      ...line, text: `${inset}${line.text}`, spans: line.spans ? [{ text: inset }, ...line.spans] : undefined,
    }));
  }
  return lines.flatMap((line): TuiLine[] => {
    if (typeof line === "string") return wrapCells(line, width);
    const text = padCells(line.text, width);
    if (line.spans) return [{ ...line, text, spans: [...line.spans, { text: " ".repeat(width - cells(line.text)) }] }];
    return wrapCells(line.text, width).map((part) => ({ ...line, text: padCells(part, width) }));
  });
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

type InputSchema = {
  type?: string; title?: string; properties?: Record<string, InputSchema>; items?: InputSchema;
  required?: string[]; enum?: unknown[]; default?: unknown; minimum?: number; maximum?: number;
  format?: string; minItems?: number; "x-ui"?: { hidden?: boolean };
};

function inputSchema(capabilities: WorkflowCapability[] | undefined, node: WorkflowNode): InputSchema | undefined {
  const capability = capabilities?.find((item) => item.type === "app_skill" && item.metadata?.app_id === node.config?.app_id && item.metadata?.skill_id === node.config?.skill_id);
  const schema = capability?.metadata?.input_schema;
  return schema && typeof schema === "object" && !Array.isArray(schema) ? schema as InputSchema : undefined;
}

function schemaFields(schema: InputSchema, value: unknown, path = "config.input", labelPrefix = "", required = false): TuiFormField[] {
  if (schema["x-ui"]?.hidden) return [];
  const title = labelPrefix || schema.title || path.split(".").at(-1)!.replaceAll("_", " ");
  if (schema.type === "object" || schema.properties) {
    const record = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
    return Object.entries(schema.properties ?? {}).flatMap(([key, child]) => schemaFields(child, record[key], `${path}.${key}`, labelPrefix ? `${labelPrefix} / ${child.title ?? key.replaceAll("_", " ")}` : child.title ?? key.replaceAll("_", " "), schema.required?.includes(key) ?? false));
  }
  if (schema.type === "array" && schema.items && (schema.items.type === "object" || schema.items.properties)) {
    const items = Array.isArray(value) ? value : [];
    const count = Math.max(items.length, schema.minItems ?? 0, 1);
    return Array.from({ length: count }, (_, index) => schemaFields(schema.items!, items[index], `${path}.${index}`, `${title} ${index + 1}`, required)).flat();
  }
  if (schema.type === "array" && schema.items) {
    const items = Array.isArray(value) ? value : [];
    const count = Math.max(items.length, schema.minItems ?? 0, 1);
    return Array.from({ length: count }, (_, index) => schemaFields(schema.items!, items[index], `${path}.${index}`, `${title} ${index + 1}`, required && index < (schema.minItems ?? 1))).flat();
  }
  const declaredType = (["string", "number", "integer", "boolean", "object", "array"] as const).find((candidate) => candidate === schema.type) ?? "string";
  const resolved = value === undefined ? schema.default : value;
  const type = resolved && typeof resolved === "object" && declaredType === "string" ? Array.isArray(resolved) ? "array" : "object" : declaredType;
  return [{ name: path, label: `${title}${required ? " *" : ""}`, value: fieldValue(resolved),
    valueType: type, required, options: schema.enum?.map(String) ?? (type === "boolean" ? ["true", "false"] : undefined),
    multiline: type === "object" || type === "array" || /(?:message|body|prompt|code|query)$/i.test(path),
    minimum: schema.minimum, maximum: schema.maximum, format: schema.format }];
}

function configField(path: string, value: unknown, options: Partial<TuiFormField> = {}): TuiFormField {
  return { name: `config.${path}`, label: path.replaceAll("_", " ").replaceAll(".", " / "), value: fieldValue(value),
    valueType: typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : Array.isArray(value) ? "array" : value && typeof value === "object" ? "object" : "string",
    multiline: typeof value === "object" || /(?:message|body|prompt|code)$/i.test(path), ...options };
}

/** Mirrors the web builder's field groups. Unknown config stays editable and survives saves. */
export function buildWorkflowNodeForm(workflow: WorkflowDetail, node: WorkflowNode, capabilities?: WorkflowCapability[], kind = "workflow-node"): TuiForm {
  if (!workflow.graph.nodes.some((candidate) => candidate.id === node.id)) throw new Error(`Unknown workflow node ${node.id}.`);
  const config = node.config ?? {};
  const handled = new Set<string>();
  const fields: TuiFormField[] = [];
  const add = (path: string, options: Partial<TuiFormField> = {}) => {
    handled.add(path.split(".")[0]!);
    const value = valueAt(config, path);
    const { value: fallback, ...metadata } = options;
    fields.push(configField(path, value ?? fallback, metadata));
  };
  if (node.type === "schedule_trigger") {
    const schedule = config.schedule && typeof config.schedule === "object" ? config.schedule as Record<string, unknown> : {};
    const type = String(schedule.type ?? "daily");
    add("schedule.type", { options: ["once", "hourly", "daily", "weekly"], value: type, required: true });
    add("schedule.at", { required: type === "once", format: "date-time" });
    add("schedule.minute", { value: "0", valueType: "integer", minimum: 0, maximum: 59, required: type === "hourly" });
    add("schedule.time", { value: "09:00", format: "time", required: type === "daily" || type === "weekly" });
    add("schedule.weekdays", { value: "[\"sunday\"]", valueType: "array", required: type === "weekly" });
    add("schedule.timezone", { value: "UTC", required: true });
    handled.add("schedule");
  } else if (node.type === "app_skill_action" && config.app_id === "ai" && config.skill_id === "ask") {
    add("input.prompt", { required: true, multiline: true });
    if (valueAt(config, "input.model") !== undefined) add("input.model");
    handled.add("input");
  } else if (node.type === "app_skill_action") {
    add("app_id", { required: true }); add("skill_id", { required: true });
    const schema = inputSchema(capabilities, node);
    if (schema) {
      fields.push(...schemaFields(schema, config.input));
      // Raw JSON remains an advanced escape hatch. Unchanged JSON never overrides typed fields.
      fields.push(configField("input", config.input ?? {}, { label: "Advanced input JSON", multiline: true, valueType: "object" }));
    } else fields.push(configField("input", config.input ?? {}, { label: "Input JSON (schema unavailable)", multiline: true, valueType: "object" }));
    handled.add("input");
  } else if (node.type === "check" || node.type === "decision") {
    const mode = config.mode === "ai" ? "ai" : "exact";
    add("mode", { value: mode, options: ["exact", "ai"], required: true });
    add("question", { required: mode === "ai", multiline: true });
    add("predicate.left", { required: mode === "exact" });
    add("predicate.op", { options: ["eq", "neq", "gt", "gte", "lt", "lte", "contains"], required: mode === "exact" });
    add("predicate.right", { required: mode === "exact", valueType: typeof valueAt(config, "predicate.right") === "number" ? "number" : typeof valueAt(config, "predicate.right") === "boolean" ? "boolean" : "string" });
    handled.add("predicate");
  } else if (node.type === "send_chat_message" || node.type === "start_new_chat") {
    add("title", { required: true }); add("message", { required: true, multiline: true });
    if (node.type === "send_chat_message") add("chat_id", { label: "Destination chat ID (blank creates a new chat)" });
  } else for (const key of NODE_FIELDS[node.type] ?? []) add(key);
  for (const [key, value] of Object.entries(config)) if (!handled.has(key)) fields.push(configField(key, value));
  return {
    kind,
    title: `Edit ${label(node)}`,
    contextId: node.id,
    fieldIndex: 0,
    fields: [{ name: "title", label: "Node title", value: node.title ?? "" }, ...fields],
  };
}

function parsedField(raw: string, oldValue: unknown, field: TuiFormField): unknown {
  if (field.required && !raw.trim()) throw new Error("This field is required.");
  if (field.options?.length && raw && !field.options.includes(raw)) throw new Error(`Choose ${field.options.join(", ")}.`);
  if (field.valueType === "boolean" || typeof oldValue === "boolean") {
    if (raw !== "true" && raw !== "false") throw new Error("Use true or false for boolean fields.");
    return raw === "true";
  }
  if (field.valueType === "number" || field.valueType === "integer" || typeof oldValue === "number") {
    const value = Number(raw);
    if (!raw.trim() || !Number.isFinite(value)) throw new Error("Enter a valid number.");
    if (field.valueType === "integer" && !Number.isInteger(value)) throw new Error("Enter a whole number.");
    if (field.minimum !== undefined && value < field.minimum) throw new Error(`Enter at least ${field.minimum}.`);
    if (field.maximum !== undefined && value > field.maximum) throw new Error(`Enter at most ${field.maximum}.`);
    return value;
  }
  if (field.valueType === "object" || field.valueType === "array" || oldValue !== null && typeof oldValue === "object") {
    const value: unknown = JSON.parse(raw);
    if (field.valueType === "array" && !Array.isArray(value)) throw new Error("Enter a JSON array.");
    if (field.valueType === "object" && (!value || typeof value !== "object" || Array.isArray(value))) throw new Error("Enter a JSON object.");
    return value;
  }
  if (field.format === "time" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(raw)) throw new Error("Use HH:MM time.");
  if (field.format === "date-time" && Number.isNaN(Date.parse(raw))) throw new Error("Enter a valid date and time.");
  return raw;
}

function setPath(config: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split(".");
  let target: Record<string, unknown> | unknown[] = config;
  for (const [index, part] of parts.slice(0, -1).entries()) {
    const key = Array.isArray(target) ? Number(part) : part;
    const existing = (target as Record<string | number, unknown>)[key];
    const next = existing && typeof existing === "object" ? existing : /^\d+$/.test(parts[index + 1]!) ? [] : {};
    (target as Record<string | number, unknown>)[key] = next;
    target = next as Record<string, unknown> | unknown[];
  }
  const key = Array.isArray(target) ? Number(parts.at(-1)!) : parts.at(-1)!;
  (target as Record<string | number, unknown>)[key] = value;
}

export async function submitWorkflowNodeForm(
  client: Pick<OpenMatesClient, "updateWorkflow">,
  workflow: WorkflowDetail,
  form: TuiForm,
): Promise<WorkflowDetail> {
  const nodeId = form.contextId;
  const node = workflow.graph.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) throw new Error(`Unknown workflow node ${nodeId ?? ""}.`);
  const config = structuredClone(node.config ?? {});
  const scheduleType = node.type === "schedule_trigger" ? formValue(form, "config.schedule.type") : null;
  const checkMode = node.type === "check" || node.type === "decision" ? formValue(form, "config.mode") : null;
  if (scheduleType && scheduleType !== valueAt(node.config ?? {}, "schedule.type")) {
    const schedule = config.schedule && typeof config.schedule === "object" ? config.schedule as Record<string, unknown> : {};
    for (const key of ["at", "minute", "time", "weekdays"]) {
      if (key === "at" && scheduleType === "once" || key === "minute" && scheduleType === "hourly" || key === "time" && ["daily", "weekly"].includes(scheduleType) || key === "weekdays" && scheduleType === "weekly") continue;
      delete schedule[key];
    }
    config.schedule = schedule;
  }
  const advanced = form.fields.find((field) => field.name === "config.input" && field.label === "Advanced input JSON");
  if (advanced && advanced.value !== fieldValue(node.config?.input ?? {})) {
    try { setPath(config, "input", parsedField(advanced.value, node.config?.input, advanced)); }
    catch (error) { throw new Error(`${advanced.label}: ${error instanceof Error ? error.message : "Invalid value"}`); }
  }
  for (const field of form.fields) {
    if (!field.name.startsWith("config.")) continue;
    if (field === advanced) continue;
    const path = field.name.slice("config.".length);
    if (path.startsWith("schedule.") && !["schedule.type", "schedule.timezone",
      ...(scheduleType === "once" ? ["schedule.at"] : scheduleType === "hourly" ? ["schedule.minute"] : scheduleType === "weekly" ? ["schedule.time", "schedule.weekdays"] : ["schedule.time"])].includes(path)) continue;
    if (checkMode === "ai" && path.startsWith("predicate.") || checkMode === "exact" && path === "question") continue;
    const oldValue = valueAt(node.config ?? {}, path);
    const required = path.startsWith("schedule.") ? path !== "schedule.type" && path !== "schedule.timezone" ? true : field.required
      : path === "question" && checkMode === "ai" || path.startsWith("predicate.") && checkMode === "exact" ? true : field.required;
    if (oldValue === undefined && !field.value.trim() && !required) continue;
    try { setPath(config, path, parsedField(field.value, oldValue, { ...field, required })); }
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
