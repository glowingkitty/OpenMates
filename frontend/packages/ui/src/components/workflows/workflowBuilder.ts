import type {
  WorkflowGraph,
  WorkflowNode,
} from "../../stores/workflowWorkspaceStore";

export type Schema = {
  "x-ui"?: { control?: string; start_field?: string; end_field?: string; min?: string; max_offset_days?: number; default?: string; hidden?: boolean; basic?: boolean };
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, Schema>;
  items?: Schema;
  required?: string[];
  enum?: unknown[];
  default?: unknown;
  example?: unknown;
  examples?: unknown[];
  minimum?: number;
  maximum?: number;
  format?: string;
  anyOf?: Schema[];
};
export type Capability = {
  id: string;
  type: string;
  enabled: boolean;
  title: string;
  reason?: string;
  metadata: {
    app_id?: string;
    skill_id?: string;
    input_schema?: Schema;
    output_schema?: Schema;
    cost?: { fixed?: number; per_unit?: { credits: number } };
    workflow?: {
      test_allowed?: boolean;
      test_example_input?: Record<string, unknown>;
    };
  };
};
export type Output = {
  reference: string;
  nodeId: string;
  label: string;
  schema: Schema;
};
export type Insertion = { after: string | null; branch?: string };

export const record = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
export const label = (value: string): string =>
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
export const isCheck = (node: WorkflowNode): boolean =>
  ["check", "decision"].includes(node.type);
export const isTrigger = (node: WorkflowNode): boolean =>
  node.type.endsWith("_trigger");
export const isMessage = (node: WorkflowNode): boolean =>
  ["send_chat_message", "create_chat_report", "start_new_chat"].includes(
    node.type,
  );
export const isAskAi = (node: WorkflowNode): boolean =>
  node.type === "app_skill_action" &&
  node.config?.app_id === "ai" &&
  node.config?.skill_id === "ask";
export const capabilityFor = (
  node: WorkflowNode,
  capabilities: Capability[],
): Capability | undefined =>
  capabilities.find(
    (capability) =>
      capability.id === `${node.config?.app_id}.${node.config?.skill_id}`,
  );

/** Local path readiness; the backend validates required inputs before any run. */
export function workflowGraphReady(
  graph: WorkflowGraph,
  { requireSchedule = false }: { requireSchedule?: boolean } = {},
): boolean {
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  if (
    requireSchedule &&
    nodesById.get(graph.trigger_node_id ?? "")?.type !== "schedule_trigger"
  )
    return false;

  const incoming = new Set(graph.edges.map((edge) => edge.to));
  const roots = graph.nodes.filter((node) => !incoming.has(node.id));
  const start =
    graph.trigger_node_id ?? (roots.length === 1 ? roots[0].id : null);
  if (!start) return false;
  const qualifyingTypes = new Set([
    "send_chat_message",
    "create_chat_report",
    "start_new_chat",
    "send_notification",
    "send_email_notification",
  ]);
  const pending = [start];
  const visited = new Set<string>();
  while (pending.length > 0) {
    const nodeId = pending.pop();
    if (!nodeId || visited.has(nodeId)) continue;
    visited.add(nodeId);
    const node = nodesById.get(nodeId);
    if (!node) continue;
    if (qualifyingTypes.has(node.type)) return true;
    for (const edge of graph.edges)
      if (edge.from === nodeId) pending.push(edge.to);
  }
  return false;
}

export function schemaDefault(schema: Schema): unknown {
  // Registry defaults are JSON data and may arrive through a Svelte state proxy.
  if (schema.default !== undefined)
    return JSON.parse(JSON.stringify(schema.default));
  if (schema.type === "object") {
    const properties = Object.entries(schema.properties ?? {});
    const defaults = Object.fromEntries(properties
      .filter(([name, item]) => schema.required?.includes(name) || item.default !== undefined)
      .map(([name, item]) => [name, schemaDefault(item)]));
    const ui = schema["x-ui"];
    if (ui?.control === "date-range" && ui.default === "today") {
      defaults[ui.start_field ?? "start_date"] = { $date: "today", format: "date" };
      defaults[ui.end_field ?? "end_date"] = { $date: "today", format: "date" };
      if (properties.some(([key, field]) => key === "days" && field["x-ui"]?.hidden)) delete defaults.days;
    }
    return defaults;
  }
  if (schema.type === "array")
    return schema.items?.type === "object" ? [schemaDefault(schema.items)] : [];
  if (schema.type === "boolean") return false;
  if (["number", "integer"].includes(schema.type ?? ""))
    return schema.minimum ?? 0;
  return "";
}

/** Bindings come from graph ancestors, never from a future or sibling branch. */
export function outputsBefore(
  graph: WorkflowGraph,
  nodeId: string,
  capabilities: Capability[],
  insertion?: Insertion | null,
): Output[] {
  const ancestors = new Set<string>();
  const visit = (id: string) => {
    for (const edge of graph.edges.filter((edge) => edge.to === id))
      if (!ancestors.has(edge.from)) {
        ancestors.add(edge.from);
        visit(edge.from);
      }
  };
  if (graph.nodes.some((node) => node.id === nodeId)) visit(nodeId);
  else if (insertion?.after) {
    ancestors.add(insertion.after);
    visit(insertion.after);
  }
  return graph.nodes
    .filter((node) => ancestors.has(node.id))
    .flatMap((node) => {
      const properties = isCheck(node)
        ? { matched: { type: "boolean", title: "Check matched" } }
        : (capabilityFor(node, capabilities)?.metadata.output_schema
            ?.properties ?? {});
      return Object.entries(properties).map(([key, schema]) => ({
        reference: `$nodes.${node.id}.output.${key}`,
        nodeId: node.id,
        label: `${node.title || label(String(node.config?.app_id ?? node.type))} · ${schema.title || label(key)}`,
        schema,
      }));
    });
}

/** Insert in one explicit branch/continuation, preserving all other edges. */
export function insertNode(
  graph: WorkflowGraph,
  node: WorkflowNode,
  insertion: Insertion,
): WorkflowGraph {
  if (graph.nodes.some((item) => item.id === node.id))
    return {
      ...graph,
      nodes: graph.nodes.map((item) => (item.id === node.id ? node : item)),
    };
  const nodes = [...graph.nodes, node];
  if (isTrigger(node)) {
    const roots = graph.nodes.filter(
      (item) =>
        !graph.edges.some((edge) => edge.to === item.id) && item.type !== "end",
    );
    return {
      ...graph,
      nodes: [node, ...graph.nodes],
      trigger_node_id: node.id,
      edges: [
        ...graph.edges,
        ...roots.map((root) => ({ from: node.id, to: root.id })),
      ],
    };
  }
  if (!insertion.after) return { ...graph, nodes };
  const selected = graph.edges.filter(
    (edge) =>
      edge.from === insertion.after &&
      (edge.branch ?? "") === (insertion.branch ?? ""),
  );
  return {
    ...graph,
    nodes,
    edges: [
      ...graph.edges.filter((edge) => !selected.includes(edge)),
      {
        from: insertion.after,
        to: node.id,
        ...(insertion.branch ? { branch: insertion.branch } : {}),
      },
      ...selected.map((edge) => ({ from: node.id, to: edge.to })),
    ],
  };
}

export class WorkflowNodeDependencyError extends Error {
  dependentNodeTitles: string[];
  constructor(dependentNodeTitles: string[]) {
    super("Workflow node is still used by later steps");
    this.dependentNodeTitles = dependentNodeTitles;
  }
}

export function removeNode(
  graph: WorkflowGraph,
  nodeId: string,
  capabilities: Capability[] = [],
): WorkflowGraph {
  const incoming = graph.edges.filter((edge) => edge.to === nodeId);
  const continuation = graph.edges.filter((edge) => edge.from === nodeId && !edge.branch);
  const removed = graph.nodes.find(node => node.id === nodeId);
  const predicate = record(removed?.config?.predicate);
  const source = outputsBefore(graph, nodeId, capabilities).find(output => output.reference === predicate.left);
  // A boolean equality Check only forwards the original flag. Its consumers
  // can bind directly to that flag without changing the workflow's behavior.
  const replacement = removed && isCheck(removed) && predicate.op === "eq" && predicate.right === true
    && source && normalizeSchema(source.schema).type === "boolean" ? source.reference : null;
  const oldReference = `$nodes.${nodeId}.output.matched`;
  const oldToken = `{{steps.${nodeId}.matched}}`;
  const newToken = replacement ? `{{steps.${source!.nodeId}.${replacement.split(".output.")[1]}}}` : "";
  const nullable = source && (Array.isArray(source.schema.type) && source.schema.type.includes("null") || source.schema.anyOf?.some(variant => variant.type === "null"));
  function rewrite(value: unknown, key = ""): unknown {
    // Nullable flags are equivalent to equality-to-true only for an optional
    // message condition. Preserve other consumers for the dependency error.
    if (typeof value === "string" && replacement) {
      if (nullable) return key === "include_if" && (value === oldReference || value === oldToken) ? replacement : value;
      return value === oldReference ? replacement : value.replaceAll(oldToken, newToken);
    }
    if (Array.isArray(value)) return value.map(child => rewrite(child));
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, rewrite(child, key)]));
    return value;
  }
  function referencesRemoved(value: unknown): boolean {
    if (typeof value === "string") return value.includes(`$nodes.${nodeId}.output.`) || value.includes(`steps.${nodeId}.`);
    if (Array.isArray(value)) return value.some(referencesRemoved);
    return !!value && typeof value === "object" && Object.values(value).some(referencesRemoved);
  }
  const nodes = graph.nodes.filter(node => node.id !== nodeId).map(node => ({ ...node, config: rewrite(node.config) as WorkflowNode["config"] }));
  const dependent = nodes.filter(node => referencesRemoved(node.config));
  if (dependent.length) throw new WorkflowNodeDependencyError(dependent.map(node => node.title || label(node.type)));
  // Keep branch nodes as explicit draft roots when deleting their Check.
  return {
    ...graph,
    trigger_node_id: graph.trigger_node_id === nodeId ? null : graph.trigger_node_id,
    nodes,
    edges: [
      ...graph.edges.filter(edge => edge.from !== nodeId && edge.to !== nodeId),
      ...incoming.flatMap(before => continuation.map(after => ({ ...before, to: after.to }))),
    ],
  };
}

export function workflowIcon(
  title: string,
  icon?: string | null,
  graph?: WorkflowGraph,
): string {
  if (icon && !["help-circle", "circle-help", "workflow"].includes(icon))
    return icon;
  const names =
    `${title} ${graph?.nodes.map((node) => node.config?.app_id ?? "").join(" ") ?? ""}`.toLowerCase();
  if (/apartment|flat|rent|home|wohnung/.test(names)) return "house";
  if (/weather|rain|forecast|wetter/.test(names)) return "cloud-rain";
  if (/event|meetup/.test(names)) return "calendar-days";
  if (/news|brief/.test(names)) return "newspaper";
  return "workflow";
}

/** JSON Schema nullable unions still have one authorable value type. */
export function normalizeSchema(schema: Schema): Schema {
  const rawType = (schema as { type?: string | string[] }).type;
  const variant = schema.anyOf?.find((item) => item.type !== "null");
  const type =
    typeof rawType === "string"
      ? rawType
      : rawType?.find((item) => item !== "null");
  const value = { ...(variant ?? {}), ...schema, type: type ?? variant?.type };
  return {
    ...value,
    ...(value.properties
      ? {
          properties: Object.fromEntries(
            Object.entries(value.properties).map(([key, child]) => [
              key,
              normalizeSchema(child),
            ]),
          ),
        }
      : {}),
    ...(value.items ? { items: normalizeSchema(value.items) } : {}),
  };
}

/** A new chat uses an omitted destination ID in both preview and saved graphs. */
export function messageDestinationConfig(
  config: Record<string, unknown>,
  chatId?: string | null,
): Record<string, unknown> {
  const next = { ...config };
  if (chatId) next.chat_id = chatId;
  else delete next.chat_id;
  return next;
}
