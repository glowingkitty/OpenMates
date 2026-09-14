import type {
  WorkflowGraph,
  WorkflowNode,
} from "../../stores/workflowWorkspaceStore";

export type Schema = {
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
  if (schema.type === "object")
    return Object.fromEntries(
      Object.entries(schema.properties ?? {})
        .filter(
          ([name, item]) =>
            schema.required?.includes(name) || item.default !== undefined,
        )
        .map(([name, item]) => [name, schemaDefault(item)]),
    );
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

export function removeNode(
  graph: WorkflowGraph,
  nodeId: string,
): WorkflowGraph {
  const incoming = graph.edges.filter((edge) => edge.to === nodeId);
  const continuation = graph.edges.filter(
    (edge) => edge.from === nodeId && !edge.branch,
  );
  // Keep branch nodes as explicit draft roots when deleting their Check.
  return {
    ...graph,
    trigger_node_id:
      graph.trigger_node_id === nodeId ? null : graph.trigger_node_id,
    nodes: graph.nodes.filter((node) => node.id !== nodeId),
    edges: [
      ...graph.edges.filter(
        (edge) => edge.from !== nodeId && edge.to !== nodeId,
      ),
      ...incoming.flatMap((before) =>
        continuation.map((after) => ({ ...before, to: after.to })),
      ),
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
