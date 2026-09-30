// The CLI and web app share this portable definition. YAML I/O stays in clients;
// retained Workflow encryption and authoritative graph validation stay on the API.

export const WORKFLOW_FILE_MAX_BYTES = 1_048_576;

export interface WorkflowFileNode {
  id: string;
  type: string;
  title?: string | null;
  config?: Record<string, unknown>;
  input_mapping?: Record<string, unknown>;
  ui?: Record<string, unknown>;
}

export interface WorkflowFileGraph {
  version: number;
  trigger_node_id: string | null;
  nodes: WorkflowFileNode[];
  edges: Array<{ from: string; to: string; branch?: string | null }>;
  variables?: Record<string, unknown>;
  limits?: Record<string, unknown>;
  ui_layout?: Record<string, unknown>;
}

export interface WorkflowFileBinding {
  type: string;
  node_id: string;
  app_id?: string;
  skill_id?: string;
}

export interface WorkflowFileDocument {
  format: "openmates-workflow";
  format_version: 1;
  workflow: {
    title: string;
    description?: string | null;
    run_content_retention: "last_5" | "none";
    graph: WorkflowFileGraph;
  };
  binding_requirements: WorkflowFileBinding[];
}

export interface WorkflowFileSource {
  title: string;
  description?: string | null;
  run_content_retention?: "last_5" | "none";
  graph: WorkflowFileGraph;
  binding_requirements?: WorkflowFileBinding[];
}

const FORBIDDEN_KEYS = new Set([
  "token", "accesstoken", "refreshtoken", "authtoken", "bearertoken", "secret",
  "credential", "credentials", "password", "apikey", "privatekey", "vaultkey",
  "masterkey", "encryptionkey", "authorization", "grant", "grantid", "accountid",
  "connectedaccountid", "connectionid", "provideruserid", "userid", "ownerid", "ownerhash", "teamid",
  "projectid", "workflowid", "versionid", "runid", "chatid", "sourcechatid",
  "encryptedgraphblobref", "encryptedcontentref", "fragmentkey", "shortkey",
  "templatekey", "nextrunat", "providerresponse", "runhistory", "deliveryhistory",
  "cookie", "sessioncookie", "sessionid", "encryptedkey", "encryptedpayload", "ciphertext", "vault",
  "claimtoken", "deliveryid", "encryptedgraphref", "lastrunat",
]);

// Provider prefixes are common in authored skill inputs. Keep credential suffixes
// out of portable files without rejecting ordinary fields such as token_count.
const CREDENTIAL_SUFFIXES = [
  "accesstoken", "refreshtoken", "authtoken", "bearertoken", "sessiontoken",
  "apikey", "privatekey", "clientsecret", "secret", "password", "credential",
  "credentials", "authorization", "vaultkey", "masterkey", "encryptionkey",
];

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}

function onlyKeys(value: Record<string, unknown>, keys: string[], path: string): void {
  for (const key of Object.keys(value)) {
    if (!keys.includes(key)) throw new Error(`Unsupported Workflow file field: ${path}.${key}.`);
  }
}

function assertPortable(value: unknown): void {
  let remaining = 50_000;
  const active = new Set<object>();
  function visit(item: unknown, path: string, depth: number): void {
    if (--remaining < 0 || depth > 64) throw new Error("Workflow file is too complex.");
    if (typeof item === "number" && !Number.isFinite(item)) throw new Error("Workflow file contains an invalid number.");
    if (item === null || ["string", "boolean", "number"].includes(typeof item)) return;
    if (!Array.isArray(item) && !record(item)) throw new Error(`Invalid Workflow file value at ${path}.`);
    if (active.has(item)) throw new Error("Workflow file contains a circular reference.");
    active.add(item);
    if (Array.isArray(item)) {
      item.forEach((child, i) => visit(child, `${path}[${i}]`, depth + 1));
    } else {
      for (const [key, child] of Object.entries(item)) {
        const normalized = key.toLowerCase().replace(/[^a-z0-9]/g, "");
        if (["__proto__", "constructor", "prototype"].includes(key)
          || FORBIDDEN_KEYS.has(normalized) || CREDENTIAL_SUFFIXES.some((suffix) => normalized.endsWith(suffix))) {
          throw new Error(`Workflow file contains an account-specific or private field at ${path}.${key}.`);
        }
        visit(child, `${path}.${key}`, depth + 1);
      }
    }
    active.delete(item);
  }
  visit(value, "$", 0);
}

function remapGraph(graph: WorkflowFileGraph, ids: Map<string, string>): WorkflowFileGraph {
  const escaped = Array.from(ids.keys()).sort((a, b) => b.length - a.length)
    .map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const references = escaped.length
    ? new RegExp(`(\\$nodes\\.|\\{\\{\\s*steps\\.)(${escaped.join("|")})(?=[.}\\s]|$)`, "g")
    : null;
  function visit(value: unknown): unknown {
    if (typeof value === "string") return references
      ? value.replace(references, (_match, prefix: string, id: string) => prefix + ids.get(id))
      : value;
    if (Array.isArray(value)) return value.map((item) => visit(item));
    if (record(value)) return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, visit(child)]));
    return value;
  }
  const mapped = visit(graph) as WorkflowFileGraph;
  if (graph.ui_layout) mapped.ui_layout = Object.fromEntries(
    Object.entries(graph.ui_layout).map(([key, child]) => [ids.get(key) ?? key, visit(child)]),
  );
  mapped.trigger_node_id = graph.trigger_node_id ? ids.get(graph.trigger_node_id) ?? graph.trigger_node_id : null;
  mapped.nodes.forEach((node, i) => { node.id = ids.get(graph.nodes[i].id) ?? node.id; });
  mapped.edges.forEach((edge, i) => {
    edge.from = ids.get(graph.edges[i].from) ?? edge.from;
    edge.to = ids.get(graph.edges[i].to) ?? edge.to;
  });
  return mapped;
}

/** Export a saved definition, excluding record IDs and runtime state. */
export function buildWorkflowFile(source: WorkflowFileSource): WorkflowFileDocument {
  const graph = JSON.parse(JSON.stringify(source.graph)) as WorkflowFileGraph;
  const ids = new Map(graph.nodes.map((node, i) => [node.id, `step_${i + 1}`]));
  const requirements: WorkflowFileBinding[] = [];
  const addBinding = (binding: WorkflowFileBinding) => {
    if (!requirements.some((item) => item.type === binding.type && item.node_id === binding.node_id)) requirements.push(binding);
  };
  graph.nodes = graph.nodes.map((node) => {
    const config = { ...(node.config ?? {}) };
    if (node.type === "schedule_trigger") addBinding({ type: "schedule", node_id: node.id });
    if (node.type === "app_skill_action") addBinding({
      type: "app_skill", node_id: node.id,
      app_id: String(config.app_id ?? ""), skill_id: String(config.skill_id ?? ""),
    });
    if (node.type === "send_notification" || node.type === "send_email_notification") {
      addBinding({ type: "notification_preferences", node_id: node.id });
    }
    if (node.type === "send_chat_message") {
      if (config.chat_id || config.destination_required || source.binding_requirements?.some((item) => item.type === "chat_destination" && item.node_id === node.id)) {
        delete config.chat_id;
        config.destination_required = true;
        addBinding({ type: "chat_destination", node_id: node.id });
      } else delete config.chat_id;
    }
    return {
      id: node.id, type: node.type,
      ...(node.title != null ? { title: node.title } : {}), config,
      ...(node.input_mapping != null ? { input_mapping: node.input_mapping } : {}),
      ...(node.ui != null ? { ui: node.ui } : {}),
    };
  });
  const document: WorkflowFileDocument = {
    format: "openmates-workflow", format_version: 1,
    workflow: {
      title: source.title,
      description: source.description ?? null,
      run_content_retention: source.run_content_retention ?? "last_5",
      graph: remapGraph(graph, ids),
    },
    binding_requirements: requirements.map((item) => ({ ...item, node_id: ids.get(item.node_id)! })),
  };
  return validateWorkflowFile(document);
}

/** Validate a parsed YAML document without accepting runtime records as files. */
export function validateWorkflowFile(value: unknown): WorkflowFileDocument {
  if (!record(value) || value.format !== "openmates-workflow") throw new Error("This is not an OpenMates Workflow file.");
  if (value.format_version !== 1) throw new Error("This Workflow file version is not supported.");
  onlyKeys(value, ["format", "format_version", "workflow", "binding_requirements"], "$");
  const workflow = value.workflow;
  if (!record(workflow)) throw new Error("Workflow file is missing its definition.");
  onlyKeys(workflow, ["title", "description", "run_content_retention", "graph"], "$.workflow");
  if (typeof workflow.title !== "string" || !workflow.title.trim() || workflow.title.length > 200) throw new Error("Workflow file needs a title of at most 200 characters.");
  if (workflow.description != null && (typeof workflow.description !== "string" || workflow.description.length > 2_000)) throw new Error("Workflow file description is invalid.");
  if (!["last_5", "none"].includes(String(workflow.run_content_retention))) throw new Error("Workflow file retention setting is invalid.");
  const graph = workflow.graph;
  if (!record(graph) || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges) || !Number.isInteger(graph.version) || Number(graph.version) < 1) throw new Error("Workflow file graph is invalid.");
  onlyKeys(graph, ["version", "trigger_node_id", "nodes", "edges", "variables", "limits", "ui_layout"], "$.workflow.graph");
  for (const key of ["variables", "limits", "ui_layout"]) {
    if (graph[key] != null && !record(graph[key])) throw new Error(`Workflow graph ${key} must be an object.`);
  }
  const ids = new Set<string>();
  for (const node of graph.nodes) {
    if (!record(node) || typeof node.id !== "string" || !node.id || typeof node.type !== "string" || !node.type || !record(node.config)) throw new Error("Workflow file contains an invalid step.");
    onlyKeys(node, ["id", "type", "title", "config", "input_mapping", "ui"], "$.workflow.graph.nodes");
    if (ids.has(node.id)) throw new Error("Workflow file contains duplicate step identifiers.");
    if (node.title != null && typeof node.title !== "string") throw new Error("Workflow step title is invalid.");
    for (const key of ["input_mapping", "ui"]) {
      if (node[key] != null && !record(node[key])) throw new Error(`Workflow step ${key} must be an object.`);
    }
    ids.add(node.id);
  }
  if (graph.trigger_node_id !== null && (typeof graph.trigger_node_id !== "string" || !ids.has(graph.trigger_node_id))) throw new Error("Workflow trigger references a missing step.");
  for (const edge of graph.edges) {
    if (!record(edge) || typeof edge.from !== "string" || typeof edge.to !== "string" || !ids.has(edge.from) || !ids.has(edge.to)) throw new Error("Workflow file contains a link to a missing step.");
    onlyKeys(edge, ["from", "to", "branch"], "$.workflow.graph.edges");
    if (edge.branch != null && typeof edge.branch !== "string") throw new Error("Workflow branch is invalid.");
  }
  if (!Array.isArray(value.binding_requirements)) throw new Error("Workflow file is missing its recipient review requirements.");
  for (const binding of value.binding_requirements) {
    if (!record(binding) || !["schedule", "app_skill", "chat_destination", "notification_preferences"].includes(String(binding.type)) || typeof binding.node_id !== "string" || !ids.has(binding.node_id)) throw new Error("Workflow file contains an invalid recipient review requirement.");
    onlyKeys(binding, ["type", "node_id", "app_id", "skill_id"], "$.binding_requirements");
    for (const key of ["app_id", "skill_id"]) {
      if (binding[key] != null && typeof binding[key] !== "string") throw new Error("Workflow app requirement is invalid.");
    }
  }
  assertPortable(value);
  return JSON.parse(JSON.stringify(value)) as WorkflowFileDocument;
}

export function workflowFileName(title: string): string {
  // eslint-disable-next-line no-control-regex -- Export filenames must exclude control characters.
  const stem = title.normalize("NFKC").replace(/[\x00-\x1f/\\<>:"|?*]/g, "-")
    .replace(/\.workflow\.ya?ml$/i, "").replace(/^\.+|[. ]+$/g, "").trim().slice(0, 100);
  return `${stem || "workflow"}.workflow.yml`;
}
