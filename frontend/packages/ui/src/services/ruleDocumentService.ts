/** Client-encrypted personal settings and ordinary encrypted Project Markdown files. */
import { get } from 'svelte/store';
import { getApiEndpoint } from '../config/api';
import { authStore } from '../stores/authStore';
import { userProfile, updateProfile } from '../stores/userProfile';
import { activeChatStore } from '../stores/activeChatStore';
import { decryptWithMasterKey, encryptWithMasterKey } from './encryption/MetadataEncryptor';
import { decryptWithEmbedKey, encryptWithEmbedKey, wrapEmbedKeyWithChatKey } from './cryptoService';
import { chatKeyManager } from './encryption/ChatKeyManager';
import {
  approveProjectWrite, getActiveProjectFocus, getProject, getProjectContents,
  getProjectSettings, getProjectFileRevisionReceipt, readEncryptedProjectFile,
  type ProjectItemViewModel,
} from './projectService';
import {
  executeHostedProjectFileJob, type HostedProjectFileAdapter,
} from './hostedProjectFileExecutor';
import { projectFileMutationDigest, type ProjectFileMutation } from '../utils/projectFileMutationProtocol';
import type { ProjectFileJob } from './projectFileJobExecutor';
import {
  buildWholeDocumentPatch, parseRuleDocument, validateRuleCatalog, type CustomRuleDocument,
} from '../utils/ruleDocuments';
import { broadcastProjectFilesChanged } from './projectBrowserEvents';
import { projectRecordRevision } from '../utils/projectContextRevision';

const PERSONAL_SETTINGS_KEY = 'rule_documents';
export const PROJECT_RULE_DIRECTORY = '.openmates/rules';
const projectItemRevision = (item: ProjectItemViewModel) => projectRecordRevision(item.encrypted as unknown as Record<string, unknown>);

export interface EditableRuleDocument extends CustomRuleDocument {
  path?: string;
  expectedBase?: string;
}

export interface SavedProjectMarkdownDocument {
  project_item_id: string;
  embed_id: string;
  version_id: number;
  file_operation_id: string;
  item_revision: string;
}

function requireOwner(): string {
  const owner = get(userProfile).user_id;
  if (!get(authStore).isAuthenticated || !owner) throw new Error('rule_auth_required');
  return owner;
}

async function accountSettings(): Promise<{ owner: string; ciphertext: string | null; settings: Record<string, unknown> }> {
  const owner = requireOwner();
  const ciphertext = get(userProfile).encrypted_settings ?? null;
  const plaintext = ciphertext ? await decryptWithMasterKey(ciphertext) : '{}';
  if (!plaintext || requireOwner() !== owner) throw new Error('rule_settings_unavailable');
  const settings: unknown = JSON.parse(plaintext);
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)) throw new Error('rule_settings_unavailable');
  return { owner, ciphertext, settings: settings as Record<string, unknown> };
}

function personalDocuments(settings: Record<string, unknown>): CustomRuleDocument[] {
  const documents = settings[PERSONAL_SETTINGS_KEY];
  if (documents === undefined) return [];
  if (!Array.isArray(documents)) throw new Error('invalid_rule_document');
  const result = documents.map((value: unknown) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid_rule_document');
    const rule = value as Record<string, unknown>;
    if (typeof rule.id !== 'string' || typeof rule.document !== 'string'
      || Object.keys(rule).some((key) => !['id', 'document'].includes(key))) throw new Error('invalid_rule_document');
    return { id: rule.id, source: 'personal' as const, document: rule.document };
  });
  return validateRuleCatalog(result);
}

export async function listPersonalRuleDocuments(): Promise<EditableRuleDocument[]> {
  return personalDocuments((await accountSettings()).settings);
}

export async function savePersonalRuleDocument(input: { id?: string; document: string }): Promise<CustomRuleDocument> {
  parseRuleDocument(input.document);
  const snapshot = await accountSettings();
  const documents = personalDocuments(snapshot.settings);
  const rule: CustomRuleDocument = { id: input.id ?? `personal:${crypto.randomUUID()}`, source: 'personal', document: input.document };
  const index = documents.findIndex((item) => item.id === rule.id);
  if (input.id && index < 0) throw new Error('rule_not_found');
  if (index < 0) documents.push(rule); else documents[index] = rule;
  validateRuleCatalog(documents);
  snapshot.settings[PERSONAL_SETTINGS_KEY] = documents.map(({ id, document }) => ({ id, document }));
  const encrypted = await encryptWithMasterKey(JSON.stringify(snapshot.settings));
  if (!encrypted) throw new Error('rule_settings_unavailable');
  if (requireOwner() !== snapshot.owner || (get(userProfile).encrypted_settings ?? null) !== snapshot.ciphertext) {
    throw new Error('rule_settings_changed');
  }
  const response = await fetch(getApiEndpoint('/v1/settings/encrypted-account'), {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ encrypted_settings: encrypted }),
  });
  if (!response.ok) throw new Error('rule_save_failed');
  if (requireOwner() !== snapshot.owner) throw new Error('rule_auth_required');
  updateProfile({ encrypted_settings: encrypted });
  return rule;
}

function job(chatId: string, projectId: string, operation: ProjectFileJob['operation'], path: string, operationId: string = crypto.randomUUID()): ProjectFileJob {
  // Direct owner actions reuse the guarded hosted adapter; no server job lease is invented.
  return {
    protocol_version: 1, operation_id: operationId, chat_id: chatId, project_id: projectId,
    operation, arguments: { path }, lease_token: '', lease_generation: 0, lease_expires_at: 0,
  };
}

async function activeProjectAdapter(chatId: string, projectId: string): Promise<HostedProjectFileAdapter & { itemIdsByPath: Map<string, string>; writeMode: string | null }> {
  const owner = requireOwner();
  const focus = await getActiveProjectFocus(chatId);
  if (focus?.project_id !== projectId) throw new Error('rule_project_activation_required');
  const chatKey = await chatKeyManager.getKey(chatId);
  if (!chatKey || requireOwner() !== owner) throw new Error('rule_auth_required');
  const context = { teamId: focus.team_id };
  const project = await getProject(projectId, context);
  const [contents, settings] = await Promise.all([getProjectContents(project, context), getProjectSettings(project, context)]);
  let accessSettings = settings.settings;
  if (settings.encrypted?.encrypted_settings) {
    const plaintext = await decryptWithEmbedKey(settings.encrypted.encrypted_settings, project.projectKey);
    if (plaintext === null) throw new Error('rule_project_unavailable');
    let decoded: unknown;
    try { decoded = JSON.parse(plaintext); } catch { throw new Error('rule_project_unavailable'); }
    if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) throw new Error('rule_project_unavailable');
    accessSettings = decoded as Record<string, unknown>;
  }
  const fileAccess = accessSettings.file_access;
  if (fileAccess !== undefined && (!fileAccess || typeof fileAccess !== 'object' || Array.isArray(fileAccess))) throw new Error('rule_project_unavailable');
  const privatePaths = fileAccess && typeof fileAccess === 'object' && !Array.isArray(fileAccess)
    ? (fileAccess as Record<string, unknown>).private_paths : undefined;
  if (privatePaths !== undefined && (!Array.isArray(privatePaths) || privatePaths.length > 256
    || privatePaths.some((path: unknown) => typeof path !== 'string' || !path || path.length > 4096))) throw new Error('rule_project_unavailable');
  const requireFreshBinding = async () => {
    const current = await getActiveProjectFocus(chatId);
    if (requireOwner() !== owner || current?.project_id !== projectId || current?.team_id !== focus.team_id) {
      throw new Error('rule_project_activation_required');
    }
  };
  await requireFreshBinding();
  return {
    projectId, projectKey: project.projectKey, chatKey, teamId: focus.team_id,
    privatePaths: privatePaths as string[] | undefined,
    writeMode: settings.writeMode ?? null,
    itemIdsByPath: new Map(contents.items.map((item) => [String(item.metadata.path ?? item.metadata.display_path ?? item.metadata.file_path ?? item.metadata.filename ?? item.displayName), item.project_item_id])),
    encrypt: encryptWithEmbedKey, wrap: wrapEmbedKeyWithChatKey,
    encodeContent: async (content) => JSON.stringify(content),
    listFiles: async () => contents.items.filter((item) => item.target_id && ['embed', 'upload'].includes(item.item_type))
      .map((item) => ({ embedId: item.target_id, path: String(item.metadata.path ?? item.metadata.display_path ?? item.metadata.file_path ?? item.metadata.filename ?? item.displayName) })),
    readHead: async (embedId) => {
      if (requireOwner() !== owner) throw new Error('rule_auth_required');
      return readEncryptedProjectFile(project, embedId, context);
    },
    receipt: (embedId, currentJob, digest) => getProjectFileRevisionReceipt(projectId, embedId, currentJob.operation_id, chatId, digest, context),
    commit: async (payload) => {
      await requireFreshBinding();
      const { chatSyncService } = await import('./chatSyncService');
      return chatSyncService.commitProjectFileRevision(payload);
    },
  };
}

export async function listProjectRuleDocuments(input: { chatId: string; projectId: string }): Promise<EditableRuleDocument[]> {
  const adapter = await activeProjectAdapter(input.chatId, input.projectId);
  const listing = await executeHostedProjectFileJob(adapter, job(input.chatId, input.projectId, 'list', PROJECT_RULE_DIRECTORY));
  const entries = listing.entries as Array<{ path: string }>;
  const rules: EditableRuleDocument[] = [];
  for (const entry of entries.slice(0, 24)) {
    if (!/^\.openmates\/rules\/[a-zA-Z0-9_-]+\.md$/.test(entry.path)) continue;
    const result = await executeHostedProjectFileJob(adapter, job(input.chatId, input.projectId, 'read_text', entry.path));
    if (typeof result.content !== 'string') throw new Error('invalid_rule_document');
    parseRuleDocument(result.content);
    rules.push({
      id: adapter.itemIdsByPath.get(entry.path) ?? '',
      source: 'project', project_id: input.projectId, document: result.content,
      path: entry.path, expectedBase: String(result.expected_base),
    });
  }
  validateRuleCatalog(rules);
  return rules;
}

export async function readActiveProjectMarkdownDocuments(input: {
  chatId: string; projectId: string; requests: readonly { itemId: string; path: string }[];
}): Promise<Array<{ item_id: string; path: string; document: string; file_revision: number }>> {
  if (input.requests.length > 6) throw new Error('project_document_limit');
  const owner = requireOwner();
  const adapter = await activeProjectAdapter(input.chatId, input.projectId);
  const result = [];
  let total = 0;
  for (const request of input.requests) {
    if (adapter.itemIdsByPath.get(request.path) !== request.itemId) continue;
    const read = await executeHostedProjectFileJob(adapter, job(input.chatId, input.projectId, 'read_text', request.path));
    if (typeof read.content !== 'string' || read.truncated) throw new Error('invalid_project_document');
    total += read.content.length;
    if (total > 60_000) throw new Error('project_document_limit');
    result.push({ item_id: request.itemId, path: request.path, document: read.content, file_revision: Number(read.revision) });
  }
  const fresh = await getActiveProjectFocus(input.chatId);
  if (requireOwner() !== owner || fresh?.project_id !== input.projectId || fresh?.team_id !== adapter.teamId) return [];
  return result;
}

export async function saveProjectRuleDocument(input: { chatId: string; projectId: string; document: string; existing?: EditableRuleDocument }): Promise<void> {
  parseRuleDocument(input.document);
  await saveProjectMarkdownDocument({
    chatId: input.chatId, projectId: input.projectId, document: input.document,
    path: input.existing?.path ?? `${PROJECT_RULE_DIRECTORY}/${crypto.randomUUID()}.md`,
    metadata: { rule_document: true }, existingDocument: input.existing?.document,
    expectedBase: input.existing?.expectedBase, saveApproved: true,
  });
}

export async function saveProjectMarkdownDocument(input: {
  chatId: string; projectId: string; path: string; document: string;
  metadata: Record<string, unknown>; itemId?: string; expectedItemRevision?: string;
  existingDocument?: string; expectedBase?: string;
  operationId?: string; expectedEmbedRevision?: number;
  /** Set only by a click that reviews/saves this actual document, not the earlier authoring request. */
  saveApproved?: boolean;
}): Promise<SavedProjectMarkdownDocument> {
  if (new TextEncoder().encode(input.document).length > 200 * 1024) throw new Error('project_document_limit');
  const adapter = await activeProjectAdapter(input.chatId, input.projectId);
  const path = input.path;
  const project = await getProject(input.projectId, { teamId: adapter.teamId });
  const before = await getProjectContents(project, { teamId: adapter.teamId });
  const found = before.items.filter((item) => item.metadata.path === path || item.metadata.display_path === path || item.project_item_id === input.itemId);
  if (found.length > 1 || input.itemId && (!found[0] || found[0].project_item_id !== input.itemId)) throw new Error('project_document_changed');
  const existing = found[0];
  if (input.expectedEmbedRevision !== undefined) {
    if (!existing && input.expectedEmbedRevision !== 0) throw new Error('project_document_changed');
    const readHead = adapter.readHead;
    adapter.readHead = async (embedId) => {
      const head = await readHead(embedId);
      if (existing?.target_id === embedId && head.revision !== input.expectedEmbedRevision) throw new Error('project_document_changed');
      return head;
    };
  }
  const itemRevision = existing ? await projectItemRevision(existing) : undefined;
  if (input.expectedItemRevision && itemRevision !== input.expectedItemRevision) throw new Error('project_document_changed');
  let original = input.existingDocument;
  let expectedBase = input.expectedBase;
  if (existing && original === undefined) {
    const read = await executeHostedProjectFileJob(adapter, job(input.chatId, input.projectId, 'read_text', path));
    if (typeof read.content !== 'string' || typeof read.expected_base !== 'string') throw new Error('invalid_project_document');
    original = read.content;
    expectedBase = read.expected_base;
  }
  const mutation: ProjectFileMutation = existing ? {
    operation: 'update_file', operation_id: input.operationId ?? crypto.randomUUID(), path, expected_base: expectedBase ?? null,
    patch: buildWholeDocumentPatch(original ?? '', input.document, path),
  } : { operation: 'create_file', operation_id: input.operationId ?? crypto.randomUUID(), path, expected_base: null, content: input.document };
  if (adapter.writeMode !== 'apply_and_show' && input.saveApproved !== true) {
    throw new Error('project_document_approval_required');
  }
  const commit = adapter.commit;
  adapter.commit = async (payload) => {
    const creation = payload.create;
    if (creation && typeof creation === 'object') {
      payload.create = { ...creation,
        encrypted_metadata: await encryptWithEmbedKey(JSON.stringify({ ...input.metadata, path, display_path: path, source: 'hosted_project_file' }), adapter.projectKey),
      };
    }
    return commit(payload);
  };
  const digest = await projectFileMutationDigest(adapter.projectKey, input.projectId, input.chatId, mutation);
  await approveProjectWrite(input.projectId, { chat_id: input.chatId, operation_id: mutation.operation_id, proposal_digest: digest }, { teamId: adapter.teamId });
  const applied = await executeHostedProjectFileJob(adapter, job(input.chatId, input.projectId, mutation.operation, path, mutation.operation_id), mutation);
  if (existing) {
    const response = await fetch(getApiEndpoint(`/v1/projects/${encodeURIComponent(input.projectId)}/items/${encodeURIComponent(existing.project_item_id)}${adapter.teamId ? `?team_id=${encodeURIComponent(adapter.teamId)}` : ''}`), {
      method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        encrypted_metadata: await encryptWithEmbedKey(JSON.stringify({ ...existing.metadata, ...input.metadata, path, display_path: path }), adapter.projectKey),
        updated_at: Math.floor(Date.now() / 1000), expected_item_revision: itemRevision,
      }),
    });
    if (!response.ok) throw new Error('project_document_metadata_failed');
  }
  const after = await getProjectContents(project, { teamId: adapter.teamId });
  const saved = after.items.find((item) => item.target_id === applied.embed_id);
  if (!saved) throw new Error('project_document_save_unconfirmed');
  broadcastProjectFilesChanged(input.projectId);
  return { project_item_id: saved.project_item_id, embed_id: saved.target_id,
    version_id: Number(applied.revision), file_operation_id: mutation.operation_id,
    item_revision: await projectItemRevision(saved) };
}

export async function collectCustomRuleDocuments(input: { chatId: string; projectId?: string | null }): Promise<CustomRuleDocument[]> {
  if (!get(authStore).isAuthenticated || !get(userProfile).user_id) return [];
  const owner = requireOwner();
  const personal = await listPersonalRuleDocuments();
  const focus = await getActiveProjectFocus(input.chatId);
  if (!get(authStore).isAuthenticated || get(userProfile).user_id !== owner) return [];
  if (!focus || input.projectId && focus.project_id !== input.projectId) return personal;
  const project = await listProjectRuleDocuments({ chatId: input.chatId, projectId: focus.project_id });
  const fresh = await getActiveProjectFocus(input.chatId);
  if (requireOwner() !== owner) return [];
  const documents = fresh?.project_id === focus.project_id && fresh?.team_id === focus.team_id ? [...personal, ...project] : personal;
  const bounded: CustomRuleDocument[] = [];
  let chars = 0;
  for (const { id, source, project_id, document } of documents) {
    if (bounded.length >= 24 || chars + document.length > 64_000) continue;
    bounded.push({ id, source, ...(project_id ? { project_id } : {}), document });
    chars += document.length;
  }
  return validateRuleCatalog(bounded);
}

export function activeRuleChatId(): string | null { return activeChatStore.get(); }
