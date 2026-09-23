/*
 * Project remote-access bridge primitives.
 *
 * Purpose: provide bounded, read-only source search and cache-path helpers for
 * Project remote sources before interactive bridge commands are wired.
 * Architecture: CLI executes source reads/searches locally; OpenMates stores
 * only encrypted metadata and opaque source IDs.
 * Security: searches run inside approved source roots and filter high-risk,
 * binary, and out-of-root paths before returning snippets.
 * Tests: frontend/packages/openmates-cli/tests/remoteAccess.test.ts.
 */

import { startCodexTaskBridges, flushCodexChatDeletions } from "./codexTaskBridge.js";
import { flushTaskCommands } from "./taskCommandDelivery.js";
import { flushPendingTaskMutations } from "./taskMutationDelivery.js";
import { flushPendingTaskActivities } from "./taskActivityDelivery.js";
import lockfile from "proper-lockfile";
import { resolveStateDir } from "./storage.js";
import { ProjectTaskCache, decryptProjectTask, type ProjectTaskFrame } from "./projectTaskSync.js";
import {
  chmodSync,
  closeSync,
  constants,
  existsSync,
  fstatSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  readSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { join, resolve, relative } from "node:path";

import { canonicalProjectSourceRoot } from "./projectSourceRootPolicy.js";
import {
  loadProjectPathPolicy,
  ProjectPathAccessError,
  type LoadedProjectPathPolicy,
} from "./projectPathPolicy.js";
import {
  ProjectSearchProtocolError,
  matchesProjectSearchGlob,
  matchesProjectSearchQuery,
  normalizeProjectSearchRequest,
  type ProjectSearchMode,
  type ProjectSearchTarget,
} from "../../ui/src/utils/projectSearchProtocol.js";
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "./crypto.js";
import {
  createRemoteAccessHandshake,
  deriveRemoteAccessSessionKey,
  sealRemoteAccessEnvelope,
  type RemoteAccessCryptoIdentity,
  type RemoteAccessHandshake,
} from "./remoteAccessCrypto.js";
import type { OpenMatesClient } from "./client.js";
import { executeRemoteFileMutation, RemoteFileMutationError } from "./remoteFileWrites.js";
import { createRemoteCommandSourceController } from "./remoteCommandSource.js";
import { inspectRemoteCommandCapability } from "./remoteCommandRuntime.js";
import { prepareRemoteHttpsConnectNetworkConfinement } from "./remoteCommandNetwork.js";
import {
  isProjectFileMutationOperation, projectFileMutationDigest, validateProjectFileMutation,
} from "../../ui/src/utils/projectFileMutationProtocol.js";
import { WebSocketProtocolError, type ProjectRemoteAccessRequestFrame } from "./ws.js";
import { verifyProjectIgnoredReadGrant } from "../../ui/src/utils/projectIgnoredReadGrant.js";

export interface RemoteAccessSearchMatch {
  path: string;
  line?: number;
  snippet?: string;
}

export interface RemoteAccessSearchResult {
  matches: RemoteAccessSearchMatch[];
  omitted: number;
  excluded: number;
  truncated: boolean;
}

export interface RemoteAccessSourceRecord {
  sourceId: string;
  projectId?: string;
  sourceType: "local_folder" | "local_git_repository" | "remote_folder" | "remote_git_repository";
  rootPath: string;
  displayName: string;
  cachePath: string;
  status: "connected" | "offline" | "permission_required" | "revoked";
  createdAt: number;
  updatedAt: number;
}

export type RgRunner = (args: string[], cwd: string, maxOutputMatches?: number, stdin?: string) => Promise<string>;

export interface RemoteAccessSearchOptions {
  query: string;
  sourceRoot: string;
  maxResults?: number;
  target?: ProjectSearchTarget;
  mode?: ProjectSearchMode;
  path?: string;
  glob?: string;
  userProtectedPatterns?: string[];
  runRg: RgRunner;
  stateDirectory?: string;
}

export interface StartRemoteAccessSourceInput {
  sourceId: string;
  projectId?: string;
  rootPath: string;
  sourceType?: RemoteAccessSourceRecord["sourceType"];
  displayName?: string;
  homeDirectory?: string;
}

export interface StoredRemoteAccessSearchOptions {
  sourceId: string;
  query: string;
  maxResults?: number;
  target?: ProjectSearchTarget;
  mode?: ProjectSearchMode;
  path?: string;
  glob?: string;
  homeDirectory?: string;
  userProtectedPatterns?: string[];
  runRg: RgRunner;
}

const MAX_SEARCH_SNIPPET_CHARS = 500;
const SEARCH_TIMEOUT_MS = 10_000;
const MAX_FALLBACK_SEARCH_FILES = 10_000;
const MAX_RG_STDOUT_BYTES = 2 * 1024 * 1024;
const MAX_RG_STDERR_BYTES = 4 * 1024;
const MAX_RG_LINE_BYTES = 64 * 1024;
const MAX_APPROVED_ROOTS = 16;
const DEFAULT_MAX_DIRECTORY_ENTRIES = 500;
const DEFAULT_MAX_READ_BYTES = 200 * 1024;
const DEFAULT_MAX_READ_LINES = 4_000;
const REMOTE_ACCESS_RESULT_MAX_BYTES = 200 * 1024;
const BINARY_PROBE_BYTES = 8 * 1024;
const MAX_SOURCE_ID_LENGTH = 128;
const BINARY_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".pdf",
  ".zip",
  ".gz",
  ".tar",
  ".mp3",
  ".mp4",
  ".mov",
]);

export interface RemoteAccessRepositoryCandidate {
  rootPath: string;
  displayName: string;
}

export interface RemoteAccessDirectoryEntry {
  path: string;
  kind: "file" | "directory";
}

export interface LiveRemoteAccessBinding {
  source: RemoteAccessSourceRecord;
  projectKey: Uint8Array;
  keyEpoch: number;
  teamId?: string;
}

export interface RemoteAccessLifecycleEvent {
  state: "connecting" | "connected" | "reconnecting" | "disconnected";
  attempt?: number;
  delayMs?: number;
}

export function resolveRemoteAccessRoots(
  pathFlag: string | undefined,
  cwd = process.cwd(),
): string[] {
  const requested = pathFlag === undefined ? [cwd] : pathFlag.split("\n");
  if (requested.some((value) => !value)) throw new Error("--path requires a non-empty folder value");
  if (requested.length > MAX_APPROVED_ROOTS) {
    throw new Error(`remote-access accepts at most ${MAX_APPROVED_ROOTS} approved roots`);
  }
  const roots: string[] = [];
  for (const value of requested) {
    const candidate = resolve(cwd, value);
    if (!existsSync(candidate) || !statSync(candidate).isDirectory()) {
      throw new Error(`Remote source path does not exist or is not a directory: ${candidate}`);
    }
    const canonical = canonicalProjectSourceRoot(candidate);
    if (!roots.includes(canonical)) roots.push(canonical);
  }
  return roots;
}

export function discoverRemoteAccessRepositories(roots: string[]): {
  repositories: RemoteAccessRepositoryCandidate[];
  permissionDenied: string[];
} {
  const repositoryRoots = new Set<string>();
  const permissionDenied: string[] = [];

  const visit = (directory: string, approvedRoot: string): void => {
    let entries;
    try {
      entries = readdirSync(directory, { withFileTypes: true });
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code === "EACCES" || code === "EPERM") {
        permissionDenied.push(relative(approvedRoot, directory) || ".");
        return;
      }
      throw error;
    }
    if (entries.some((entry) => entry.name === ".git" && (entry.isDirectory() || entry.isFile()))) {
      repositoryRoots.add(realpathSync(directory));
    }
    for (const entry of entries) {
      if (entry.name === ".git" || entry.isSymbolicLink() || !entry.isDirectory()) continue;
      visit(join(directory, entry.name), approvedRoot);
    }
  };

  for (const root of roots) visit(root, root);
  return {
    repositories: [...repositoryRoots]
      .sort()
      .map((rootPath) => ({ rootPath, displayName: rootPath.split(/[\\/]/).filter(Boolean).pop() ?? rootPath })),
    permissionDenied: permissionDenied.sort(),
  };
}

export function remoteAccessSourceType(rootPath: string): RemoteAccessSourceRecord["sourceType"] {
  const gitMarker = join(rootPath, ".git");
  return existsSync(gitMarker) ? "local_git_repository" : "local_folder";
}

export function listRemoteAccessDirectory(options: {
  sourceRoot: string;
  relativePath: string;
  maxEntries?: number;
  userProtectedPatterns?: string[];
  stateDirectory?: string;
}): { entries: RemoteAccessDirectoryEntry[]; omitted: number; excluded: number; truncated: boolean } {
  const root = canonicalProjectSourceRoot(options.sourceRoot, { stateDirectory: options.stateDirectory });
  const policy = loadProjectPathPolicy(root, {
    trustedPrivatePaths: options.userProtectedPatterns,
    stateDirectory: options.stateDirectory,
    targetPaths: [options.relativePath],
  });
  const directory = resolveApprovedPath(root, options.relativePath);
  const directoryPath = relative(root, directory).replace(/\\/g, "/");
  if (directoryPath && (policy.isPrivate(directoryPath, true) || policy.isIgnored(directoryPath, true))) {
    throw new ProjectPathAccessError("private_path", "Remote source directory is unavailable");
  }
  if (!statSync(directory).isDirectory()) throw new Error("Remote source path is not a directory");
  const maxEntries = options.maxEntries ?? DEFAULT_MAX_DIRECTORY_ENTRIES;
  if (!Number.isInteger(maxEntries) || maxEntries <= 0 || maxEntries > DEFAULT_MAX_DIRECTORY_ENTRIES) {
    throw new Error(`Remote directory entry limit must be between 1 and ${DEFAULT_MAX_DIRECTORY_ENTRIES}`);
  }
  const entries: RemoteAccessDirectoryEntry[] = [];
  let omitted = 0;
  let excluded = 0;
  for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const entryPath = relative(root, join(directory, entry.name)).replace(/\\/g, "/");
    if (
      entry.name === ".git"
      || entry.isSymbolicLink()
      || policy.isIgnored(entryPath, entry.isDirectory())
      || policy.isPrivate(entryPath, entry.isDirectory())
      || (entry.isFile() && lstatSync(join(directory, entry.name)).nlink > 1)
      || (entry.isFile() && isBinaryFile(join(directory, entry.name)))
    ) {
      excluded += 1;
      continue;
    }
    if (!entry.isFile() && !entry.isDirectory()) {
      excluded += 1;
      continue;
    }
    if (entries.length >= maxEntries) {
      omitted += 1;
      continue;
    }
    entries.push({ path: entryPath, kind: entry.isDirectory() ? "directory" : "file" });
  }
  return { entries, omitted, excluded, truncated: omitted > 0 };
}

export function readRemoteAccessTextFile(options: {
  sourceRoot: string;
  relativePath: string;
  maxBytes?: number;
  maxLines?: number;
  userProtectedPatterns?: string[];
  stateDirectory?: string;
  isIgnoredReadApproved?: (path: string) => boolean;
  beforeOpen?: () => void;
}): { content: string; truncated: boolean; sizeBytes: number; lineCount: number; expected_base: string | null } {
  const root = canonicalProjectSourceRoot(options.sourceRoot, { stateDirectory: options.stateDirectory });
  const normalizedRelative = options.relativePath.replace(/\\/g, "/");
  const policy = loadProjectPathPolicy(root, {
    trustedPrivatePaths: options.userProtectedPatterns,
    stateDirectory: options.stateDirectory,
    targetPaths: [normalizedRelative],
  });
  policy.assertReadablePath(normalizedRelative, options.isIgnoredReadApproved);
  const requested = resolveApprovedPath(root, normalizedRelative);
  if (lstatSync(requested).nlink > 1) throw new Error("Remote source file is a protected hardlink");
  options.beforeOpen?.();
  const maxBytes = normalizeBound(options.maxBytes, DEFAULT_MAX_READ_BYTES, "byte");
  const maxLines = normalizeBound(options.maxLines, DEFAULT_MAX_READ_LINES, "line");
  let descriptor: number | undefined;
  try {
    descriptor = openSync(requested, constants.O_RDONLY | constants.O_NOFOLLOW);
    const openedPath = openedDescriptorPath(descriptor, requested);
    assertInsideRoot(root, openedPath);
    const stats = fstatSync(descriptor);
    if (!stats.isFile()) throw new Error("Remote source path is not a regular file");
    const bytesToRead = Math.min(stats.size, maxBytes + 1);
    const buffer = Buffer.alloc(bytesToRead);
    const bytesRead = readSync(descriptor, buffer, 0, bytesToRead, 0);
    const bytes = new Uint8Array(buffer.subarray(0, bytesRead));
    if (bytes.subarray(0, BINARY_PROBE_BYTES).includes(0)) throw new Error("Remote source file is binary or unsupported");
    const decoded = decodeBoundedUtf8(bytes, Math.min(bytes.length, maxBytes), stats.size <= maxBytes);
    const lines = decoded.split(/(?<=\n)/);
    const content = lines.slice(0, maxLines).join("");
    const truncated = stats.size > maxBytes || lines.length > maxLines;
    return {
      content,
      truncated,
      sizeBytes: stats.size,
      lineCount: countTextLines(content),
      expected_base: truncated ? null : createHash("sha256").update(bytes.subarray(0, bytesRead)).digest("hex"),
    };
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ELOOP") throw new Error("Remote source path is a symbolic link");
    throw error;
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}

export function remoteAccessReadLimits(args: Record<string, unknown>): { maxBytes: number; maxLines: number } {
  const maxBytes = args.max_bytes;
  const maxLines = args.max_lines;
  return {
    maxBytes: normalizeBound(typeof maxBytes === "number" ? maxBytes : maxBytes === undefined ? undefined : Number.NaN, DEFAULT_MAX_READ_BYTES, "byte"),
    maxLines: normalizeBound(typeof maxLines === "number" ? maxLines : maxLines === undefined ? undefined : Number.NaN, DEFAULT_MAX_READ_LINES, "line"),
  };
}

type RemoteTextReadResult = {
  content: string;
  truncated: boolean;
  sizeBytes: number;
  lineCount: number;
  expected_base: string | null;
};

export function serializeRemoteAccessSuccessResponse(result: unknown): string {
  const serialized = JSON.stringify({ ok: true, result });
  if (new TextEncoder().encode(serialized).byteLength <= REMOTE_ACCESS_RESULT_MAX_BYTES) return serialized;
  if (!isRemoteTextReadResult(result)) {
    return JSON.stringify({ ok: false, error: "operation_failed" });
  }

  let low = 0;
  let high = result.content.length;
  let bounded = JSON.stringify({ ok: true, result: boundedRemoteTextResult(result, "") });
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const candidate = JSON.stringify({
      ok: true,
      result: boundedRemoteTextResult(result, safeTextPrefix(result.content, middle)),
    });
    if (new TextEncoder().encode(candidate).byteLength <= REMOTE_ACCESS_RESULT_MAX_BYTES) {
      bounded = candidate;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return bounded;
}

function isRemoteTextReadResult(value: unknown): value is RemoteTextReadResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const result = value as Record<string, unknown>;
  return typeof result.content === "string"
    && typeof result.truncated === "boolean"
    && typeof result.sizeBytes === "number"
    && typeof result.lineCount === "number"
    && (result.expected_base === null || typeof result.expected_base === "string");
}

function boundedRemoteTextResult(result: RemoteTextReadResult, content: string): RemoteTextReadResult {
  return {
    ...result,
    content,
    truncated: true,
    lineCount: countTextLines(content),
    expected_base: null,
  };
}

function safeTextPrefix(content: string, length: number): string {
  let end = Math.min(length, content.length);
  if (end > 0) {
    const code = content.charCodeAt(end - 1);
    if (code >= 0xd800 && code <= 0xdbff) end -= 1;
  }
  return content.slice(0, end);
}

export async function runRemoteAccessBridge(options: {
  client: OpenMatesClient;
  sourceSessionId: string;
  bindings: LiveRemoteAccessBinding[];
  signal: AbortSignal;
  confirmedTakeover?: boolean;
  taskCacheRoot?: string;
  onTaskSync?: (event: { projectId: string; directory: string; status: string }) => void;
  onLifecycle?: (event: RemoteAccessLifecycleEvent) => void;
}): Promise<void> {
  const accountScope = JSON.stringify([options.client.getSession().apiUrl, options.client.getSession().hashedEmail, options.bindings[0]?.teamId ?? "personal"]);
  const caches = new Map<string, ProjectTaskCache>();
  const releases: Array<() => Promise<void>> = [];
  let deliveryTimer: ReturnType<typeof setInterval> | undefined;
  let delivering = false;
  let codexBridges: ReturnType<typeof startCodexTaskBridges> | undefined;
  const commandCapability = inspectRemoteCommandCapability();
  // Keep tracked processes across transport reconnects. A new WebSocket must
  // recover their leases, never start the same approved execution again.
  const commandSource = commandCapability.supported ? createRemoteCommandSourceController({
    client: options.client,
    sourceSessionId: options.sourceSessionId,
    bindings: options.bindings,
    runtime: {
      capability: () => commandCapability,
      prepareNetworkConfinement: prepareRemoteHttpsConnectNetworkConfinement,
    },
  }) : null;
  const flushDelivery = async () => {
    if (delivering || options.signal.aborted) return;
    delivering = true;
    try {
      const notice = (status: string) => options.onTaskSync?.({ projectId: "", directory: "", status });
      await flushCodexChatDeletions(options.client, options.bindings[0]?.teamId, resolveStateDir(), notice);
      await flushTaskCommands(options.client, options.bindings[0]?.teamId, resolveStateDir(), notice);
      await flushPendingTaskActivities(options.client, options.bindings[0]?.teamId, resolveStateDir(), notice);
      await flushPendingTaskMutations(options.client, options.bindings[0]?.teamId, resolveStateDir(), notice);
    }
    catch { options.onTaskSync?.({ projectId: "", directory: "", status: "delivery_deferred" }); }
    finally { delivering = false; }
  };
  try {
    for (const binding of options.bindings) {
      const projectId = binding.source.projectId!;
      if (caches.has(projectId)) continue;
      const cache = new ProjectTaskCache(options.taskCacheRoot ?? join(resolveStateDir(), "project-task-cache"), accountScope, projectId);
      releases.push(await lockfile.lock(cache.directory, { retries: 0, stale: 120000 }));
      caches.set(projectId, cache);
    }
  codexBridges = startCodexTaskBridges(options.bindings.map(item => item.source.rootPath),
    [...caches.values()].map(cache => join(cache.directory, "snapshot.json")), resolveStateDir(),
    status => options.onTaskSync?.({projectId: "", directory: "", status}));
  deliveryTimer = setInterval(() => { void flushDelivery(); }, 5000);
  void flushDelivery();
  let reconnectAttempt = 0;
  while (!options.signal.aborted) {
    options.onLifecycle?.({ state: reconnectAttempt === 0 ? "connecting" : "reconnecting", attempt: reconnectAttempt });
    let ws: Awaited<ReturnType<OpenMatesClient["openProjectRemoteAccessWebSocket"]>>["ws"] | null = null;
    let removeRequestListener: (() => void) | null = null;
    let detachCommandSource: (() => void) | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    let taskSubscribeTimer: ReturnType<typeof setTimeout> | undefined;
    const waitingForProjects = new Set(caches.keys());
    let removeTaskListener: (() => void) | null = null;
    let taskFrames = Promise.resolve();
    for (const cache of caches.values()) cache.connection("reconnecting");
    try {
      const opened = await options.client.openProjectRemoteAccessWebSocket();
      ws = opened.ws;
      const lifecyclePayload = projectRemoteAccessLifecyclePayload(options.sourceSessionId, options.bindings);
      await ws.sendAsync("project_remote_access_register", {
        ...lifecyclePayload,
        confirmed_takeover: options.confirmedTakeover === true,
        bindings: options.bindings.map((binding) => ({
          project_id: binding.source.projectId,
          source_id: binding.source.sourceId,
          capabilities: ["read", "search", "import", "write_request", ...(commandCapability.supported ? ["run_command"] : [])],
          key_epoch: binding.keyEpoch,
        })),
      });
      await ws.waitForMessage("project_remote_access_registered", undefined, 20_000);
      detachCommandSource = commandSource?.attach(ws) ?? null;
      removeTaskListener = ws.onProjectTaskSync((type, payload) => {
        taskFrames = taskFrames.then(async () => {
          const frame = payload as ProjectTaskFrame & { code?: string };
          const cache = caches.get(frame.project_id);
          if (type === "project_task_sync_error") {
            if (cache) cache.connection(frame.code === "access_revoked" ? "revoked" : "reconnecting");
            else if (frame.code === "access_revoked") for (const item of caches.values()) item.connection("revoked");
            else ws?.close();
            options.onTaskSync?.({ projectId: frame.project_id ?? "", directory: cache?.directory ?? "", status: frame.code ?? "sync_deferred" });
            return;
          }
          if (!cache) throw new Error("Task sync returned an unselected Project");
          const binding = options.bindings.find(item => item.source.projectId === frame.project_id)!;
          const committed = await cache.accept(frame, record => decryptProjectTask(record,
            options.client.getMasterKeyBytes(), binding.projectKey, frame.project_id));
          if (committed) {
            waitingForProjects.delete(frame.project_id);
            if (!waitingForProjects.size) clearTimeout(taskSubscribeTimer);
            reconnectAttempt = 0;
            codexBridges?.changed();
            options.onTaskSync?.({ projectId: frame.project_id, directory: cache.directory, status: "synced" });
          }
        }).catch(() => {
          options.onTaskSync?.({ projectId: "", directory: "", status: "sync_deferred" });
          ws?.close(); // A fresh connection replays the last fully committed cursor.
        });
      });
      taskSubscribeTimer = setTimeout(() => {
        if (waitingForProjects.size) {
          options.onTaskSync?.({ projectId: "", directory: "", status: "Task sync did not acknowledge all Projects; reconnecting." });
          ws?.close();
        }
      }, 30_000);
      await ws.sendAsync("project_task_sync_subscribe", {
        ...(options.bindings[0]?.teamId ? { team_id: options.bindings[0].teamId } : {}),
        bindings: [...caches].map(([project_id, cache]) => ({
          project_id, source_id: options.bindings.find(item => item.source.projectId === project_id)!.source.sourceId,
          cursor: cache.cursor,
        })),
      });
      options.onLifecycle?.({ state: "connected" });
      removeRequestListener = ws.onProjectRemoteAccessRequest((frame) => {
        void handleLiveRemoteAccessRequest(options.client, ws!, opened.ownerId, options.sourceSessionId, options.bindings, frame);
      });
      heartbeatTimer = setInterval(() => {
        void ws?.sendAsync("project_remote_access_heartbeat", lifecyclePayload);
      }, 15_000);
      await Promise.race([ws.waitForClose(), waitForAbort(options.signal)]);
      if (options.signal.aborted) {
        await commandSource?.stop();
        await ws.sendAsync("project_remote_access_disconnect", lifecyclePayload).catch(() => undefined);
        options.onLifecycle?.({ state: "disconnected" });
        return;
      }
    } catch (error) {
      if (error instanceof WebSocketProtocolError) throw error;
      const message = error instanceof Error ? error.message : String(error);
      if (/session expired|invalid|not logged in/i.test(message)) throw error;
    } finally {
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      clearTimeout(taskSubscribeTimer);
      removeRequestListener?.();
      detachCommandSource?.();
      removeTaskListener?.();
      await taskFrames;
      ws?.close();
    }
    reconnectAttempt += 1;
    const delayMs = reconnectDelayMs(reconnectAttempt);
    options.onLifecycle?.({ state: "reconnecting", attempt: reconnectAttempt, delayMs });
    await waitForAbort(options.signal, delayMs);
  }
  } finally {
    await commandSource?.stop();
    codexBridges?.close();
    if (deliveryTimer) clearInterval(deliveryTimer);
    for (const cache of caches.values()) if (cache.snapshot.connection !== "revoked") cache.connection("stopped");
    const released = await Promise.allSettled(releases.reverse().map(release => release()));
    if (released.some(result => result.status === "rejected")) options.onTaskSync?.({projectId: "", directory: "", status: "Task cache lock cleanup needs review."});
  }
}

export function projectRemoteAccessLifecyclePayload(
  sourceSessionId: string,
  bindings: LiveRemoteAccessBinding[],
): { source_session_id: string; team_id?: string } {
  const teamId = bindings[0]?.teamId;
  return {
    source_session_id: sourceSessionId,
    ...(teamId ? { team_id: teamId } : {}),
  };
}

export function projectRemoteAccessCryptoIdentity(
  ownerId: string,
  sourceSessionId: string,
  binding: Pick<LiveRemoteAccessBinding, "teamId">,
  frame: Pick<
    ProjectRemoteAccessRequestFrame,
    "project_id" | "source_id" | "requesting_client_id" | "key_epoch" | "routing_identity"
  >,
): RemoteAccessCryptoIdentity {
  const routingIdentity = binding.teamId ? frame.routing_identity : undefined;
  return {
    ownerId: routingIdentity?.context_id_hash ?? ownerId,
    ...(routingIdentity ? {
      contextType: "team" as const,
      contextId: routingIdentity.context_id_hash,
      hostMemberId: routingIdentity.host_member_hash,
      hostDeviceId: routingIdentity.host_device_fingerprint_hash,
      requesterMemberId: routingIdentity.requester_member_hash,
      requesterDeviceId: routingIdentity.requester_device_fingerprint_hash,
    } : {}),
    projectId: frame.project_id,
    sourceId: frame.source_id,
    sourceSessionId,
    requestingClientId: frame.requesting_client_id,
    keyEpoch: frame.key_epoch,
  };
}

async function handleLiveRemoteAccessRequest(
  client: OpenMatesClient,
  ws: Awaited<ReturnType<OpenMatesClient["openProjectRemoteAccessWebSocket"]>>["ws"],
  ownerId: string,
  sourceSessionId: string,
  bindings: LiveRemoteAccessBinding[],
  frame: ProjectRemoteAccessRequestFrame,
): Promise<void> {
  const binding = bindings.find((item) =>
    item.source.sourceId === frame.source_id && item.source.projectId === frame.project_id
  );
  if (!binding || frame.source_session_id !== sourceSessionId || frame.key_epoch !== binding.keyEpoch) return;
  const bootstrapText = await decryptWithAesGcmCombined(frame.encrypted_envelope, binding.projectKey);
  if (!bootstrapText) return;
  let bootstrap: {
    type?: string;
    nonce?: string;
    requesting_client_id?: string;
    requester_handshake?: RemoteAccessHandshake;
    operation?: ProjectRemoteAccessRequestFrame["operation"];
    arguments?: Record<string, unknown>;
    ignored_read_grant?: unknown;
    ignored_read_context?: { chatId?: unknown; operationId?: unknown };
  };
  try {
    bootstrap = JSON.parse(bootstrapText) as typeof bootstrap;
  } catch {
    return;
  }
  if (
    bootstrap.type === "routing_discovery"
    && bootstrap.requesting_client_id === frame.requesting_client_id
    && bootstrap.nonce
  ) {
    await ws.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
      ...(binding.teamId ? { team_id: binding.teamId } : {}),
      project_id: frame.project_id,
      source_id: frame.source_id,
      request_id: frame.request_id,
      key_epoch: binding.keyEpoch,
      encrypted_envelope: await encryptWithAesGcmCombined(
        JSON.stringify({ type: "routing_discovery_result", nonce: bootstrap.nonce }),
        binding.projectKey,
      ),
    });
    return;
  }
  if (
    !bootstrap.requesting_client_id
    || bootstrap.requesting_client_id !== frame.requesting_client_id
    || !bootstrap.requester_handshake
    || bootstrap.operation !== frame.operation
    || !bootstrap.arguments
  ) return;
  if (binding.teamId && frame.routing_identity?.context_type !== "team") return;
  const identity = projectRemoteAccessCryptoIdentity(ownerId, sourceSessionId, binding, frame);
  try {
    const sourceHandshake = await createRemoteAccessHandshake(binding.projectKey, identity, "source");
    const sessionKey = await deriveRemoteAccessSessionKey(
      binding.projectKey,
      identity,
      "source",
      sourceHandshake.privateKey,
      sourceHandshake.handshake,
      bootstrap.requester_handshake,
    );
    let responseText: string;
    try {
      let result: unknown;
      if (isProjectFileMutationOperation(frame.operation)) {
        const mutation = validateProjectFileMutation(bootstrap.arguments.mutation);
        const chatId = bootstrap.arguments.chat_id;
        if (typeof chatId !== "string" || chatId !== frame.chat_id
          || mutation.operation !== frame.operation || mutation.operation_id !== frame.operation_id
          || await projectFileMutationDigest(binding.projectKey, frame.project_id, chatId, mutation) !== frame.proposal_digest) {
          throw new Error("write_authorization_denied");
        }
        const context = binding.teamId ? { teamId: binding.teamId } : { personal: true };
        const authorize = () => client.authorizeProjectRemoteWrite(
          frame.project_id, frame.source_id, frame.request_id, sourceSessionId, context,
        );
        // Resolve the trusted origin before selecting its idempotency journal,
        // then check again inside the brief file commit turn.
        const initial = await authorize();
        result = await executeRemoteFileMutation({
          sourceRoot: binding.source.rootPath, mutation,
          operationScope: initial.authorization_scope,
          authorize: async () => {
            const current = await authorize();
            if (current.authorization_scope !== initial.authorization_scope
              || current.operation_id !== mutation.operation_id) throw new Error("write_authorization_denied");
          },
        });
      } else {
        let approvedIgnoredPath: string | null = null;
        const requestedPath = typeof bootstrap.arguments.path === "string" ? bootstrap.arguments.path : ".";
        const ignoredReadContext = bootstrap.ignored_read_context;
        if (frame.operation === "read_text" && bootstrap.ignored_read_grant !== undefined
          && ignoredReadContext && typeof ignoredReadContext.chatId === "string"
          && typeof ignoredReadContext.operationId === "string"
          && await verifyProjectIgnoredReadGrant(binding.projectKey, bootstrap.ignored_read_grant, {
            projectId: frame.project_id,
            sourceId: frame.source_id,
            requestId: frame.request_id,
            chatId: ignoredReadContext.chatId,
            operationId: ignoredReadContext.operationId,
            path: requestedPath,
          })) {
          approvedIgnoredPath = requestedPath;
        }
        result = await executeRemoteAccessOperation(binding.source.rootPath, frame.operation, bootstrap.arguments, {
          isIgnoredReadApproved: approvedIgnoredPath === null ? undefined : (path) => path === approvedIgnoredPath,
        });
      }
      responseText = serializeRemoteAccessSuccessResponse(result);
    } catch (error) {
      responseText = JSON.stringify({ ok: false, error: remoteAccessOperationErrorCode(error) });
    }
    const envelope = await sealRemoteAccessEnvelope(
      sessionKey,
      identity,
      frame.request_id,
      "result",
      new TextEncoder().encode(responseText),
    );
    await ws.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
      ...(binding.teamId ? { team_id: binding.teamId } : {}),
      project_id: frame.project_id,
      source_id: frame.source_id,
      request_id: frame.request_id,
      key_epoch: binding.keyEpoch,
      encrypted_envelope: JSON.stringify({ source_handshake: sourceHandshake.handshake, envelope }),
    });
  } catch {
    // Invalid or unauthorized encrypted requests fail closed without plaintext diagnostics.
  }
}

async function executeRemoteAccessOperation(
  sourceRoot: string,
  operation: ProjectRemoteAccessRequestFrame["operation"],
  args: Record<string, unknown>,
  trustedOptions: { isIgnoredReadApproved?: (path: string) => boolean } = {},
): Promise<unknown> {
  const relativePath = typeof args.path === "string" ? args.path : ".";
  if (operation === "list") {
    return listRemoteAccessDirectory({ sourceRoot, relativePath });
  }
  if (operation === "read_text") {
    const limits = remoteAccessReadLimits(args);
    return readRemoteAccessTextFile({
      sourceRoot,
      relativePath,
      ...limits,
      isIgnoredReadApproved: trustedOptions.isIgnoredReadApproved,
    });
  }
  if (operation !== "search") throw new Error("unsupported_operation");
  return searchRemoteSource({
    query: typeof args.query === "string" ? args.query : "",
    sourceRoot,
    target: args.target as ProjectSearchTarget | undefined,
    mode: args.mode as ProjectSearchMode | undefined,
    path: typeof args.path === "string" ? args.path : undefined,
    glob: typeof args.glob === "string" ? args.glob : undefined,
    maxResults: typeof args.max_results === "number" ? args.max_results : undefined,
    runRg: runRgCommand,
  });
}

export function remoteAccessOperationErrorCode(error: unknown): string {
  if (error instanceof RemoteFileMutationError) return error.code;
  if (error instanceof ProjectSearchProtocolError) return error.code;
  if (error instanceof ProjectPathAccessError) {
    return error.code === "private_path" ? "protected_path" : error.code;
  }
  const message = error instanceof Error ? error.message : "";
  if (message === "write_authorization_denied") return message;
  if (typeof (error as { code?: unknown })?.code === "string"
    && /authorization|focus|approval|write.policy|permission/i.test(String((error as { code: string }).code))) {
    return "write_authorization_denied";
  }
  if (/protected|private/i.test(message)) return "protected_path";
  if (/binary|unsupported/i.test(message)) return "unsupported_file";
  if (/symbolic link|approved source root|not a directory|not a regular file|ENOENT/i.test(message)) return "invalid_path";
  if (message === "regex_search_unavailable") return message;
  return "operation_failed";
}

function reconnectDelayMs(attempt: number): number {
  const base = Math.min(30_000, 1_000 * (2 ** Math.max(0, attempt - 1)));
  return Math.round(base * (0.8 + Math.random() * 0.4));
}

function waitForAbort(signal: AbortSignal, timeoutMs?: number): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolvePromise) => {
    const onAbort = () => {
      if (timer) clearTimeout(timer);
      resolvePromise();
    };
    const timer = timeoutMs === undefined
      ? undefined
      : setTimeout(() => {
          signal.removeEventListener("abort", onAbort);
          resolvePromise();
        }, timeoutMs);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function resolveRemoteCachePath(sourceId: string, homeDirectory?: string): string {
  assertSafeSourceId(sourceId);
  return join(remoteAccessStateDirectory(homeDirectory), "remote-cache", sourceId);
}

export function startRemoteAccessSource(input: StartRemoteAccessSourceInput): RemoteAccessSourceRecord {
  assertSafeSourceId(input.sourceId);
  const requestedRootPath = resolve(input.rootPath);
  if (!existsSync(requestedRootPath) || !statSync(requestedRootPath).isDirectory()) {
    throw new Error(`Remote source path does not exist or is not a directory: ${requestedRootPath}`);
  }
  const rootPath = canonicalProjectSourceRoot(requestedRootPath, {
    stateDirectory: input.homeDirectory === undefined
      ? resolveStateDir()
      : resolveStateDir({ homeDir: input.homeDirectory, stateDir: "", profile: "" }),
  });
  const now = Math.floor(Date.now() / 1000);
  const source: RemoteAccessSourceRecord = {
    sourceId: input.sourceId,
    projectId: input.projectId,
    sourceType: input.sourceType ?? "local_folder",
    rootPath,
    displayName: input.displayName ?? input.sourceId,
    cachePath: resolveRemoteCachePath(input.sourceId, input.homeDirectory),
    status: "offline",
    createdAt: now,
    updatedAt: now,
  };
  const sources = listRemoteAccessSources(input.homeDirectory).filter((entry) => entry.sourceId !== input.sourceId);
  saveRemoteAccessSources([...sources, source], input.homeDirectory);
  mkdirSync(source.cachePath, { recursive: true, mode: 0o700 });
  return source;
}

export function listRemoteAccessSources(homeDirectory?: string): RemoteAccessSourceRecord[] {
  const filePath = remoteAccessStorePath(homeDirectory);
  if (!existsSync(filePath)) return [];
  try {
    const parsed = JSON.parse(readFileSync(filePath, "utf-8")) as { sources?: RemoteAccessSourceRecord[] };
    if (!Array.isArray(parsed.sources)) {
      throw new Error("Remote source store is missing the sources array");
    }
    parsed.sources.forEach((source, index) => assertRemoteAccessSourceRecord(source, index));
    return parsed.sources;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to read remote source store at ${filePath}: ${message}`);
  }
}

export async function searchStoredRemoteAccessSource(options: StoredRemoteAccessSearchOptions): Promise<RemoteAccessSearchResult> {
  const source = listRemoteAccessSources(options.homeDirectory).find((entry) => entry.sourceId === options.sourceId);
  if (!source) {
    throw new Error(`Remote source '${options.sourceId}' is not attached`);
  }
  return searchRemoteSource({
    query: options.query,
    sourceRoot: source.rootPath,
    maxResults: options.maxResults,
    target: options.target,
    mode: options.mode,
    path: options.path,
    glob: options.glob,
    userProtectedPatterns: options.userProtectedPatterns,
    runRg: options.runRg,
  });
}

export async function searchRemoteSource(options: RemoteAccessSearchOptions): Promise<RemoteAccessSearchResult> {
  const sourceRoot = canonicalProjectSourceRoot(options.sourceRoot, { stateDirectory: options.stateDirectory });
  const request = normalizeProjectSearchRequest({
    query: options.query,
    target: options.target,
    mode: options.mode,
    path: options.path,
    glob: options.glob,
    max_results: options.maxResults,
  });
  const policy = loadProjectPathPolicy(sourceRoot, {
    trustedPrivatePaths: options.userProtectedPatterns,
    stateDirectory: options.stateDirectory,
    discoverNestedIgnoreFiles: true,
  });
  const targetPath = resolveApprovedPath(sourceRoot, request.path);
  const searchPath = relative(sourceRoot, targetPath).replace(/\\/g, "/") || ".";
  if (searchPath !== "." && (policy.isPrivate(searchPath, statSync(targetPath).isDirectory())
    || policy.isIgnored(searchPath, statSync(targetPath).isDirectory()))) {
    throw new Error("Remote source search path is protected");
  }
  const hardlinkExclusions = collectSearchHardlinkExclusions(sourceRoot, targetPath, policy);

  try {
    if (request.target === "files") {
      return await searchRemoteFileNamesWithRg(options.runRg, sourceRoot, searchPath, request, policy, hardlinkExclusions);
    }
    const output = await options.runRg(
      buildRgContentSearchArgs(request, searchPath, policy, hardlinkExclusions),
      sourceRoot,
      request.maxResults + 1,
    );
    return collectRgContentMatches(output, sourceRoot, request, policy);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    if (request.mode === "regex") throw new ProjectSearchProtocolError("regex_search_unavailable");
    return searchRemoteSourceWithoutRg(request, sourceRoot, targetPath, policy);
  }
}

function collectRgContentMatches(
  output: string,
  sourceRoot: string,
  request: ReturnType<typeof normalizeProjectSearchRequest>,
  policy: LoadedProjectPathPolicy,
): RemoteAccessSearchResult {
  const matches: RemoteAccessSearchMatch[] = [];
  let omitted = 0;
  let excluded = 0;
  for (const line of output.split("\n")) {
    if (!line.trim()) continue;
    const match = parseRgMatch(line);
    if (!match) continue;
    if (
      shouldExcludeReadPath(sourceRoot, match.path, policy)
      || !isWithinSearchPath(match.path, request.path)
      || !matchesProjectSearchGlob(match.path, request.glob)
      || (match.line ?? 0) > DEFAULT_MAX_READ_LINES
    ) {
      excluded += 1;
      continue;
    }
    if (matches.length >= request.maxResults) {
      omitted += 1;
      continue;
    }
    matches.push(match);
  }
  return { matches, omitted, excluded, truncated: omitted > 0 };
}

function searchRemoteSourceWithoutRg(
  request: ReturnType<typeof normalizeProjectSearchRequest>,
  sourceRoot: string,
  targetPath: string,
  policy: LoadedProjectPathPolicy,
): RemoteAccessSearchResult {
  const root = canonicalProjectSourceRoot(sourceRoot);
  const deadline = Date.now() + SEARCH_TIMEOUT_MS;
  const targetStats = statSync(targetPath);
  const directories = targetStats.isDirectory() ? [targetPath] : [];
  const initialFiles = targetStats.isFile() ? [targetPath] : [];
  const matches: RemoteAccessSearchMatch[] = [];
  let inspectedFiles = 0;
  let omitted = 0;
  let excluded = 0;

  while (directories.length > 0 || initialFiles.length > 0) {
    if (Date.now() >= deadline) throw new Error("Remote source search timed out");
    const candidateFiles = initialFiles.splice(0);
    const directory = directories.pop();
    if (directory) {
      let entries;
      try {
        entries = readdirSync(directory, { withFileTypes: true }).sort((left, right) => left.name.localeCompare(right.name));
      } catch {
        excluded += 1;
        continue;
      }
      for (const entry of entries) {
        const absolutePath = join(directory, entry.name);
        const relativePath = relative(root, absolutePath).replace(/\\/g, "/");
        if (
          entry.name === ".git"
          || entry.isSymbolicLink()
          || policy.isIgnored(relativePath, entry.isDirectory())
          || policy.isPrivate(relativePath, entry.isDirectory())
        ) {
          excluded += 1;
          continue;
        }
        if (entry.isDirectory()) {
          directories.push(absolutePath);
          continue;
        }
        if (!entry.isFile() || isBinaryFile(absolutePath)) {
          excluded += 1;
          continue;
        }
        candidateFiles.push(absolutePath);
      }
    }

    for (const absolutePath of candidateFiles) {
      const relativePath = relative(root, absolutePath).replace(/\\/g, "/");
      if (
        shouldExcludeReadPath(root, relativePath, policy)
        || isBinaryFile(absolutePath)
        || !matchesProjectSearchGlob(relativePath, request.glob)
      ) {
        excluded += 1;
        continue;
      }
      inspectedFiles += 1;
      if (inspectedFiles > MAX_FALLBACK_SEARCH_FILES) {
        omitted += 1;
        return { matches, omitted, excluded, truncated: true };
      }
      if (request.target === "files") {
        if (!matchesProjectSearchQuery(relativePath, request)) continue;
        if (matches.length >= request.maxResults) {
          omitted += 1;
          return { matches, omitted, excluded, truncated: true };
        }
        matches.push({ path: relativePath });
        continue;
      }
      let content: string;
      try {
        const read = readRemoteAccessTextFile({
          sourceRoot: root,
          relativePath,
          isIgnoredReadApproved: () => false,
        });
        if (read.sizeBytes > DEFAULT_MAX_READ_BYTES) {
          excluded += 1;
          continue;
        }
        content = read.content;
      } catch {
        excluded += 1;
        continue;
      }
      const lines = content.split(/(?<=\n)/);
      for (let index = 0; index < lines.length; index += 1) {
        if (!matchesProjectSearchQuery(lines[index] ?? "", request)) continue;
        if (matches.length >= request.maxResults) {
          omitted += 1;
          return { matches, omitted, excluded, truncated: true };
        }
        matches.push({ path: relativePath, line: index + 1, snippet: lines[index]!.slice(0, MAX_SEARCH_SNIPPET_CHARS) });
      }
    }
  }
  return { matches, omitted, excluded, truncated: omitted > 0 };
}

async function searchRemoteFileNamesWithRg(
  runRg: RgRunner,
  sourceRoot: string,
  searchPath: string,
  request: ReturnType<typeof normalizeProjectSearchRequest>,
  policy: LoadedProjectPathPolicy,
  hardlinkExclusions: readonly string[],
): Promise<RemoteAccessSearchResult> {
  const output = await runRg(
    buildRgFileListArgs(request, searchPath, policy, hardlinkExclusions),
    sourceRoot,
    MAX_FALLBACK_SEARCH_FILES + 1,
  );
  const outputPaths = output.split("\n").filter(Boolean);
  const enumerationTruncated = outputPaths.length > MAX_FALLBACK_SEARCH_FILES;
  const candidates: string[] = [];
  let excluded = 0;
  for (const rawPath of outputPaths.slice(0, MAX_FALLBACK_SEARCH_FILES)) {
    const path = normalizeRgPath(rawPath);
    if (
      path === null
      || shouldExcludeReadPath(sourceRoot, path, policy)
      || !isWithinSearchPath(path, request.path)
      || !matchesProjectSearchGlob(path, request.glob)
    ) {
      excluded += 1;
      continue;
    }
    candidates.push(path);
  }

  let matchedPaths: string[];
  let regexTruncated = false;
  if (request.mode === "literal") {
    matchedPaths = candidates.filter((path) => matchesProjectSearchQuery(path, request));
  } else {
    const regexOutput = await runRg(
      buildRgFilenameRegexArgs(request.query),
      sourceRoot,
      request.maxResults + 1,
      candidates.length ? `${candidates.join("\n")}\n` : "",
    );
    matchedPaths = regexOutput.split("\n").map(parseRgStdinMatch).filter((path): path is string => path !== null);
    regexTruncated = matchedPaths.length > request.maxResults;
  }
  const omitted = Math.max(0, matchedPaths.length - request.maxResults) + (enumerationTruncated ? 1 : 0);
  return {
    matches: matchedPaths.slice(0, request.maxResults).map((path) => ({ path })),
    omitted,
    excluded,
    truncated: omitted > 0 || regexTruncated,
  };
}

function assertSafeSourceId(sourceId: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(sourceId) || sourceId.length > MAX_SOURCE_ID_LENGTH) {
    throw new Error("Remote source ID must be 1-128 characters and contain only letters, numbers, dot, underscore, or hyphen");
  }
}

function buildRgContentSearchArgs(
  request: ReturnType<typeof normalizeProjectSearchRequest>,
  searchPath: string,
  policy: LoadedProjectPathPolicy,
  hardlinkExclusions: readonly string[],
): string[] {
  const args = baseRgArgs(policy, hardlinkExclusions);
  args.push("--json", "--line-number", "--max-filesize", String(DEFAULT_MAX_READ_BYTES));
  if (request.mode === "literal") args.push("--fixed-strings");
  if (request.glob) args.push("--glob", request.glob);
  args.push("--regexp", request.query, "--", searchPath);
  return args;
}

function buildRgFileListArgs(
  request: ReturnType<typeof normalizeProjectSearchRequest>,
  searchPath: string,
  policy: LoadedProjectPathPolicy,
  hardlinkExclusions: readonly string[],
): string[] {
  const args = baseRgArgs(policy, hardlinkExclusions);
  args.push("--files");
  if (request.glob) args.push("--glob", request.glob);
  args.push("--", searchPath);
  return args;
}

function buildRgFilenameRegexArgs(query: string): string[] {
  return ["--no-config", "--color", "never", "--json", "--line-number", "--regexp", query, "--", "-"];
}

function baseRgArgs(policy: LoadedProjectPathPolicy, hardlinkExclusions: readonly string[]): string[] {
  // --no-require-git keeps .gitignore semantics in attached plain folders too.
  const args = ["--no-config", "--hidden", "--color", "never", "--no-require-git"];
  for (const pattern of [
    ".git",
    ".git/**",
    "**/.git/**",
    ...binaryRgGlobs(),
    ...policy.rgExclusionGlobs(),
    ...hardlinkExclusions,
  ]) args.push("--iglob", `!${pattern.replace(/\\/g, "/")}`);
  return args;
}

function binaryRgGlobs(): string[] {
  return [...BINARY_EXTENSIONS].flatMap((extension) => [`*${extension}`, `**/*${extension}`]);
}

export async function runRgCommand(
  args: string[],
  cwd: string,
  maxOutputMatches?: number,
  stdin?: string,
): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn("rg", args, {
      cwd,
      stdio: [stdin === undefined ? "ignore" : "pipe", "pipe", "pipe"],
      env: minimalRgEnvironment(),
    });
    const stdoutLines: string[] = [];
    let pendingStdout = "";
    let stdoutBytes = 0;
    let stderr = "";
    let stderrBytes = 0;
    let matchCount = 0;
    let killedForCap = false;
    let timedOut = false;
    let outputLimitExceeded = false;
    let settled = false;
    const settleReject = (error: Error) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    const settleResolve = (value: string) => {
      if (settled) return;
      settled = true;
      resolvePromise(value);
    };
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, SEARCH_TIMEOUT_MS);

    child.stdout!.setEncoding("utf-8");
    child.stdout!.on("data", (chunk: string) => {
      stdoutBytes += Buffer.byteLength(chunk);
      if (stdoutBytes > MAX_RG_STDOUT_BYTES) {
        outputLimitExceeded = true;
        child.kill();
        return;
      }
      pendingStdout += chunk;
      const lines = pendingStdout.split("\n");
      pendingStdout = lines.pop() ?? "";
      if (Buffer.byteLength(pendingStdout) > MAX_RG_LINE_BYTES) {
        outputLimitExceeded = true;
        child.kill();
        return;
      }
      for (const line of lines) {
        if (!line) continue;
        if (Buffer.byteLength(line) > MAX_RG_LINE_BYTES) {
          outputLimitExceeded = true;
          child.kill();
          break;
        }
        stdoutLines.push(line);
        if (args.includes("--files") || line.includes('"type":"match"')) {
          matchCount += 1;
        }
        if (maxOutputMatches !== undefined && matchCount >= maxOutputMatches) {
          killedForCap = true;
          child.kill();
          break;
        }
      }
    });

    child.stderr!.setEncoding("utf-8");
    child.stderr!.on("data", (chunk: string) => {
      if (stderrBytes >= MAX_RG_STDERR_BYTES) return;
      const remaining = MAX_RG_STDERR_BYTES - stderrBytes;
      const bounded = Buffer.from(chunk).subarray(0, remaining).toString("utf-8");
      stderr += bounded;
      stderrBytes += Buffer.byteLength(bounded);
    });

    child.on("error", (error) => {
      clearTimeout(timeout);
      settleReject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timeout);
      if (pendingStdout && Buffer.byteLength(pendingStdout) <= MAX_RG_LINE_BYTES) stdoutLines.push(pendingStdout);
      if (timedOut) {
        settleReject(new Error("Remote source search timed out"));
        return;
      }
      if (outputLimitExceeded) {
        settleReject(new Error("Remote source search output exceeded its byte limit"));
        return;
      }
      if (code === 0 || code === 1 || killedForCap) {
        settleResolve(stdoutLines.join("\n"));
        return;
      }
      const detail = stderr.trim().slice(0, 500);
      settleReject(new Error(`rg failed with exit code ${code}${detail ? `: ${detail}` : ""}`));
    });
    if (stdin !== undefined && child.stdin) child.stdin.end(stdin);
  });
}

function shouldExcludeReadPath(sourceRoot: string, relativePath: string, policy: LoadedProjectPathPolicy): boolean {
  if (normalizeRgPath(relativePath) === null) return true;
  if (!isPathInsideRoot(sourceRoot, relativePath)) return true;
  if (isBinaryPath(relativePath)) return true;
  return policy.isIgnored(relativePath) || policy.isPrivate(relativePath);
}

/** Enumerate metadata only so rg never opens a multiply-linked file before policy can inspect it. */
function collectSearchHardlinkExclusions(
  sourceRoot: string,
  targetPath: string,
  policy: LoadedProjectPathPolicy,
): string[] {
  const target = lstatSync(targetPath);
  if (target.isFile()) {
    const path = relative(sourceRoot, targetPath).replace(/\\/g, "/");
    return target.nlink > 1 ? [path] : [];
  }
  if (!target.isDirectory()) return [];
  const directories = [targetPath];
  const hardlinks: string[] = [];
  let inspected = 0;
  while (directories.length > 0) {
    const directory = directories.pop() as string;
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (++inspected > MAX_FALLBACK_SEARCH_FILES) {
        throw new Error("Remote source search alias scan exceeded its bounded file limit");
      }
      if (entry.name === ".git" || entry.isSymbolicLink()) continue;
      const absolute = join(directory, entry.name);
      const path = relative(sourceRoot, absolute).replace(/\\/g, "/");
      if (entry.isDirectory()) {
        if (!policy.isIgnored(path, true) && !policy.isPrivate(path, true)) directories.push(absolute);
        continue;
      }
      if (!entry.isFile() || policy.isIgnored(path) || policy.isPrivate(path)) continue;
      if (lstatSync(absolute).nlink > 1) hardlinks.push(path);
    }
  }
  return hardlinks;
}

function isWithinSearchPath(path: string, searchPath: string): boolean {
  if (searchPath === ".") return true;
  return path === searchPath || path.startsWith(`${searchPath}/`);
}

function parseRgStdinMatch(line: string): string | null {
  const match = parseRgMatch(line);
  return match?.snippet?.replace(/\r?\n$/, "") || null;
}

function minimalRgEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { LC_ALL: "C", LANG: "C" };
  for (const key of ["PATH", "Path", "SYSTEMROOT", "SystemRoot", "WINDIR", "PATHEXT"]) {
    if (process.env[key] !== undefined) env[key] = process.env[key];
  }
  return env;
}

function isPathInsideRoot(sourceRoot: string, relativePath: string): boolean {
  const resolvedPath = resolve(sourceRoot, relativePath);
  const relation = relative(sourceRoot, resolvedPath);
  return relation === "" || (!relation.startsWith("..") && !resolve(relation).startsWith("/.."));
}

function isBinaryPath(path: string): boolean {
  const lowerPath = path.toLowerCase();
  for (const extension of BINARY_EXTENSIONS) {
    if (lowerPath.endsWith(extension)) return true;
  }
  return false;
}

function parseRgMatch(line: string): RemoteAccessSearchMatch | null {
  try {
    const parsed = JSON.parse(line) as {
      type?: string;
      data?: {
        path?: { text?: string };
        line_number?: number;
        lines?: { text?: string };
      };
    };
    if (parsed.type !== "match") return null;
    const path = normalizeRgPath(parsed.data?.path?.text);
    const lineNumber = parsed.data?.line_number;
    const snippet = parsed.data?.lines?.text;
    if (path === null || typeof lineNumber !== "number" || typeof snippet !== "string") {
      return null;
    }
    return { path, line: lineNumber, snippet: snippet.slice(0, MAX_SEARCH_SNIPPET_CHARS) };
  } catch {
    return null;
  }
}

function normalizeRgPath(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\\/g, "/").replace(/^\.\//, "");
  if (
    !normalized
    || normalized.length > 2_048
    || normalized.startsWith("/")
    || hasControlCharacters(normalized)
    || normalized.split("/").some((part) => part === "..")
  ) return null;
  return normalized;
}

function hasControlCharacters(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (codePoint <= 0x1f || codePoint === 0x7f) return true;
  }
  return false;
}

function resolveApprovedPath(sourceRoot: string, relativePath: string): string {
  if (!relativePath || relativePath.includes("\0")) throw new Error("Remote source path is invalid");
  const lexical = resolve(sourceRoot, relativePath);
  assertInsideRoot(sourceRoot, lexical);
  const relation = relative(sourceRoot, lexical);
  let current = sourceRoot;
  for (const part of relation.split(/[\\/]/).filter(Boolean)) {
    current = join(current, part);
    if (lstatSync(current).isSymbolicLink()) throw new Error("Remote source path is a symbolic link");
  }
  const canonical = realpathSync(lexical);
  assertInsideRoot(sourceRoot, canonical);
  return canonical;
}

function assertInsideRoot(sourceRoot: string, path: string): void {
  const relation = relative(sourceRoot, path);
  if (relation.startsWith("..") || resolve(sourceRoot, relation) !== resolve(path)) {
    throw new Error("Remote source path escapes the approved source root");
  }
}

function openedDescriptorPath(descriptor: number, requestedPath: string): string {
  const procPath = `/proc/self/fd/${descriptor}`;
  if (existsSync(procPath)) return realpathSync(procPath);
  return realpathSync(requestedPath);
}

function isBinaryFile(path: string): boolean {
  let descriptor: number | undefined;
  try {
    descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    const stats = fstatSync(descriptor);
    const buffer = Buffer.alloc(Math.min(stats.size, BINARY_PROBE_BYTES));
    const bytesRead = readSync(descriptor, buffer, 0, buffer.length, 0);
    const bytes = new Uint8Array(buffer.subarray(0, bytesRead));
    if (bytes.includes(0)) return true;
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      return false;
    } catch {
      return true;
    }
  } catch {
    return true;
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}

function normalizeBound(value: number | undefined, maximum: number, label: string): number {
  const result = value ?? maximum;
  if (!Number.isInteger(result) || result <= 0 || result > maximum) {
    throw new Error(`Remote source ${label} limit must be between 1 and ${maximum}`);
  }
  return result;
}

function decodeBoundedUtf8(bytes: Uint8Array, limit: number, completeFile: boolean): string {
  const attempts = completeFile ? 1 : 4;
  for (let backoff = 0; backoff < attempts && limit - backoff >= 0; backoff += 1) {
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, limit - backoff));
    } catch {
      // A byte-bounded prefix may split one UTF-8 code point; at most three
      // trailing bytes can be removed without accepting invalid source text.
    }
  }
  throw new Error("Remote source file is binary or unsupported");
}

function countTextLines(content: string): number {
  if (!content) return 0;
  return content.split("\n").length - (content.endsWith("\n") ? 1 : 0);
}

function remoteAccessStateDirectory(homeDirectory?: string): string {
  return homeDirectory === undefined
    ? resolveStateDir()
    : resolveStateDir({ homeDir: homeDirectory, stateDir: "", profile: "" });
}

function remoteAccessStorePath(homeDirectory?: string): string {
  return join(remoteAccessStateDirectory(homeDirectory), "remote-sources.json");
}

function saveRemoteAccessSources(sources: RemoteAccessSourceRecord[], homeDirectory?: string): void {
  const filePath = remoteAccessStorePath(homeDirectory);
  const stateDir = remoteAccessStateDirectory(homeDirectory);
  mkdirSync(stateDir, { recursive: true, mode: 0o700 });
  chmodSync(stateDir, 0o700);
  writeFileSync(filePath, `${JSON.stringify({ sources }, null, 2)}\n`, { mode: 0o600 });
  chmodSync(filePath, 0o600);
}

function assertRemoteAccessSourceRecord(value: unknown, index: number): asserts value is RemoteAccessSourceRecord {
  if (typeof value !== "object" || value === null) {
    throw new Error(`Remote source record ${index} is not an object`);
  }
  const source = value as Partial<RemoteAccessSourceRecord>;
  const validStatus = ["connected", "offline", "permission_required", "revoked"].includes(source.status ?? "");
  const validType = ["local_folder", "local_git_repository", "remote_folder", "remote_git_repository"].includes(
    source.sourceType ?? "",
  );
  if (
    typeof source.sourceId !== "string" ||
    (source.projectId !== undefined && typeof source.projectId !== "string") ||
    !validType ||
    typeof source.rootPath !== "string" ||
    typeof source.displayName !== "string" ||
    typeof source.cachePath !== "string" ||
    !validStatus ||
    typeof source.createdAt !== "number" ||
    typeof source.updatedAt !== "number"
  ) {
    throw new Error(`Remote source record ${index} is invalid`);
  }
  assertSafeSourceId(source.sourceId);
}
