// frontend/packages/ui/src/services/projectService.ts
// Client-side Projects V1 service.
//
// Projects use a project-specific AES key for metadata. Uploaded files are
// represented as embeds first, then linked into a project via project_items.

import { getApiEndpoint, storageArchiveFetch } from "../config/api";
import { get } from "svelte/store";
import { featureAvailabilityStore } from "../stores/appSkillsStore";
import { WorkspaceQueryCache, getWorkspaceCacheIdentity, WorkspaceCacheDiscardedError } from "./workspaceQueryCache";
import { PROJECTS_CHANGED_EVENT } from "./projectBrowserEvents";
import { getTeamKey } from './teamService';
import { getActiveTeamContextSnapshot } from '../stores/teamStore';
import { computeSHA256 } from "../message_parsing/utils";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
  wrapEmbedKeyWithChatKey,
  wrapEmbedKeyWithMasterKey,
  unwrapEmbedKeyWithEmbedKey,
} from "./cryptoService";
import { embedStore } from "./embedStore";
import { uploadFileToServer } from "../components/enter_message/services/uploadService";
import { classifyMindMapUploadSource } from "../components/enter_message/services/mindMapUploadDetection";
import { normalizeMindMapSource } from "../components/embeds/mindmaps/mindMapContent";
import { generateDirectEmbedRef } from "../utils/embedFragmentUtils";
import {
  buildProjectSourceCreatePayload,
  type ProjectSourceCapability,
  type ProjectSourceCreatePayload,
  type ProjectSourceStatus,
  type ProjectSourceType,
  type ProjectWriteMode,
  type ProjectRemoteAccessOperation as ProjectRemoteSourceOperation,
} from "./projectRemoteSources";
import type { HostedProjectFileHead } from "./hostedProjectFileExecutor";
import { PROJECT_RUST_CORE, decideProject, projectRule, type ProjectStateOutput } from "./projectState/decide";
import {
  PROJECT_BROWSER_REMOTE_READ_MAX_BYTES,
  PROJECT_BROWSER_REMOTE_READ_MAX_LINES,
  PROJECT_REMOTE_CHECKED_OPERATIONS,
  type RemoteRefusal,
} from "./projectState/remoteAccessPolicy";
import {
  isProjectFileMutationOperation,
  projectFileMutationDigest,
  validateProjectFileMutation,
} from "../utils/projectFileMutationProtocol";
import { createProjectIgnoredReadGrant } from "../utils/projectIgnoredReadGrant";
import {
  ProjectRemoteAccessReplayGuard,
  createProjectRemoteAccessHandshake,
  deriveProjectRemoteAccessSessionKey,
  openProjectRemoteAccessEnvelope,
  type ProjectRemoteAccessCryptoIdentity,
  type ProjectRemoteAccessEnvelope,
  type ProjectRemoteAccessHandshake,
} from "./projectRemoteAccessCrypto";

export type ProjectItemType = "embed" | "chat" | "upload" | "workflow";

export interface EncryptedProjectRecord {
  id?: string;
  project_id: string;
  encrypted_project_key: string;
  key_wrappers?: Array<{ key_type: string; encrypted_project_key: string; hashed_team_id?: string }>;
  encrypted_name: string;
  encrypted_description?: string | null;
  encrypted_icon?: string | null;
  encrypted_color?: string | null;
  pinned?: boolean;
  archived?: boolean;
  is_private?: boolean;
  is_shared?: boolean;
  created_at: number;
  updated_at: number;
  last_opened_at: number;
  item_count?: number;
  version?: number;
}

export interface ProjectFolderRecord {
  folder_id: string;
  hashed_project_id: string;
  hashed_parent_folder_id?: string | null;
  encrypted_name: string;
  created_at: number;
  updated_at: number;
  position: number;
}

export interface ProjectItemRecord {
  hashed_folder_id?: string | null;
  project_item_id: string;
  item_type: ProjectItemType;
  target_id_hash: string;
  target_id_encrypted: string;
  encrypted_display_name?: string | null;
  encrypted_note?: string | null;
  encrypted_metadata?: string | null;
  created_at: number;
  updated_at: number;
  position: number;
}

export interface ProjectFolderViewModel {
  folder_id: string;
  name: string;
  parentHash: string | null;
  encrypted: ProjectFolderRecord;
}

export interface ProjectItemViewModel {
  project_item_id: string;
  item_type: ProjectItemType;
  target_id: string;
  displayName: string;
  metadata: Record<string, unknown>;
  encrypted: ProjectItemRecord;
}

export interface ProjectSourceRecord extends ProjectSourceCreatePayload {
  id?: string;
  source_session_id?: string | null;
  key_epoch?: number | null;
}

export interface ProjectSettingsRecord {
  auto_selection?: boolean;
  focus_activation_policy?: ProjectFocusActivationPolicy;
  write_mode?: ProjectWriteMode | null;
  selection_required?: boolean;
  default_focus_id_hash?: string | null;
  encrypted_settings?: string | null;
  updated_at?: number | null;
}

export interface ProjectSettingsViewModel {
  autoSelection: boolean;
  focusActivationPolicy: ProjectFocusActivationPolicy;
  writeMode: ProjectWriteMode | null;
  selectionRequired: boolean;
  settings: Record<string, unknown>;
  encrypted: ProjectSettingsRecord;
}

export type ProjectFocusActivationPolicy = "delayed" | "immediate" | "approval";

export interface ProjectSourceViewModel {
  source_id: string;
  source_type: ProjectSourceType;
  displayName: string;
  metadata: Record<string, unknown>;
  capabilities: ProjectSourceCapability[];
  status: ProjectSourceStatus;
  sourceSessionId: string | null;
  keyEpoch: number | null;
  encrypted: ProjectSourceRecord;
}

export type ProjectRemoteAccessOperation = ProjectRemoteSourceOperation;

export interface ProjectApiContext {
  teamId?: string | null;
}

function assertCurrentProjectContext(teamId: string | null | undefined): void {
  if ((teamId ?? null) !== getActiveTeamContextSnapshot().teamId) throw new WorkspaceCacheDiscardedError();
}

export interface ActiveProjectFocus {
  active: true;
  project_id: string;
  focus_id: string;
  specialist_focus_id?: string | null;
  team_id: string | null;
  activated_at: number;
}

export interface ProjectWriteApprovalResult {
  approved: true;
  operation_id: string;
  proposal_digest: string;
  approved_at: number;
}

export class ProjectRemoteAccessError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ProjectRemoteAccessError";
    this.code = code;
  }
}

export interface ProjectRemoteDirectoryEntry {
  path: string;
  kind: "file" | "directory";
  previewable?: false;
  sizeBytes?: number;
  children?: Array<{ path: string; kind: "file" | "directory" }>;
  childFileCount?: number;
  childFolderCount?: number;
  childFileSizeBytes?: number;
  childSummaryTruncated?: boolean;
}

export interface ProjectRemoteDirectoryResult {
  entries: ProjectRemoteDirectoryEntry[];
  omitted: number;
  excluded: number;
  nextCursor?: string;
}

export interface ProjectRemoteSearchMatch {
  path: string;
  kind?: "file" | "directory";
  line?: number;
  snippet?: string;
}

export interface ProjectRemoteSearchResult {
  matches: ProjectRemoteSearchMatch[];
  omitted: number;
  excluded: number;
}

export interface ProjectRemoteTextResult {
  content: string;
  truncated: boolean;
  sizeBytes: number;
  lineCount: number;
  expectedBase: string | null;
}

export interface ProjectRemoteImageChunkResult {
  content_base64: string;
  mime_type: "image/png" | "image/jpeg" | "image/gif" | "image/webp" | "image/avif";
  size_bytes: number;
  offset: number;
  content_hash: string;
}

export interface ProjectRemoteFileChunkResult {
  content_base64: string;
  size_bytes: number;
  offset: number;
  file_identity: string;
  chunk_hash: string;
}

export type ProjectRemoteTransferOperation = "copy_entries" | "move_entries";

export interface ProjectRemoteTransferResult {
  operation: ProjectRemoteTransferOperation;
  destination_path: string;
  completed: string[];
  failed: Array<{ path: string; code: string }>;
}

export interface ProjectRemoteAccessContext {
  ownerId: string;
  teamId?: string | null;
}

export interface ProjectSourceCreateInput {
  sourceId?: string;
  sourceType: ProjectSourceType;
  displayName: string;
  metadata?: Record<string, unknown>;
  capabilities?: string[];
  status?: ProjectSourceStatus;
}

export interface ProjectUploadMetadata {
  source_id?: string;
  remote_path?: string;
  remote_base_hash?: string;
  remote_content_hash?: string;
  remote_mtime?: string;
  remote_git_status?: string;
  safety_flags?: string[];
  imported_from_remote_source?: boolean;
}

export interface ProjectUploadLocation {
  folderId?: string | null;
}

export interface ProjectViewModel {
  project_id: string;
  /** Team whose matching wrapper decrypted this Project; captured with the key. */
  teamId?: string | null;
  name: string;
  description: string;
  icon: string;
  projectKey: Uint8Array;
  encrypted: EncryptedProjectRecord;
}

const REMOTE_ACCESS_POLL_INTERVAL_MS = 250;
const REMOTE_ACCESS_TIMEOUT_MS = 45_000;
// The source trims escaped JSON against the exact 200KiB encrypted-envelope
// budget. This leaves headroom for ordinary text result metadata.
export { PROJECT_BROWSER_REMOTE_READ_MAX_BYTES, PROJECT_BROWSER_REMOTE_READ_MAX_LINES };

interface ProjectRemoteRoutingIdentity {
  context_type: "team";
  context_id_hash: string;
  host_member_hash: string;
  host_device_fingerprint_hash: string;
  requester_member_hash: string;
  requester_device_fingerprint_hash: string;
}

interface ProjectRemoteRequestCreated {
  request_id: string;
  status: "delivered" | "queued";
  source_session_id?: string;
  key_epoch?: number;
  routing_identity?: ProjectRemoteRoutingIdentity;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await storageArchiveFetch(getApiEndpoint(path), {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Projects API failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as T;
}

function generateProjectKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key)) ?? "";
}

export async function decryptProject(record: EncryptedProjectRecord, teamId = getActiveTeamContextSnapshot().teamId): Promise<ProjectViewModel | null> {
  const teamHash = teamId ? await computeSHA256(teamId) : null;
  const wrapperInput = {
    teamId: teamId ?? null, teamHash, encryptedProjectKey: record.encrypted_project_key, keyWrappers: record.key_wrappers,
  };
  const selected = PROJECT_RUST_CORE
    ? await decideProject("projectWrapperSelect", wrapperInput) : projectRule("projectWrapperSelect", wrapperInput);
  if (selected.mode === "none") return null;
  const projectKey = selected.mode === "team" && teamId
    ? await unwrapEmbedKeyWithEmbedKey(selected.wrapper, await getTeamKey(teamId))
    : selected.mode === "master" ? await decryptChatKeyWithMasterKey(selected.encryptedProjectKey) : null;
  if (!projectKey) return null;
  return {
    project_id: record.project_id,
    teamId: selected.mode === "team" && teamId ? teamId : null,
    name: await decryptOptional(record.encrypted_name, projectKey),
    description: await decryptOptional(record.encrypted_description, projectKey),
    icon: await decryptOptional(record.encrypted_icon, projectKey),
    projectKey,
    encrypted: record,
  };
}

const projectListCache = new WorkspaceQueryCache<ProjectViewModel[]>();
const projectEntityCache = new WorkspaceQueryCache<ProjectViewModel>();

function projectListKey(teamId: string | null | undefined): string {
  return JSON.stringify(['list', teamId ?? null]);
}

function activeProjectListKey(): string {
  return projectListKey(getActiveTeamContextSnapshot().teamId);
}

function projectEntityKey(projectId: string, context: ProjectApiContext = {}): string {
  return JSON.stringify([context.teamId ?? null, projectId]);
}

export function peekProjects(): ProjectViewModel[] | undefined { return projectListCache.peek(activeProjectListKey()); }
export function subscribeProjects(listener: () => void): () => void { return projectListCache.subscribe(listener); }
export function getProjectsRefreshError(): unknown { return projectListCache.getError(activeProjectListKey()); }

function projectsAreDisabled(): boolean {
  const availability = get(featureAvailabilityStore);
  return availability.initialized && availability.disabledById?.["platform:projects"] === true;
}

export async function listProjects(options: { force?: boolean; teamId?: string | null; freshRequest?: boolean } = {}): Promise<ProjectViewModel[]> {
  if (projectsAreDisabled()) return [];
  const teamId = 'teamId' in options ? options.teamId : getActiveTeamContextSnapshot().teamId;
  return projectListCache.load(projectListKey(teamId), async () => {
    const data = await requestJson<{ projects: EncryptedProjectRecord[] }>(withProjectRemoteQuery("/v1/projects", { team_id: teamId }));
    const decrypted = await Promise.all(data.projects.map((record) => decryptProject(record, teamId)));
    return decrypted.filter((project): project is ProjectViewModel => project !== null);
  }, options);
}

/** A click starts a new owner-scoped request even if an older refresh is pending. */
export async function listFreshProjectsForSend(): Promise<{ projects: ProjectViewModel[]; mutationVersion: number }> {
  const mutationVersion = projectListCache.getMutationVersion();
  const projects = await listProjects({ teamId: null, force: true, freshRequest: true });
  if (projectListCache.getMutationVersion() !== mutationVersion) throw new WorkspaceCacheDiscardedError();
  return { projects, mutationVersion };
}

export function getProjectsMutationVersion(): number { return projectListCache.getMutationVersion(); }

export async function getProject(projectId: string, context: ProjectApiContext = {}): Promise<ProjectViewModel> {
  const teamId = 'teamId' in context ? context.teamId : getActiveTeamContextSnapshot().teamId;
  const summary = teamId === getActiveTeamContextSnapshot().teamId
    ? peekProjects()?.find((project) => project.project_id === projectId) : undefined;
  if (summary && projectListCache.isFresh(projectListKey(teamId))) return summary;
  return projectEntityCache.load(projectEntityKey(projectId, { teamId }), async () => {
    const data = await requestJson<{ project: EncryptedProjectRecord }>(
      withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(projectId)}`, { team_id: teamId }),
    );
    const project = await decryptProject(data.project, teamId);
    if (!project) throw new Error("Project could not be decrypted");
    return project;
  });
}

function publishMergeInput(project: ProjectViewModel, isNew: boolean) {
  const cached = peekProjects();
  const current = projectEntityCache.peek(projectEntityKey(project.project_id, { teamId: project.teamId }))
    ?? cached?.find((item) => item.project_id === project.project_id);
  return {
    cached, current,
    input: {
      projectId: project.project_id, incomingVersion: project.encrypted.version ?? null,
      current: current ? { version: current.encrypted.version ?? null } : null,
      cachedIds: cached ? cached.map((item) => item.project_id) : null, isNew,
    },
  };
}

function applyPublishMerge(
  project: ProjectViewModel, cached: ProjectViewModel[] | undefined, current: ProjectViewModel | undefined,
  merge: ProjectStateOutput<"projectPublishMerge">,
): ProjectViewModel {
  if (merge.keepCurrent && current) return current;
  // Fence a concurrent list read even when no list has been loaded yet.
  if (!merge.keepCurrent && merge.list !== "invalidate" && cached) {
    projectListCache.set(activeProjectListKey(), merge.list === "replace"
      ? cached.map((item) => item.project_id === project.project_id ? project : item)
      : merge.list === "prepend" ? [project, ...cached] : cached);
  } else projectListCache.invalidate();
  projectEntityCache.set(projectEntityKey(project.project_id, { teamId: project.teamId }), project);
  return project;
}

/** Synchronous flag-off publish (the original TypeScript merge rule). */
function publishProjectSync(project: ProjectViewModel, isNew = false): ProjectViewModel {
  const { cached, current, input } = publishMergeInput(project, isNew);
  return applyPublishMerge(project, cached, current, projectRule("projectPublishMerge", input));
}

/** Flag-on publish: the shared Rust core decides the merge (callers use publishProjectSync flag-off). */
async function publishProjectRust(project: ProjectViewModel, isNew = false): Promise<ProjectViewModel> {
  const identity = getWorkspaceCacheIdentity();
  const { input } = publishMergeInput(project, isNew);
  const merge = await decideProject("projectPublishMerge", input);
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  // Re-read the caches after the decision so the merge applies to their current values.
  const fresh = publishMergeInput(project, isNew);
  return applyPublishMerge(project, fresh.cached, fresh.current, merge);
}

// File/source events do not change summaries. Metadata mutations publish their
// authoritative response above; a generic external change refreshes summaries.
if (typeof window !== 'undefined') {
  window.addEventListener(PROJECTS_CHANGED_EVENT, (event) => {
    if (!(event as CustomEvent<{ projectId?: string }>).detail?.projectId) {
      projectListCache.invalidate();
      projectEntityCache.invalidate();
    }
  });
}

export async function updateProjectMetadata(
  project: ProjectViewModel,
  patch: { name?: string; description?: string },
): Promise<ProjectViewModel> {
  assertCurrentProjectContext(project.teamId);
  const identity = getWorkspaceCacheIdentity();
  const patchInput = {
    version: project.encrypted.version ?? null, name: patch.name !== undefined, description: patch.description !== undefined,
  };
  const plan = PROJECT_RUST_CORE
    ? await decideProject("projectMetadataPatch", patchInput) : projectRule("projectMetadataPatch", patchInput);
  const body: Record<string, unknown> = {
    version: plan.version,
  };
  if (plan.encryptName && patch.name !== undefined) body.encrypted_name = await encryptWithEmbedKey(patch.name, project.projectKey);
  if (plan.encryptDescription && patch.description !== undefined) body.encrypted_description = await encryptWithEmbedKey(patch.description, project.projectKey);
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  const data = await requestJson<{ project: EncryptedProjectRecord }>(withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(project.project_id)}`, { team_id: project.teamId }), {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  const updated = await decryptProject(data.project, project.teamId);
  if (!updated) throw new Error("Updated project could not be decrypted");
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  return PROJECT_RUST_CORE ? publishProjectRust(updated) : publishProjectSync(updated);
}

export async function createProject(name: string, writeMode: ProjectWriteMode | null, context: ProjectApiContext = {}): Promise<ProjectViewModel> {
  const identity = getWorkspaceCacheIdentity();
  const teamId = 'teamId' in context ? context.teamId : getActiveTeamContextSnapshot().teamId;
  const projectKey = generateProjectKey();
  const encryptedProjectKey = await encryptChatKeyWithMasterKey(projectKey);
  if (!encryptedProjectKey) throw new Error("Could not wrap project key with master key");
  const timestamp = nowSeconds();
  const projectId = crypto.randomUUID();
  const planInput = { name, writeMode, focusId: crypto.randomUUID(), timestamp };
  const plan = PROJECT_RUST_CORE ? await decideProject("projectCreatePlan", planInput) : projectRule("projectCreatePlan", planInput);
  const teamWrapper = teamId ? {
    key_type: 'team', hashed_team_id: await computeSHA256(teamId), team_key_epoch: plan.teamKeyEpoch,
    encrypted_project_key: await wrapEmbedKeyWithChatKey(projectKey, await getTeamKey(teamId)),
  } : null;
  const body = {
    project_id: projectId,
    encrypted_project_key: encryptedProjectKey,
    ...(teamWrapper ? { key_wrappers: [teamWrapper] } : {}),
    encrypted_name: await encryptWithEmbedKey(plan.plaintext.name, projectKey),
    encrypted_description: await encryptWithEmbedKey(plan.plaintext.description, projectKey),
    encrypted_icon: await encryptWithEmbedKey(plan.plaintext.icon, projectKey),
    encrypted_color: await encryptWithEmbedKey(plan.plaintext.color, projectKey),
    pinned: plan.fields.pinned,
    created_at: plan.fields.created_at,
    updated_at: plan.fields.updated_at,
    last_opened_at: plan.fields.last_opened_at,
    write_mode: plan.fields.write_mode,
    ...(plan.fields.chat_organization_only ? { chat_organization_only: true } : {}),
    default_focus_id: plan.fields.default_focus_id,
    encrypted_settings: await encryptWithEmbedKey(plan.plaintext.settings, projectKey),
  };
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  const data = await requestJson<{ project: EncryptedProjectRecord }>(withProjectRemoteQuery("/v1/projects", { team_id: teamId }), {
    method: "POST",
    body: JSON.stringify(body),
  });
  const created = (
    (await decryptProject(data.project, teamId)) ?? {
      project_id: projectId,
      teamId: teamId ?? null,
      name,
      description: "",
      icon: "folder",
      projectKey,
      encrypted: data.project,
    }
  );
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  return PROJECT_RUST_CORE ? publishProjectRust(created, true) : publishProjectSync(created, true);
}

export async function listProjectSources(project: ProjectViewModel, context: ProjectApiContext = {}): Promise<ProjectSourceViewModel[]> {
  const data = await requestJson<{ sources: ProjectSourceRecord[] }>(
    withProjectRemoteQuery(`/v1/projects/${project.project_id}/sources`, {
      team_id: context.teamId ?? project.teamId,
    }),
  );
  return Promise.all(data.sources.map((source) => decryptProjectSource(source, project.projectKey)));
}

export async function createProjectSource(project: ProjectViewModel, input: ProjectSourceCreateInput): Promise<ProjectSourceViewModel> {
  assertCurrentProjectContext(project.teamId);
  const timestamp = nowSeconds();
  const metadata = JSON.stringify(input.metadata ?? {});
  const payloadInput = {
    sourceId: input.sourceId ?? crypto.randomUUID(),
    sourceType: input.sourceType,
    encryptedDisplayName: await encryptWithEmbedKey(input.displayName, project.projectKey),
    encryptedMetadata: await encryptWithEmbedKey(metadata, project.projectKey),
    capabilities: input.capabilities,
    status: input.status,
    timestamp,
  };
  const payload = PROJECT_RUST_CORE ? await sourcePayloadRust(payloadInput) : buildProjectSourceCreatePayload(payloadInput);
  const data = await requestJson<{ source: ProjectSourceRecord }>(withProjectRemoteQuery(`/v1/projects/${project.project_id}/sources`, { team_id: project.teamId }), {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return decryptProjectSource(data.source, project.projectKey);
}

/** Flag-on source create body: Rust filters and defaults, the page keeps the wire key order. */
async function sourcePayloadRust(input: Parameters<typeof buildProjectSourceCreatePayload>[0]) {
  const answer = await decideProject("projectSourceCreate", input) as Record<string, unknown>;
  return {
    source_id: answer.source_id,
    source_type: answer.source_type,
    encrypted_display_name: answer.encrypted_display_name,
    encrypted_metadata: answer.encrypted_metadata,
    capabilities: answer.capabilities,
    status: answer.status,
    created_at: answer.created_at,
    updated_at: answer.updated_at,
    ...("last_indexed_at" in answer ? { last_indexed_at: answer.last_indexed_at } : {}),
  };
}

export async function requestProjectRemoteAccess<T>(
  project: ProjectViewModel,
  source: ProjectSourceViewModel,
  context: ProjectRemoteAccessContext,
  operation: ProjectRemoteAccessOperation,
  args: Record<string, unknown>,
  signal?: AbortSignal,
  approvedIgnoredRead?: { path: string; chatId: string; operationId: string },
): Promise<T> {
  const requestContext: Readonly<ProjectRemoteAccessContext> = {
    ownerId: context.ownerId,
    teamId: context.teamId ?? null,
  };
  const preflightInput = {
    status: source.status, capabilities: source.capabilities, operation, hasOwner: Boolean(requestContext.ownerId),
    // Only the argument fields the preflight reads cross into Rust.
    args: { include_content: args.include_content, user_initiated: args.user_initiated },
  };
  const preflight = remoteAnswer(PROJECT_RUST_CORE
    ? await decideProject("projectRemotePreflight", preflightInput) : projectRule("projectRemotePreflight", preflightInput));
  const isUserFileTransfer = preflight.userFileTransfer;

  let sourceSessionId = source.sourceSessionId;
  let keyEpoch = source.keyEpoch;
  let routingIdentity: ProjectRemoteRoutingIdentity | null = null;
  if (requestContext.teamId) {
    const discovery = await discoverProjectRemoteRouting(project, source, requestContext, signal);
    sourceSessionId = discovery.sourceSessionId;
    keyEpoch = discovery.keyEpoch;
    routingIdentity = discovery.routingIdentity;
  }
  if (!sourceSessionId || !keyEpoch) throw new ProjectRemoteAccessError("source_offline", "This Project source is offline");

  const requestId = crypto.randomUUID();
  const requestingClientId = crypto.randomUUID();
  let ignoredReadGrant: Awaited<ReturnType<typeof createProjectIgnoredReadGrant>> | undefined;
  if (approvedIgnoredRead) {
    const ignoredInput = { operation, path: args.path, approved: approvedIgnoredRead };
    if (PROJECT_RUST_CORE) await decideProject("projectIgnoredRead", ignoredInput);
    else projectRule("projectIgnoredRead", ignoredInput);
    ignoredReadGrant = await createProjectIgnoredReadGrant(project.projectKey, {
      projectId: project.project_id,
      sourceId: source.source_id,
      requestId,
      chatId: approvedIgnoredRead.chatId,
      operationId: approvedIgnoredRead.operationId,
      path: approvedIgnoredRead.path,
    });
  }
  let writeContext: { chat_id: string; operation_id: string; proposal_digest: string } | undefined;
  if (isProjectFileMutationOperation(operation)) {
    const chatId = args.chat_id;
    const mutation = validateProjectFileMutation(args.mutation);
    if (typeof chatId !== "string" || !chatId || mutation.operation !== operation) {
      throw new Error("A Project write requires the originating chat and an exact proposal");
    }
    writeContext = {
      chat_id: chatId,
      operation_id: mutation.operation_id,
      proposal_digest: await projectFileMutationDigest(project.projectKey, project.project_id, chatId, mutation),
    };
  }
  const identity: ProjectRemoteAccessCryptoIdentity = routingIdentity
    ? {
        ownerId: routingIdentity.context_id_hash,
        contextType: "team",
        contextId: routingIdentity.context_id_hash,
        projectId: project.project_id,
        sourceId: source.source_id,
        sourceSessionId,
        requestingClientId,
        hostMemberId: routingIdentity.host_member_hash,
        hostDeviceId: routingIdentity.host_device_fingerprint_hash,
        requesterMemberId: routingIdentity.requester_member_hash,
        requesterDeviceId: routingIdentity.requester_device_fingerprint_hash,
        keyEpoch,
      }
    : {
        ownerId: requestContext.ownerId,
        projectId: project.project_id,
        sourceId: source.source_id,
        sourceSessionId,
        requestingClientId,
        keyEpoch,
      };
  const requester = await createProjectRemoteAccessHandshake(project.projectKey, identity, "requester");
  const operationArguments = preflight.readLimits
    ? {
        ...args,
        max_bytes: preflight.readLimits.max_bytes,
        max_lines: preflight.readLimits.max_lines,
      }
    : args;
  const encryptedEnvelope = await encryptWithEmbedKey(
    JSON.stringify({
      requesting_client_id: requestingClientId,
      requester_handshake: requester.handshake,
      operation,
      arguments: operationArguments,
      ...(ignoredReadGrant && approvedIgnoredRead
        ? {
            ignored_read_grant: ignoredReadGrant,
            ignored_read_context: {
              chatId: approvedIgnoredRead.chatId,
              operationId: approvedIgnoredRead.operationId,
            },
          }
        : {}),
    }),
    project.projectKey,
  );
  const created = await requestRemoteJson<ProjectRemoteRequestCreated>(
    projectRemoteRequestPath(project.project_id, source.source_id, requestContext.teamId),
    {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId,
        requesting_client_id: requestingClientId,
        operation,
        key_epoch: keyEpoch,
        encrypted_envelope: encryptedEnvelope,
        ...writeContext,
        ...(isUserFileTransfer ? { user_initiated: true } : {}),
      }),
      signal,
    },
  );
  const createdInput = {
    created: { source_session_id: created.source_session_id, key_epoch: created.key_epoch }, sourceSessionId, keyEpoch,
  };
  remoteAnswer(PROJECT_RUST_CORE
    ? await decideProject("projectRemoteCreated", createdInput) : projectRule("projectRemoteCreated", createdInput));

  const result = await pollProjectRemoteResult(
    project.project_id,
    source.source_id,
    requestId,
    requestingClientId,
    requestContext.teamId,
    signal,
  );
  throwIfRemoteAccessAborted(signal);
  const opened = await openProjectRemoteAccessResult<unknown>(
    result.encrypted_envelope,
    project.projectKey,
    identity,
    requestId,
    requester.privateKey,
    requester.handshake,
  );
  throwIfRemoteAccessAborted(signal);
  if (!PROJECT_REMOTE_CHECKED_OPERATIONS.includes(operation)) return opened as T;
  const normalizeInput = { operation, value: opened };
  const normalized = PROJECT_RUST_CORE
    ? await decideProject("projectRemoteNormalize", normalizeInput) : projectRule("projectRemoteNormalize", normalizeInput);
  if (PROJECT_RUST_CORE) throwIfRemoteAccessAborted(signal);
  return normalized.result as T;
}

/** The answer of a remote-access rule, or its refusal rethrown as the typed error. */
function remoteAnswer<A extends object>(answer: A | RemoteRefusal): A {
  if ("remoteError" in answer) throw remoteRefusalError(answer as RemoteRefusal);
  return answer as A;
}

/** Execute a user-confirmed copy or move entirely on the connected source host. */
export async function transferProjectRemoteEntries(
  project: ProjectViewModel,
  source: ProjectSourceViewModel,
  context: ProjectRemoteAccessContext,
  input: { operation: ProjectRemoteTransferOperation; paths: string[]; destinationPath: string },
  signal?: AbortSignal,
): Promise<ProjectRemoteTransferResult> {
  const transferInput = { paths: input.paths, destinationPath: input.destinationPath };
  remoteAnswer(PROJECT_RUST_CORE
    ? await decideProject("projectRemoteTransfer", transferInput) : projectRule("projectRemoteTransfer", transferInput));
  return requestProjectRemoteAccess<ProjectRemoteTransferResult>(project, source, context, input.operation, {
    paths: input.paths,
    destination_path: input.destinationPath,
    user_initiated: true,
  }, signal);
}

async function discoverProjectRemoteRouting(
  project: ProjectViewModel,
  source: ProjectSourceViewModel,
  context: ProjectRemoteAccessContext,
  signal?: AbortSignal,
): Promise<{
  sourceSessionId: string;
  keyEpoch: number;
  routingIdentity: ProjectRemoteRoutingIdentity;
}> {
  const requestId = crypto.randomUUID();
  const requestingClientId = crypto.randomUUID();
  const nonce = crypto.randomUUID();
  const encryptedEnvelope = await encryptWithEmbedKey(
    JSON.stringify({
      type: "routing_discovery",
      requesting_client_id: requestingClientId,
      nonce,
    }),
    project.projectKey,
  );
  const created = await requestRemoteJson<ProjectRemoteRequestCreated>(
    projectRemoteRequestPath(project.project_id, source.source_id, context.teamId),
    {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId,
        requesting_client_id: requestingClientId,
        operation: "list",
        key_epoch: 1,
        encrypted_envelope: encryptedEnvelope,
      }),
      signal,
    },
  );
  const routingIdentity = created.routing_identity;
  const routingInput = {
    created: {
      source_session_id: created.source_session_id, key_epoch: created.key_epoch,
      routing_identity: routingIdentity ? { context_type: routingIdentity.context_type } : undefined,
    },
  };
  remoteAnswer(PROJECT_RUST_CORE
    ? await decideProject("projectRoutingCreated", routingInput) : projectRule("projectRoutingCreated", routingInput));
  const result = await pollProjectRemoteResult(project.project_id, source.source_id, requestId, requestingClientId, context.teamId, signal);
  const discoveryText = await decryptWithEmbedKey(result.encrypted_envelope, project.projectKey);
  throwIfRemoteAccessAborted(signal);
  const discoveryInput = { discovery: discoveryText, nonce };
  remoteAnswer(PROJECT_RUST_CORE
    ? await decideProject("projectRoutingResult", discoveryInput) : projectRule("projectRoutingResult", discoveryInput));
  return {
    sourceSessionId: created.source_session_id as string,
    keyEpoch: created.key_epoch as number,
    routingIdentity: routingIdentity as ProjectRemoteRoutingIdentity,
  };
}

async function pollProjectRemoteResult(
  projectId: string,
  sourceId: string,
  requestId: string,
  requestingClientId: string,
  teamId?: string | null,
  signal?: AbortSignal,
): Promise<{ encrypted_envelope: string }> {
  const deadline = Date.now() + REMOTE_ACCESS_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (signal?.aborted) throw remoteAccessAbortError();
    const basePath = `/v1/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/requests/${encodeURIComponent(requestId)}`;
    const path = withProjectRemoteQuery(basePath, {
      requesting_client_id: requestingClientId,
      team_id: teamId,
    });
    let response: Response;
    try {
      response = await storageArchiveFetch(getApiEndpoint(path), {
        credentials: "include",
        signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new ProjectRemoteAccessError("source_offline", "The Project source request could not be sent");
    }
    if (response.ok) {
      try {
        const result = (await response.json()) as {
          encrypted_envelope?: unknown;
        };
        if (typeof result.encrypted_envelope !== "string" || !result.encrypted_envelope) throw new Error();
        return { encrypted_envelope: result.encrypted_envelope };
      } catch {
        throw new ProjectRemoteAccessError("invalid_remote_payload", "The Project source returned an invalid response");
      }
    }
    if (response.status !== 404) {
      const httpInput = { status: response.status };
      throw remoteRefusalError(PROJECT_RUST_CORE
        ? await decideProject("projectRemoteHttpError", httpInput) : projectRule("projectRemoteHttpError", httpInput));
    }
    await waitForRemoteAccessPoll(signal);
  }
  throw new ProjectRemoteAccessError("protocol_timeout", "Remote access request timed out");
}

async function openProjectRemoteAccessResult<T>(
  encryptedEnvelope: string,
  projectKey: Uint8Array,
  identity: ProjectRemoteAccessCryptoIdentity,
  requestId: string,
  requesterPrivateKey: string,
  requesterHandshake: ProjectRemoteAccessHandshake,
): Promise<T> {
  let payload: {
    source_handshake: ProjectRemoteAccessHandshake;
    envelope: ProjectRemoteAccessEnvelope;
  };
  try {
    payload = JSON.parse(encryptedEnvelope) as typeof payload;
  } catch {
    throw new Error("Remote access result envelope is invalid");
  }
  const sessionKey = await deriveProjectRemoteAccessSessionKey(
    projectKey,
    identity,
    "requester",
    requesterPrivateKey,
    requesterHandshake,
    payload.source_handshake,
  );
  const plaintext = await openProjectRemoteAccessEnvelope(
    sessionKey,
    identity,
    requestId,
    "result",
    payload.envelope,
    new ProjectRemoteAccessReplayGuard(),
  );
  const responseInput = { plaintext: new TextDecoder("utf-8", { fatal: true }).decode(plaintext) };
  const response = remoteAnswer(PROJECT_RUST_CORE
    ? await decideProject("projectRemoteResponse", responseInput) : projectRule("projectRemoteResponse", responseInput));
  return response.result as T;
}

function waitForRemoteAccessPoll(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(remoteAccessAbortError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, REMOTE_ACCESS_POLL_INTERVAL_MS);
    if (signal?.aborted) {
      clearTimeout(timer);
      reject(remoteAccessAbortError());
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function remoteAccessAbortError(): DOMException {
  return new DOMException("Remote access request aborted", "AbortError");
}

function throwIfRemoteAccessAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw remoteAccessAbortError();
}

function projectRemoteRequestPath(projectId: string, sourceId: string, teamId?: string | null): string {
  return withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/requests`, {
    team_id: teamId,
  });
}

function withProjectRemoteQuery(path: string, values: Record<string, string | null | undefined>): string {
  const url = new URL(path, "https://openmates.invalid");
  for (const [key, value] of Object.entries(values)) {
    if (value) url.searchParams.set(key, value);
  }
  return `${url.pathname}${url.search}`;
}

async function requestRemoteJson<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await storageArchiveFetch(getApiEndpoint(path), {
      credentials: "include",
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ProjectRemoteAccessError("source_offline", "The Project source request could not be sent");
  }
  if (!response.ok) {
    // A 409 body may carry the device-binding detail the status mapping checks.
    const body = response.status === 409
      ? await response.json().catch(() => null) as { detail?: unknown } | null
      : null;
    const httpInput = { status: response.status, detail: body?.detail };
    throw remoteRefusalError(PROJECT_RUST_CORE
      ? await decideProject("projectRemoteHttpError", httpInput) : projectRule("projectRemoteHttpError", httpInput));
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ProjectRemoteAccessError("invalid_remote_payload", "The Project source returned an invalid response");
  }
}

function remoteRefusalError(refusal: RemoteRefusal): ProjectRemoteAccessError {
  return new ProjectRemoteAccessError(refusal.remoteError.code, refusal.remoteError.message);
}


export async function getProjectSettings(project: ProjectViewModel, context: ProjectApiContext = {}): Promise<ProjectSettingsViewModel> {
  const data = await requestJson<{ settings: ProjectSettingsRecord }>(
    withProjectRemoteQuery(`/v1/projects/${project.project_id}/settings`, {
      team_id: context.teamId ?? project.teamId,
    }),
  );
  const initInput = {
    settings: { encrypted_settings: data.settings.encrypted_settings, write_mode: data.settings.write_mode },
    // A focus id is drawn only when the settings still need their default focus.
    projectName: project.name, focusId: data.settings.encrypted_settings ? "" : crypto.randomUUID(), timestamp: nowSeconds(),
  };
  const init = PROJECT_RUST_CORE ? await decideProject("projectSettingsInit", initInput) : projectRule("projectSettingsInit", initInput);
  if (init.init) {
    const initialized = await requestJson<{ settings: ProjectSettingsRecord }>(
      withProjectRemoteQuery(`/v1/projects/${project.project_id}/settings`, {
        team_id: context.teamId ?? project.teamId,
      }),
      {
        method: "PATCH",
        body: JSON.stringify({
          write_mode: init.writeMode,
          default_focus_id: init.defaultFocusId,
          encrypted_settings: await encryptWithEmbedKey(init.settingsPlaintext, project.projectKey),
          updated_at: init.updatedAt,
        }),
      },
    );
    return decryptProjectSettings(initialized.settings, project.projectKey);
  }
  return decryptProjectSettings(data.settings, project.projectKey);
}

export async function updateProjectSettings(
  project: ProjectViewModel,
  writeMode: ProjectWriteMode | null,
  context: ProjectApiContext = {},
  autoSelection?: boolean,
  focusActivationPolicy?: ProjectFocusActivationPolicy,
): Promise<ProjectSettingsViewModel> {
  const patchInput = { writeMode, autoSelection, focusActivationPolicy, timestamp: nowSeconds() };
  const data = await requestJson<{ settings: ProjectSettingsRecord }>(
    withProjectRemoteQuery(`/v1/projects/${project.project_id}/settings`, {
      team_id: context.teamId ?? project.teamId,
    }),
    {
      method: "PATCH",
      body: JSON.stringify(PROJECT_RUST_CORE ? await settingsPatchRust() : projectRule("projectSettingsPatch", patchInput)),
    },
  );
  return decryptProjectSettings(data.settings, project.projectKey);

  async function settingsPatchRust() {
    // Rust answers a key-sorted object; rebuild the wire body in its original key order.
    const answer = await decideProject("projectSettingsPatch", patchInput) as Record<string, unknown>;
    return {
      ...("write_mode" in answer ? { write_mode: answer.write_mode } : {}),
      ...("auto_selection" in answer ? { auto_selection: answer.auto_selection } : {}),
      ...("focus_activation_policy" in answer ? { focus_activation_policy: answer.focus_activation_policy } : {}),
      updated_at: answer.updated_at,
    };
  }
}

export async function confirmProjectFocusCountdown(
  projectId: string, input: { chat_id: string; activation_request_id: string; approved?: boolean }, context: ProjectApiContext = {},
): Promise<void> {
  await requestJson(withProjectRemoteQuery(`/v1/projects/${projectId}/focus/countdown`, { team_id: context.teamId }), {
    method: "POST", body: JSON.stringify(input),
  });
}

export async function activateProjectFocus(
  projectId: string,
  input: { chat_id: string; focus_id: string; instruction: string; activation_request_id?: string },
  context: ProjectApiContext = {},
): Promise<ActiveProjectFocus> {
  const data = await requestJson<{ focus: ActiveProjectFocus }>(
    withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(projectId)}/focus/activate`, { team_id: context.teamId }),
    { method: "POST", body: JSON.stringify(input) },
  );
  if (!data.focus?.active) throw new Error("Project focus activation returned an invalid response");
  return data.focus;
}

export async function getActiveProjectFocus(chatId: string): Promise<ActiveProjectFocus | null> {
  if (projectsAreDisabled()) return null;
  const data = await requestJson<{ focus: ActiveProjectFocus | null }>(`/v1/projects/focus/current?chat_id=${encodeURIComponent(chatId)}`);
  return data.focus?.active ? data.focus : null;
}

export async function deactivateProjectFocus(chatId: string): Promise<void> {
  await requestJson<{ deactivated: boolean }>("/v1/projects/focus/deactivate", {
    method: "POST",
    body: JSON.stringify({ chat_id: chatId }),
  });
}

export async function approveProjectWrite(
  projectId: string,
  input: { chat_id: string; operation_id: string; proposal_digest: string },
  context: ProjectApiContext = {},
): Promise<ProjectWriteApprovalResult> {
  const data = await requestJson<{ approval: ProjectWriteApprovalResult }>(
    withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(projectId)}/write-approvals`, {
      team_id: context.teamId,
    }),
    { method: "POST", body: JSON.stringify(input) },
  );
  if (data.approval?.approved !== true) throw new Error("Project write approval returned an invalid response");
  return data.approval;
}

export async function readEncryptedProjectFile(
  project: ProjectViewModel,
  embedId: string,
  context: ProjectApiContext = {},
): Promise<HostedProjectFileHead> {
  const path = withProjectRemoteQuery(`/v1/embeds/${encodeURIComponent(embedId)}/encrypted`, {
    project_id: project.project_id,
    team_id: context.teamId ?? project.teamId,
  });
  const data = await requestJson<{
    embed: Record<string, unknown>;
    embed_keys?: Array<Record<string, unknown>>;
    has_initial_history?: boolean;
  }>(path);
  const headInput = { embedKeys: data.embed_keys ?? null, versionNumber: data.embed?.version_number };
  const head = PROJECT_RUST_CORE ? await decideProject("projectFileHead", headInput) : projectRule("projectFileHead", headInput);
  let embedKey = head.wrapper ? await unwrapEmbedKeyWithEmbedKey(head.wrapper, project.projectKey) : null;
  if (!embedKey) embedKey = await embedStore.getEmbedKey(embedId);
  if (!embedKey || typeof data.embed?.encrypted_content !== "string") {
    throw Object.assign(new Error("Project file key unavailable"), {
      code: "file_key_unavailable",
    });
  }
  const plaintext = await decryptWithEmbedKey(data.embed.encrypted_content, embedKey, {
    embedId,
    fieldName: "encrypted_content",
  });
  if (plaintext === null) {
    throw Object.assign(new Error("Project file decryption failed"), {
      code: "file_decryption_failed",
    });
  }
  const content = await decodeHostedProjectFileContent(plaintext);
  const revision = head.revision;
  if (revision === null) throw new Error("Invalid Project file revision");
  // History uses this same client key. Keep it only in the existing ephemeral
  // cache after current Project authorization and decryption have succeeded.
  embedStore.setEmbedKeyInCache(embedId, embedKey);
  return {
    embedKey,
    content,
    revision,
    hasInitialHistory: data.has_initial_history === true,
  };
}

export async function getProjectFileRevisionReceipt(
  projectId: string,
  embedId: string,
  operationId: string,
  chatId: string,
  proposalDigest: string,
  context: ProjectApiContext = {},
): Promise<Record<string, unknown> | null> {
  const path = withProjectRemoteQuery(`/v1/embeds/${encodeURIComponent(embedId)}/revision-receipts/${encodeURIComponent(operationId)}`, {
    project_id: projectId,
    chat_id: chatId,
    proposal_digest: proposalDigest,
    team_id: context.teamId,
  });
  const response = await storageArchiveFetch(getApiEndpoint(path), {
    credentials: "include",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Projects API failed (${response.status})`);
  const value = (await response.json()) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Project file receipt returned an invalid response");
  return value as Record<string, unknown>;
}

async function decodeHostedProjectFileContent(value: string): Promise<Record<string, unknown>> {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch {
    // Current hosted file heads use TOON; older heads may use JSON.
  }
  try {
    const { decode } = await import("@toon-format/toon");
    const parsed = decode(value, { strict: false }) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch {
    // Stable private error below; never log decrypted file content.
  }
  throw Object.assign(new Error("Project file content is invalid"), {
    code: "unsupported_file_content",
  });
}

export async function deleteProject(projectId: string, context: ProjectApiContext = {}): Promise<void> {
  const identity = getWorkspaceCacheIdentity();
  const confirmation = new URLSearchParams({
    confirmation_project_id: projectId,
  });
  const teamId = 'teamId' in context ? context.teamId : getActiveTeamContextSnapshot().teamId;
  assertCurrentProjectContext(teamId);
  if (teamId) confirmation.set('team_id', teamId);
  await requestJson<{ deleted: boolean }>(`/v1/projects/${projectId}?${confirmation.toString()}`, { method: "DELETE" });
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  const mergeInput = { cachedIds: peekProjects()?.map((project) => project.project_id) ?? null };
  const merge = PROJECT_RUST_CORE ? await decideProject("projectDeleteMerge", mergeInput) : projectRule("projectDeleteMerge", mergeInput);
  if (PROJECT_RUST_CORE && identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  const cached = peekProjects();
  if (merge.list === "filter" && cached) projectListCache.set(activeProjectListKey(), cached.filter((project) => project.project_id !== projectId));
  else projectListCache.invalidate();
  projectEntityCache.invalidate();
}

async function decryptProjectSource(source: ProjectSourceRecord, projectKey: Uint8Array): Promise<ProjectSourceViewModel> {
  const metadataText = await decryptOptional(source.encrypted_metadata, projectKey);
  const viewInput = {
    source: source as unknown as Record<string, unknown>, metadataText,
    displayName: await decryptOptional(source.encrypted_display_name, projectKey),
  };
  const { warnings, ...view } = PROJECT_RUST_CORE
    ? await decideProject("projectSourceView", viewInput) : projectRule("projectSourceView", viewInput);
  logMetadataWarnings(warnings);
  // The stored record stays the page's own object (the Rust answer is a key-sorted copy).
  return { ...view, encrypted: source } as unknown as ProjectSourceViewModel;
}

async function decryptProjectSettings(settings: ProjectSettingsRecord, projectKey: Uint8Array): Promise<ProjectSettingsViewModel> {
  const settingsText = await decryptOptional(settings.encrypted_settings, projectKey);
  const viewInput = { settings: settings as unknown as Record<string, unknown>, settingsText };
  const { warnings, ...view } = PROJECT_RUST_CORE
    ? await decideProject("projectSettingsView", viewInput) : projectRule("projectSettingsView", viewInput);
  logMetadataWarnings(warnings);
  return view as unknown as ProjectSettingsViewModel;
}

function logMetadataWarnings(warnings: Array<{ kind: "non_object" | "parse_error"; context: string }>): void {
  for (const warning of warnings) {
    console.warn(warning.kind === "non_object"
      ? `[ProjectService] Ignoring non-object Project metadata for ${warning.context}`
      : `[ProjectService] Failed to parse Project metadata for ${warning.context}`);
  }
}

export async function getProjectContents(
  project: ProjectViewModel,
  context: ProjectApiContext = {},
  chatOnly = false,
): Promise<{
  folders: ProjectFolderViewModel[];
  items: ProjectItemViewModel[];
}> {
  const data = await requestJson<{
    folders: ProjectFolderRecord[];
    items: ProjectItemRecord[];
  }>(
    withProjectRemoteQuery(`/v1/projects/${project.project_id}/items`, {
      team_id: context.teamId ?? project.teamId,
      ...(chatOnly ? { chat_only: "true" } : {}),
    }),
  );
  const folderInputs = await Promise.all(
    data.folders.map(async (folder) => ({
      record: folder as unknown as Record<string, unknown>,
      name: await decryptOptional(folder.encrypted_name, project.projectKey),
    })),
  );
  const itemInputs = await Promise.all(
    data.items.map(async (item) => ({
      record: item as unknown as Record<string, unknown>,
      metadataText: await decryptOptional(item.encrypted_metadata, project.projectKey),
      targetId: await decryptOptional(item.target_id_encrypted, project.projectKey),
      displayName: await decryptOptional(item.encrypted_display_name, project.projectKey),
    })),
  );
  const viewInput = { folders: folderInputs, items: itemInputs };
  const view = PROJECT_RUST_CORE ? await decideProject("projectContentsView", viewInput) : projectRule("projectContentsView", viewInput);
  logMetadataWarnings(view.warnings);
  // Stored records stay the page's own objects (the Rust answer carries key-sorted copies).
  return {
    folders: view.folders.map((folder, index) => ({ ...folder, encrypted: data.folders[index] })) as unknown as ProjectFolderViewModel[],
    items: view.items.map((item, index) => ({ ...item, encrypted: data.items[index] })) as unknown as ProjectItemViewModel[],
  };
}


export async function createFolder(project: ProjectViewModel, name: string, parentFolderId?: string, context: ProjectApiContext = {}): Promise<void> {
  const timestamp = nowSeconds();
  await requestJson(withProjectRemoteQuery(`/v1/projects/${project.project_id}/folders`, { team_id: context.teamId ?? project.teamId }), {
    method: "POST",
    body: JSON.stringify({
      folder_id: crypto.randomUUID(),
      parent_folder_id: parentFolderId ?? null,
      encrypted_name: await encryptWithEmbedKey(name, project.projectKey),
      encrypted_sort_key: await encryptWithEmbedKey(name.toLowerCase(), project.projectKey),
      created_at: timestamp,
      updated_at: timestamp,
      position: timestamp,
    }),
  });
}

export async function addExistingTargetToProject(
  project: ProjectViewModel,
  targetId: string,
  itemType: ProjectItemType,
  displayName: string,
  folderId?: string,
  metadata: Record<string, unknown> = {},
  context: ProjectApiContext = {},
): Promise<void> {
  const timestamp = nowSeconds();
  await requestJson(withProjectRemoteQuery(`/v1/projects/${project.project_id}/items`, { team_id: context.teamId ?? project.teamId }), {
    method: "POST",
    body: JSON.stringify({
      project_item_id: crypto.randomUUID(),
      folder_id: folderId ?? null,
      item_type: itemType,
      target_id: targetId,
      target_id_encrypted: await encryptWithEmbedKey(targetId, project.projectKey),
      encrypted_display_name: await encryptWithEmbedKey(displayName, project.projectKey),
      encrypted_note: await encryptWithEmbedKey("", project.projectKey),
      encrypted_metadata: await encryptWithEmbedKey(JSON.stringify(metadata), project.projectKey),
      created_at: timestamp,
      updated_at: timestamp,
      position: timestamp,
    }),
  });
}

/** Retain private Workflow file bindings only inside encrypted Project metadata. */
export async function updateProjectItemMetadata(
  project: ProjectViewModel, itemId: string, metadata: Record<string, unknown>, context: ProjectApiContext = {},
): Promise<void> {
  await requestJson(withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(project.project_id)}/items/${encodeURIComponent(itemId)}`,
    { team_id: context.teamId ?? project.teamId }), {
    method: 'PATCH', body: JSON.stringify({
      encrypted_metadata: await encryptWithEmbedKey(JSON.stringify(metadata), project.projectKey), updated_at: nowSeconds(),
    }),
  });
}

/** Move one existing Project association to a different Project folder. */
export async function moveProjectItemToFolder(
  project: ProjectViewModel,
  itemId: string,
  folderId: string | null,
  context: ProjectApiContext = {},
): Promise<void> {
  await requestJson(withProjectRemoteQuery(
    `/v1/projects/${encodeURIComponent(project.project_id)}/items/${encodeURIComponent(itemId)}`,
    { team_id: context.teamId ?? project.teamId },
  ), {
    method: "PATCH",
    body: JSON.stringify({ folder_id: folderId, updated_at: nowSeconds() }),
  });
}

/** Remove only a Project association; the chat and its messages remain intact. */
export async function removeChatFromProject(projectId: string, chatId: string, context: ProjectApiContext = {}): Promise<void> {
  await requestJson(withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(projectId)}/items`, {
    item_type: 'chat', target_id: chatId, team_id: context.teamId,
  }), { method: 'DELETE' });
}

/** Remove one embed's Project association (e.g. an expired Project memory file); the embed row follows the server rule. */
export async function removeEmbedFromProject(projectId: string, embedId: string, context: ProjectApiContext = {}): Promise<void> {
  await requestJson(withProjectRemoteQuery(`/v1/projects/${encodeURIComponent(projectId)}/items`, {
    item_type: 'embed', target_id: embedId, team_id: context.teamId,
  }), { method: 'DELETE' });
}

async function uploadMindMapToProject(
  project: ProjectViewModel,
  file: File,
  source: string,
  metadata: ProjectUploadMetadata = {},
  location: ProjectUploadLocation = {},
): Promise<void> {
  const normalization = normalizeMindMapSource(source);
  if (normalization.status === "invalid_source" || !normalization.model) {
    throw new Error(normalization.parseError || "Invalid mind map JSON");
  }

  const timestampMs = Date.now();
  const timestamp = Math.floor(timestampMs / 1000);
  const embedId = crypto.randomUUID();
  const embedType = "mindmaps-mindmap";
  const embedKey = generateEmbedKey();
  const embedRef = generateDirectEmbedRef("mindmap", embedId, {
    filename: file.name,
  });
  const embedContent = JSON.stringify({
    type: "mindmap",
    app_id: "mindmaps",
    skill_id: "mindmap",
    title: normalization.title,
    source_json: normalization.sourceJson,
    model: normalization.model,
    validation: {
      status: normalization.status,
      warnings: normalization.warnings,
    },
    embed_ref: embedRef,
    status: "finished",
    version_number: 1,
    node_count: normalization.nodeCount,
    edge_count: normalization.edgeCount,
    filename: file.name,
  });
  const contentHash = await computeSHA256(normalization.sourceJson);
  const hashedEmbedId = await computeSHA256(embedId);
  const hashedProjectId = await computeSHA256(project.project_id);
  const wrappedMasterKey = await wrapEmbedKeyWithMasterKey(embedKey);
  const wrappedProjectKey = await wrapEmbedKeyWithChatKey(embedKey, project.projectKey);
  if (!wrappedMasterKey || !wrappedProjectKey) throw new Error("Could not wrap mind map embed keys");

  await requestJson(`/v1/projects/${project.project_id}/upload-embed`, {
    method: "POST",
    body: JSON.stringify({
      embed: {
        embed_id: embedId,
        encrypted_type: await encryptWithEmbedKey(embedType, embedKey),
        status: "finished",
        encrypted_content: await encryptWithEmbedKey(embedContent, embedKey),
        encrypted_text_preview: await encryptWithEmbedKey(normalization.title, embedKey),
        content_hash: contentHash,
        created_at: timestamp,
        updated_at: timestamp,
        encryption_mode: "client",
        is_private: true,
        is_shared: false,
      },
      embed_keys: [
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "master",
          encrypted_embed_key: wrappedMasterKey,
          created_at: timestamp,
        },
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "project",
          hashed_project_id: hashedProjectId,
          encrypted_embed_key: wrappedProjectKey,
          created_at: timestamp,
        },
      ],
      item: {
        project_item_id: crypto.randomUUID(),
        folder_id: location.folderId ?? null,
        item_type: "embed",
        target_id: embedId,
        target_id_encrypted: await encryptWithEmbedKey(embedId, project.projectKey),
        encrypted_display_name: await encryptWithEmbedKey(normalization.title || file.name, project.projectKey),
        encrypted_note: await encryptWithEmbedKey("", project.projectKey),
        encrypted_metadata: await encryptWithEmbedKey(JSON.stringify({ ...metadata, embed_type: embedType }), project.projectKey),
        created_at: timestamp,
        updated_at: timestamp,
        position: timestamp,
      },
    }),
  });

  await embedStore.put(
    `embed:${embedId}`,
    {
      embed_id: embedId,
      type: embedType as never,
      status: "finished",
      content: embedContent,
      text_preview: normalization.title,
      createdAt: timestampMs,
      updatedAt: timestampMs,
    },
    embedType as never,
  );
  embedStore.registerEmbedRef(embedRef, embedId, "mindmap");
}

async function uploadRemoteCodeFileToProject(
  project: ProjectViewModel, file: File, metadata: ProjectUploadMetadata, location: ProjectUploadLocation,
  route: { language: string; readme: boolean },
): Promise<void> {
  const source = await file.text();
  const timestampMs = Date.now();
  const timestamp = Math.floor(timestampMs / 1000);
  const embedId = crypto.randomUUID();
  const embedType = "code-code";
  const storedMetadata = route.readme
    ? { ...metadata, embed_type: embedType, readme_uploaded_at_ms: timestampMs }
    : { ...metadata, embed_type: embedType };
  const embedKey = generateEmbedKey();
  const embedRef = generateDirectEmbedRef("code", embedId, {
    filename: file.name,
  });
  const contentHash = await computeSHA256(source);
  const embedContent = JSON.stringify({
    type: "code",
    app_id: "code",
    skill_id: "code",
    language: route.language,
    code: source,
    filename: file.name,
    embed_ref: embedRef,
    status: "finished",
    line_count: source.split("\n").length,
    content_hash: contentHash,
  });
  const hashedEmbedId = await computeSHA256(embedId);
  const hashedProjectId = await computeSHA256(project.project_id);
  const wrappedMasterKey = await wrapEmbedKeyWithMasterKey(embedKey);
  const wrappedProjectKey = await wrapEmbedKeyWithChatKey(embedKey, project.projectKey);
  if (!wrappedMasterKey || !wrappedProjectKey) throw new Error("Could not wrap code embed keys");

  await requestJson(`/v1/projects/${project.project_id}/upload-embed`, {
    method: "POST",
    body: JSON.stringify({
      embed: {
        embed_id: embedId,
        encrypted_type: await encryptWithEmbedKey(embedType, embedKey),
        status: "finished",
        encrypted_content: await encryptWithEmbedKey(embedContent, embedKey),
        encrypted_text_preview: await encryptWithEmbedKey(file.name, embedKey),
        content_hash: contentHash,
        created_at: timestamp,
        updated_at: timestamp,
        encryption_mode: "client",
        is_private: true,
        is_shared: false,
      },
      embed_keys: [
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "master",
          encrypted_embed_key: wrappedMasterKey,
          created_at: timestamp,
        },
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "project",
          hashed_project_id: hashedProjectId,
          encrypted_embed_key: wrappedProjectKey,
          created_at: timestamp,
        },
      ],
      item: {
        project_item_id: crypto.randomUUID(),
        folder_id: location.folderId ?? null,
        item_type: "embed",
        target_id: embedId,
        target_id_encrypted: await encryptWithEmbedKey(embedId, project.projectKey),
        encrypted_display_name: await encryptWithEmbedKey(file.name, project.projectKey),
        encrypted_note: await encryptWithEmbedKey("", project.projectKey),
        encrypted_metadata: await encryptWithEmbedKey(JSON.stringify(storedMetadata), project.projectKey),
        created_at: timestamp,
        updated_at: timestamp,
        position: timestamp,
      },
    }),
  });

  await embedStore.put(
    `embed:${embedId}`,
    {
      embed_id: embedId,
      type: embedType as never,
      status: "finished",
      content: embedContent,
      text_preview: file.name,
      createdAt: timestampMs,
      updatedAt: timestampMs,
    },
    embedType as never,
  );
  embedStore.registerEmbedRef(embedRef, embedId, "code");
}

export async function uploadFileToProject(project: ProjectViewModel, file: File, metadata: ProjectUploadMetadata = {}, location: ProjectUploadLocation = {}): Promise<void> {
  const routeInput = { fileName: file.name, fileType: file.type, importedFromRemote: metadata.imported_from_remote_source === true };
  const route = PROJECT_RUST_CORE ? await decideProject("projectUploadRoute", routeInput) : projectRule("projectUploadRoute", routeInput);
  if (route.route === "code") {
    await uploadRemoteCodeFileToProject(project, file, metadata, location, route);
    return;
  }

  if (route.route === "mindmap") {
    const source = await file.text();
    const classification = classifyMindMapUploadSource(file.name, source, file.size);
    if (classification.accepted === false) {
      throw new Error(`Could not import mind map: ${classification.reason.replace(/_/g, " ")}`);
    }
    await uploadMindMapToProject(project, file, source, metadata, location);
    return;
  }

  const upload = await uploadFileToServer(file);
  const timestampMs = Date.now();
  const timestamp = Math.floor(timestampMs / 1000);
  const embedKey = generateEmbedKey();
  const typeInput = { filename: upload.filename, contentType: upload.content_type };
  const { embedType, appId } = PROJECT_RUST_CORE
    ? await decideProject("projectUploadEmbedType", typeInput) : projectRule("projectUploadEmbedType", typeInput);
  const embedContent = JSON.stringify({
    app_id: appId,
    skill_id: "upload",
    type: embedType,
    status: "finished",
    filename: upload.filename,
    file_size: file.size,
    file_type: upload.content_type,
    content_hash: upload.content_hash,
    s3_base_url: upload.s3_base_url,
    files: upload.files,
    aes_key: upload.aes_key,
    aes_nonce: upload.aes_nonce,
    vault_wrapped_aes_key: upload.vault_wrapped_aes_key,
    page_count: upload.page_count ?? null,
    ai_detection: upload.ai_detection,
  });
  const hashedEmbedId = await computeSHA256(upload.embed_id);
  const hashedProjectId = await computeSHA256(project.project_id);
  const wrappedMasterKey = await wrapEmbedKeyWithMasterKey(embedKey);
  const wrappedProjectKey = await wrapEmbedKeyWithChatKey(embedKey, project.projectKey);
  if (!wrappedMasterKey || !wrappedProjectKey) throw new Error("Could not wrap upload embed keys");

  await requestJson(`/v1/projects/${project.project_id}/upload-embed`, {
    method: "POST",
    body: JSON.stringify({
      embed: {
        embed_id: upload.embed_id,
        encrypted_type: await encryptWithEmbedKey(embedType, embedKey),
        status: "finished",
        encrypted_content: await encryptWithEmbedKey(embedContent, embedKey),
        encrypted_text_preview: await encryptWithEmbedKey(upload.filename, embedKey),
        content_hash: upload.content_hash,
        created_at: timestamp,
        updated_at: timestamp,
        encryption_mode: "client",
        is_private: true,
        is_shared: false,
      },
      embed_keys: [
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "master",
          encrypted_embed_key: wrappedMasterKey,
          created_at: timestamp,
        },
        {
          hashed_embed_id: hashedEmbedId,
          key_type: "project",
          hashed_project_id: hashedProjectId,
          encrypted_embed_key: wrappedProjectKey,
          created_at: timestamp,
        },
      ],
      item: {
        project_item_id: crypto.randomUUID(),
        folder_id: location.folderId ?? null,
        item_type: "embed",
        target_id: upload.embed_id,
        target_id_encrypted: await encryptWithEmbedKey(upload.embed_id, project.projectKey),
        encrypted_display_name: await encryptWithEmbedKey(upload.filename, project.projectKey),
        encrypted_note: await encryptWithEmbedKey("", project.projectKey),
        encrypted_metadata: await encryptWithEmbedKey(JSON.stringify({ ...metadata, embed_type: embedType }), project.projectKey),
        created_at: timestamp,
        updated_at: timestamp,
        position: timestamp,
      },
    }),
  });

  await embedStore.put(
    `embed:${upload.embed_id}`,
    {
      embed_id: upload.embed_id,
      type: embedType as never,
      status: "finished",
      content: embedContent,
      text_preview: upload.filename,
      createdAt: timestampMs,
      updatedAt: timestampMs,
    },
    embedType as never,
  );
}
