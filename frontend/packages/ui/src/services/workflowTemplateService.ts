// frontend/packages/ui/src/services/workflowTemplateService.ts
// Client-side encryption and transport for portable Workflow templates.
// Runtime Workflows stay server-authoritative; this module only creates a
// recursively validated, portable projection for sharing and import.
// Fragment keys are generated and consumed locally and never sent to the API.

import { getApiEndpoint } from "../config/api";
import { decryptChatKeyWithMasterKey, encryptChatKeyWithMasterKey } from "./cryptoService";
import { buildShortUrl, encryptShareUrl, generateShortUrlParts } from "./shortUrlEncryption";
import { workflowTemplateProjectionStore, type WorkflowTemplateProjectionLocalRecord } from "../stores/workflowTemplateProjectionStore";
import type { WorkflowDetail, WorkflowGraph, WorkflowNode } from "../stores/workflowWorkspaceStore";

const PROJECTION_SCHEMA_VERSION = 1;
const TEMPLATE_KEY_LENGTH = 32;
const AES_GCM_IV_LENGTH = 12;
const FORBIDDEN_FIELD_PARTS = [
  "token", "secret", "credential", "accountid", "connectionid", "connectedaccountid",
  "provideruserid", "webhooksecret", "apikey", "password", "vault", "grant", "runid",
  "versionid", "workflowid", "nextrunat", "claim", "wait", "output", "providerresponse",
  "sourcechatid", "encryptedgraphblobref", "encryptedcontentref", "fragmentkey", "shortkey",
  "templatekey",
];

export type WorkflowTemplateBindingRequirement = {
  type: string;
  node_id: string;
  app_id?: string;
  skill_id?: string;
};

export type WorkflowTemplatePayload = {
  template_version: number;
  title: string;
  description?: string | null;
  trigger_template: Record<string, unknown>;
  node_templates: Array<Record<string, unknown>>;
  edge_templates: Array<Record<string, unknown>>;
  variables_schema: Record<string, unknown>;
  required_capabilities: string[];
  binding_requirements: WorkflowTemplateBindingRequirement[];
};

export type ImportedWorkflowTemplate = WorkflowDetail & {
  binding_requirements: WorkflowTemplateBindingRequirement[];
};

type PublicProjectionResponse = {
  template_id: string;
  ciphertext: string;
  ciphertext_checksum: string;
  projection_schema_version: number;
};

type ShortShareResult = {
  shortUrl: string;
  longUrl: string;
  token: string;
};

function encodeBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of Array.from(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeBase64Url(value: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("Template key or ciphertext is malformed.");
  let base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4) base64 += "=";
  const binary = atob(base64);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function normalizedKey(key: string): string {
  return key.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function assertPortableValue(value: unknown, path = "$"): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertPortableValue(item, `${path}[${index}]`));
    return;
  }
  if (typeof value !== "object" || value === null) return;
  for (const [key, child] of Object.entries(value)) {
    const normalized = normalizedKey(key);
    if (FORBIDDEN_FIELD_PARTS.some((forbidden) => normalized.includes(forbidden))) {
      throw new Error(`Workflow template contains a non-portable field at ${path}.${key}.`);
    }
    assertPortableValue(child, `${path}.${key}`);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPortableNode(value: unknown): value is Record<string, unknown> {
  return isRecord(value)
    && typeof value.id === "string"
    && value.id.length > 0
    && typeof value.type === "string"
    && value.type.length > 0
    && isRecord(value.config);
}

function isPortableEdge(value: unknown): value is Record<string, unknown> {
  return isRecord(value)
    && typeof value.from === "string"
    && value.from.length > 0
    && typeof value.to === "string"
    && value.to.length > 0
    && (value.branch === undefined || typeof value.branch === "string");
}

function isBindingRequirement(value: unknown): value is WorkflowTemplateBindingRequirement {
  return isRecord(value)
    && typeof value.type === "string"
    && value.type.length > 0
    && typeof value.node_id === "string"
    && value.node_id.length > 0
    && (value.app_id === undefined || typeof value.app_id === "string")
    && (value.skill_id === undefined || typeof value.skill_id === "string");
}

function portableNode(node: WorkflowNode): Record<string, unknown> {
  const candidate = {
    id: node.id,
    type: node.type,
    ...(node.title ? { title: node.title } : {}),
    config: cloneJson(node.config ?? {}),
  };
  assertPortableValue(candidate, `$.nodes.${node.id}`);
  return candidate;
}

function bindingRequirements(graph: WorkflowGraph): WorkflowTemplateBindingRequirement[] {
  return graph.nodes.flatMap((node) => {
    if (node.type === "schedule_trigger") return [{ type: "schedule", node_id: node.id }];
    if (node.type === "app_skill_action") {
      const config = node.config ?? {};
      return [{
        type: "app_skill",
        node_id: node.id,
        app_id: String(config.app_id ?? ""),
        skill_id: String(config.skill_id ?? ""),
      }];
    }
    if (node.type === "send_notification" || node.type === "send_email_notification") {
      return [{ type: "notification_preferences", node_id: node.id }];
    }
    return [];
  });
}

function requiredCapabilities(requirements: WorkflowTemplateBindingRequirement[]): string[] {
  const capabilities = new Set<string>();
  for (const requirement of requirements) {
    if (requirement.type !== "app_skill" || !requirement.app_id) continue;
    capabilities.add(requirement.app_id);
    if (requirement.skill_id) capabilities.add(`${requirement.app_id}.${requirement.skill_id}`);
  }
  return Array.from(capabilities).sort();
}

function triggerNode(graph: WorkflowGraph): WorkflowNode {
  const trigger = graph.nodes.find((node) => node.id === graph.trigger_node_id);
  if (!trigger) throw new Error("Workflow does not have a portable trigger node.");
  return trigger;
}

export function buildWorkflowTemplatePayload(workflow: WorkflowDetail): WorkflowTemplatePayload {
  const trigger = triggerNode(workflow.graph);
  const requirements = bindingRequirements(workflow.graph);
  const payload: WorkflowTemplatePayload = {
    template_version: workflow.graph.version,
    title: workflow.title.trim(),
    description: workflow.description?.trim() || null,
    trigger_template: portableNode(trigger),
    node_templates: workflow.graph.nodes.filter((node) => node.id !== trigger.id).map(portableNode),
    edge_templates: workflow.graph.edges.map((edge) => cloneJson({ from: edge.from, to: edge.to, ...(edge.branch ? { branch: edge.branch } : {}) })),
    variables_schema: {},
    required_capabilities: requiredCapabilities(requirements),
    binding_requirements: requirements,
  };
  if (!payload.title) throw new Error("Workflow title is required before sharing.");
  assertPortableValue(payload);
  return payload;
}

export function validateWorkflowTemplatePayload(value: unknown): WorkflowTemplatePayload {
  if (!isRecord(value) || typeof value.template_version !== "number" || !Number.isInteger(value.template_version) || value.template_version < 1) {
    throw new Error("Workflow template has an invalid version.");
  }
  if (typeof value.title !== "string" || !value.title.trim() || !isPortableNode(value.trigger_template)) {
    throw new Error("Workflow template is missing required portable fields.");
  }
  const nodeTemplates = Array.isArray(value.node_templates) ? value.node_templates : null;
  const edgeTemplates = Array.isArray(value.edge_templates) ? value.edge_templates : null;
  const variablesSchema = isRecord(value.variables_schema) ? value.variables_schema : null;
  const capabilities = Array.isArray(value.required_capabilities) && value.required_capabilities.every((item) => typeof item === "string")
    ? value.required_capabilities
    : null;
  const requirements = Array.isArray(value.binding_requirements) && value.binding_requirements.every(isBindingRequirement)
    ? value.binding_requirements
    : null;
  if (!nodeTemplates || !nodeTemplates.every(isPortableNode) || !edgeTemplates || !edgeTemplates.every(isPortableEdge) || !variablesSchema || !capabilities || !requirements) {
    throw new Error("Workflow template has an invalid portable structure.");
  }
  assertPortableValue(value);
  return value as WorkflowTemplatePayload;
}

async function checksum(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return `sha256:${encodeBase64Url(new Uint8Array(digest))}`;
}

function generateTemplateId(): string {
  return `wt_${crypto.randomUUID().replace(/-/g, "")}`;
}

function generateTemplateKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(TEMPLATE_KEY_LENGTH));
}

async function encryptProjection(payload: WorkflowTemplatePayload, keyBytes: Uint8Array): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new Uint8Array(keyBytes), { name: "AES-GCM" }, false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const encrypted = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(JSON.stringify(payload)));
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);
  return encodeBase64Url(combined);
}

async function decryptProjection(ciphertext: string, encodedKey: string): Promise<WorkflowTemplatePayload> {
  const keyBytes = decodeBase64Url(encodedKey);
  if (keyBytes.length !== TEMPLATE_KEY_LENGTH) throw new Error("Workflow template key has an invalid length.");
  const combined = decodeBase64Url(ciphertext);
  if (combined.length <= AES_GCM_IV_LENGTH) throw new Error("Workflow template ciphertext is incomplete.");
  const key = await crypto.subtle.importKey("raw", new Uint8Array(keyBytes), { name: "AES-GCM" }, false, ["decrypt"]);
  const decrypted = await crypto.subtle.decrypt({ name: "AES-GCM", iv: combined.slice(0, AES_GCM_IV_LENGTH) }, key, combined.slice(AES_GCM_IV_LENGTH));
  return validateWorkflowTemplatePayload(JSON.parse(new TextDecoder().decode(decrypted)) as unknown);
}

async function workflowRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Content-Type", "application/json");
  const response = await fetch(getApiEndpoint(path), {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) throw new Error(`Workflow template request failed with HTTP ${response.status}.`);
  return await response.json() as T;
}

async function localTemplateKey(record: WorkflowTemplateProjectionLocalRecord): Promise<string> {
  const key = await decryptChatKeyWithMasterKey(record.ownerWrappedKey);
  if (!key || key.length !== TEMPLATE_KEY_LENGTH) throw new Error("Template key is unavailable on this device. Create a new share from the owner device.");
  return encodeBase64Url(key);
}

export async function upsertWorkflowTemplateProjection(workflow: WorkflowDetail): Promise<WorkflowTemplateProjectionLocalRecord> {
  const existing = workflowTemplateProjectionStore.get(workflow.id);
  const templateId = existing?.templateId ?? generateTemplateId();
  const keyBytes = existing ? decodeBase64Url(await localTemplateKey(existing)) : generateTemplateKey();
  const ownerWrappedKey = existing?.ownerWrappedKey ?? await encryptChatKeyWithMasterKey(keyBytes);
  if (!ownerWrappedKey) throw new Error("Your encryption key is unavailable. Re-authenticate before sharing this workflow.");
  const ciphertext = await encryptProjection(buildWorkflowTemplatePayload(workflow), keyBytes);
  const ciphertextChecksum = await checksum(ciphertext);
  const result = await workflowRequest<{ template_id: string; source_version: number; updated_at: number }>(
    `/v1/workflows/${encodeURIComponent(workflow.id)}/template-projection`,
    {
      method: "PUT",
      body: JSON.stringify({
        template_id: templateId,
        source_version: workflow.version ?? 1,
        ciphertext,
        ciphertext_checksum: ciphertextChecksum,
        owner_wrapped_key: ownerWrappedKey,
        projection_schema_version: PROJECTION_SCHEMA_VERSION,
      }),
    },
  );
  const record: WorkflowTemplateProjectionLocalRecord = {
    workflowId: workflow.id,
    templateId: result.template_id,
    sourceVersion: result.source_version,
    ciphertext,
    ciphertextChecksum,
    ownerWrappedKey,
    projectionSchemaVersion: PROJECTION_SCHEMA_VERSION,
    shortToken: existing?.shortToken,
    revokedAt: existing?.revokedAt ?? null,
    updatedAt: result.updated_at,
  };
  workflowTemplateProjectionStore.upsert(record);
  return record;
}

export async function createWorkflowTemplateShare(workflow: WorkflowDetail): Promise<ShortShareResult> {
  const record = await upsertWorkflowTemplateProjection(workflow);
  const longUrl = await buildWorkflowTemplateLongUrl(record);
  const { token, shortKey } = generateShortUrlParts();
  const encryptedUrl = await encryptShareUrl(longUrl, token, shortKey);
  await workflowRequest("/v1/share/short-url", {
    method: "POST",
    body: JSON.stringify({
      token,
      encrypted_url: encryptedUrl,
      content_type: "workflow_template",
      content_id: record.templateId,
      password_protected: false,
    }),
  });
  workflowTemplateProjectionStore.upsert({ ...record, shortToken: token, revokedAt: null, updatedAt: Date.now() });
  return { shortUrl: buildShortUrl(token, shortKey), longUrl, token };
}

export async function buildWorkflowTemplateLongUrl(record: WorkflowTemplateProjectionLocalRecord): Promise<string> {
  const templateKey = await localTemplateKey(record);
  const origin = typeof window === "undefined" ? "https://openmates.org" : window.location.origin;
  return `${origin}/share/workflow-template/${encodeURIComponent(record.templateId)}#key=${templateKey}`;
}

export async function revokeWorkflowTemplateShare(workflowId: string): Promise<void> {
  const record = workflowTemplateProjectionStore.get(workflowId);
  await workflowRequest(`/v1/workflows/${encodeURIComponent(workflowId)}/template-projection/revoke`, { method: "POST", body: "{}" });
  if (record?.shortToken) {
    await workflowRequest(`/v1/share/short-url/${encodeURIComponent(record.shortToken)}`, { method: "DELETE" });
  }
  workflowTemplateProjectionStore.setRevoked(workflowId, Date.now());
}

export async function unrevokeWorkflowTemplateShare(workflowId: string): Promise<void> {
  await workflowRequest(`/v1/workflows/${encodeURIComponent(workflowId)}/template-projection/unrevoke`, { method: "POST", body: "{}" });
  workflowTemplateProjectionStore.setRevoked(workflowId, null);
}

export async function loadSharedWorkflowTemplate(templateId: string, templateKey: string): Promise<WorkflowTemplatePayload> {
  const projection = await workflowRequest<PublicProjectionResponse>(`/v1/workflows/template-projections/${encodeURIComponent(templateId)}`);
  if (projection.template_id !== templateId || projection.projection_schema_version !== PROJECTION_SCHEMA_VERSION) {
    throw new Error("Workflow template projection is not compatible with this app version.");
  }
  if (projection.ciphertext_checksum !== await checksum(projection.ciphertext)) {
    throw new Error("Workflow template integrity check failed.");
  }
  return await decryptProjection(projection.ciphertext, templateKey);
}

export async function importWorkflowTemplate(payload: WorkflowTemplatePayload): Promise<ImportedWorkflowTemplate> {
  const response = await workflowRequest<{ workflow: ImportedWorkflowTemplate }>("/v1/workflows/template-import", {
    method: "POST",
    body: JSON.stringify(validateWorkflowTemplatePayload(payload)),
  });
  if (!response.workflow || response.workflow.enabled) throw new Error("Imported workflow did not remain disabled for rebinding.");
  return response.workflow;
}

export async function completeWorkflowTemplateBinding(workflowId: string, requirement: WorkflowTemplateBindingRequirement): Promise<void> {
  await workflowRequest(`/v1/workflows/${encodeURIComponent(workflowId)}/binding-requirements/complete`, {
    method: "POST",
    body: JSON.stringify({ type: requirement.type, node_id: requirement.node_id }),
  });
}
