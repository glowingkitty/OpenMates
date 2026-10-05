/** Client-encrypted personal settings and ordinary encrypted Project Markdown files. */
import { get } from 'svelte/store';
import { getApiEndpoint } from '../config/api';
import { authStore } from '../stores/authStore';
import { publishPersonalDocumentMemories } from '../stores/personalDocumentMemories';
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
  buildWholeDocumentPatch, parseRuleDocument, serializeRuleDocument, validateRuleCatalog, type CustomRuleDocument,
} from '../utils/ruleDocuments';
import { broadcastProjectFilesChanged } from './projectBrowserEvents';
import { projectRecordRevision } from '../utils/projectContextRevision';

const PERSONAL_SETTINGS_KEY = 'memory_documents';
const LEGACY_PERSONAL_SETTINGS_KEY = 'rule_documents';
export const PROJECT_RULE_DIRECTORY = '.openmates/memories';
const LEGACY_PROJECT_RULE_DIRECTORY = '.openmates/rules';
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
  const legacy = settings[LEGACY_PERSONAL_SETTINGS_KEY] ?? [];
  const canonical = settings[PERSONAL_SETTINGS_KEY] ?? [];
  if (!Array.isArray(legacy) || !Array.isArray(canonical)) throw new Error('invalid_rule_document');
  // New writes supersede their legacy identity; preserve encrypted legacy data.
  const byId = new Map<string, unknown>();
  for (const entry of [...legacy, ...canonical]) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry) || typeof entry.id !== 'string') throw new Error('invalid_rule_document');
    byId.set(entry.id, entry);
  }
  const documents = [...byId.values()];
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
  await persistPersonalSettings(snapshot);
  return rule;
}

async function persistPersonalSettings(snapshot: Awaited<ReturnType<typeof accountSettings>>) {
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
}

export async function savePersonalDocumentMemoryEntry(entryId: string, value: { title: string; document: string }) {
  const original = (await listPersonalRuleDocuments()).find(document => `account-memory-${document.id.replace(/^personal:/, '')}` === entryId);
  if (!original) throw new Error('rule_not_found');
  return savePersonalRuleDocument({id: original.id, document: serializeRuleDocument({...parseRuleDocument(value.document), title: value.title})});
}

export async function deletePersonalDocumentMemoryEntry(entryId: string) {
  const snapshot = await accountSettings();
  const document = personalDocuments(snapshot.settings).find(item => `account-memory-${item.id.replace(/^personal:/, '')}` === entryId);
  if (!document) throw new Error('rule_not_found');
  for (const key of [PERSONAL_SETTINGS_KEY, LEGACY_PERSONAL_SETTINGS_KEY]) {
    const values = snapshot.settings[key];
    if (Array.isArray(values)) snapshot.settings[key] = values.filter(value => value.id !== document.id);
  }
  await persistPersonalSettings(snapshot);
}

function job(chatId: string, projectId: string, operation: ProjectFileJob['operation'], path: string, operationId: string = crypto.randomUUID()): ProjectFileJob {
  // Direct owner actions reuse the guarded hosted adapter; no server job lease is invented.
  return {
    protocol_version: 1, operation_id: operationId, chat_id: chatId, project_id: projectId,
    operation, arguments: { path }, lease_token: '', lease_generation: 0, lease_expires_at: 0,
  };
}

async function activeProjectAdapter(chatId: string, projectId: string): Promise<HostedProjectFileAdapter & { itemIdsByPath: Map<string, string>; itemsByPath: Map<string, ProjectItemViewModel>; writeMode: string | null }> {
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
    itemsByPath: new Map(contents.items.map((item) => [String(item.metadata.path ?? item.metadata.display_path ?? item.metadata.file_path ?? item.metadata.filename ?? item.displayName), item])),
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
  const listings = await Promise.all([PROJECT_RULE_DIRECTORY, LEGACY_PROJECT_RULE_DIRECTORY].map(directory =>
    executeHostedProjectFileJob(adapter, job(input.chatId, input.projectId, 'list', directory))));
  const entries = listings.flatMap(listing => listing.entries as Array<{ path: string }>);
  const rules: EditableRuleDocument[] = [];
  for (const entry of entries.slice(0, 24)) {
    if (!/^\.openmates\/(?:memories|rules)\/[a-zA-Z0-9_-]+\.md$/.test(entry.path)) continue;
    const result = await executeHostedProjectFileJob(adapter, job(input.chatId, input.projectId, 'read_text', entry.path));
    if (typeof result.content !== 'string') throw new Error('invalid_rule_document');
    parseRuleDocument(result.content);
    rules.push({
      id: adapter.itemIdsByPath.get(entry.path) ?? '',
      source: 'project', project_id: input.projectId, document: result.content,
      path: entry.path, expectedBase: String(result.expected_base),
      item_revision: await projectItemRevision(adapter.itemsByPath.get(entry.path)!),
    });
  }
  const current = await getProjectContents(await getProject(input.projectId, {teamId: adapter.teamId}), {teamId: adapter.teamId});
  const retained = [];
  for (const memory of rules) {
    const item = current.items.find(item => item.project_item_id === memory.id);
    if (item && await projectItemRevision(item) === memory.item_revision) retained.push(memory);
  }
  validateRuleCatalog(retained);
  return retained;
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
    metadata: { memory_document: true, title: parseRuleDocument(input.document).title, description: parseRuleDocument(input.document).description }, existingDocument: input.existing?.document,
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
  // Personal Memories are advertised only as metadata and supplied after consent.
  const personal: CustomRuleDocument[] = [];
  const focus = await getActiveProjectFocus(input.chatId);
  if (!get(authStore).isAuthenticated || get(userProfile).user_id !== owner) return [];
  if (!focus || input.projectId && focus.project_id !== input.projectId) return personal;
  const project = await listProjectRuleDocuments({ chatId: input.chatId, projectId: focus.project_id });
  const fresh = await getActiveProjectFocus(input.chatId);
  if (requireOwner() !== owner) return [];
  const documents = fresh?.project_id === focus.project_id && fresh?.team_id === focus.team_id ? [...personal, ...project] : personal;
  const bounded: CustomRuleDocument[] = [];
  let chars = 0;
  for (const { id, source, project_id, document, item_revision } of documents) {
    if (bounded.length >= 24 || chars + document.length > 64_000) continue;
    bounded.push({ id, source, ...(project_id ? { project_id } : {}), document, item_revision });
    chars += document.length;
  }
  return validateRuleCatalog(bounded);
}

export function activeRuleChatId(): string | null { return activeChatStore.get(); }

/** Legacy account documents share the declared private OpenMates memory category. */
export async function personalDocumentMemoryEntries() {
  const owner = requireOwner(), revision = get(userProfile).encrypted_settings ?? null;
  const documents = await listPersonalRuleDocuments();
  if (requireOwner() !== owner || (get(userProfile).encrypted_settings ?? null) !== revision) throw new Error('rule_settings_changed');
  const entries = documents.map(document => {
    const fields = parseRuleDocument(document.document);
    return { id: `account-memory-${document.id.replace(/^personal:/, '')}`, app_id: 'openmates', item_key: fields.title,
      item_value: { title: fields.title, document: document.document } as Record<string, unknown>, settings_group: 'memories',
      created_at: 0, updated_at: 0, item_version: 1 };
  });
  publishPersonalDocumentMemories(owner, revision, entries);
  return entries;
}
