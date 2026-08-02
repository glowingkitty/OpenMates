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

import { homedir } from "node:os";
import {
  chmodSync,
  closeSync,
  constants,
  existsSync,
  fstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  readSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { join, resolve, relative } from "node:path";

import { classifyProjectFileRisk, PROJECT_HIGH_RISK_GLOBS } from "./projectFileRisk.js";
import { decryptWithAesGcmCombined } from "./crypto.js";
import {
  createRemoteAccessHandshake,
  deriveRemoteAccessSessionKey,
  sealRemoteAccessEnvelope,
  type RemoteAccessCryptoIdentity,
  type RemoteAccessHandshake,
} from "./remoteAccessCrypto.js";
import type { OpenMatesClient } from "./client.js";
import { WebSocketProtocolError, type ProjectRemoteAccessRequestFrame } from "./ws.js";

export interface RemoteAccessSearchMatch {
  path: string;
  line: number;
  snippet: string;
}

export interface RemoteAccessSearchResult {
  matches: RemoteAccessSearchMatch[];
  omitted: number;
  excluded: number;
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

export type RgRunner = (args: string[], cwd: string, maxOutputMatches?: number) => Promise<string>;

export interface RemoteAccessSearchOptions {
  query: string;
  sourceRoot: string;
  maxResults?: number;
  userProtectedPatterns?: string[];
  runRg: RgRunner;
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
  homeDirectory?: string;
  userProtectedPatterns?: string[];
  runRg: RgRunner;
}

const DEFAULT_MAX_SEARCH_RESULTS = 20;
const MAX_SEARCH_SNIPPET_CHARS = 500;
const SEARCH_TIMEOUT_MS = 10_000;
const MAX_FALLBACK_SEARCH_FILES = 10_000;
const MAX_APPROVED_ROOTS = 16;
const DEFAULT_MAX_DIRECTORY_ENTRIES = 500;
const DEFAULT_MAX_READ_BYTES = 200 * 1024;
const DEFAULT_MAX_READ_LINES = 4_000;
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
    const canonical = realpathSync(candidate);
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
}): { entries: RemoteAccessDirectoryEntry[]; omitted: number; excluded: number } {
  const root = realpathSync(options.sourceRoot);
  const directory = resolveApprovedPath(root, options.relativePath);
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
      || isGitIgnoredPath(root, entryPath)
      || classifyProjectFileRisk(entryPath, options.userProtectedPatterns ?? []).isHighRisk
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
  return { entries, omitted, excluded };
}

export function readRemoteAccessTextFile(options: {
  sourceRoot: string;
  relativePath: string;
  maxBytes?: number;
  maxLines?: number;
  userProtectedPatterns?: string[];
  beforeOpen?: () => void;
}): { content: string; truncated: boolean; sizeBytes: number; lineCount: number } {
  const root = realpathSync(options.sourceRoot);
  const normalizedRelative = options.relativePath.replace(/\\/g, "/");
  if (classifyProjectFileRisk(normalizedRelative, options.userProtectedPatterns ?? []).isHighRisk) {
    throw new Error("Remote source file is protected");
  }
  if (isGitIgnoredPath(root, normalizedRelative)) throw new Error("Remote source file is ignored");
  const requested = resolveApprovedPath(root, normalizedRelative);
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
    let decoded: string;
    try {
      decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, Math.min(bytes.length, maxBytes)));
    } catch {
      throw new Error("Remote source file is binary or unsupported");
    }
    const lines = decoded.split(/(?<=\n)/);
    const content = lines.slice(0, maxLines).join("");
    return {
      content,
      truncated: stats.size > maxBytes || lines.length > maxLines,
      sizeBytes: stats.size,
      lineCount: decoded.length === 0 ? 0 : decoded.split("\n").length,
    };
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ELOOP") throw new Error("Remote source path is a symbolic link");
    throw error;
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}

export async function runRemoteAccessBridge(options: {
  client: OpenMatesClient;
  sourceSessionId: string;
  bindings: LiveRemoteAccessBinding[];
  signal: AbortSignal;
  confirmedTakeover?: boolean;
  onLifecycle?: (event: RemoteAccessLifecycleEvent) => void;
}): Promise<void> {
  let reconnectAttempt = 0;
  while (!options.signal.aborted) {
    options.onLifecycle?.({ state: reconnectAttempt === 0 ? "connecting" : "reconnecting", attempt: reconnectAttempt });
    let ws: Awaited<ReturnType<OpenMatesClient["openProjectRemoteAccessWebSocket"]>>["ws"] | null = null;
    let removeRequestListener: (() => void) | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    try {
      const opened = await options.client.openProjectRemoteAccessWebSocket();
      ws = opened.ws;
      await ws.sendAsync("project_remote_access_register", {
        source_session_id: options.sourceSessionId,
        confirmed_takeover: options.confirmedTakeover === true,
        bindings: options.bindings.map((binding) => ({
          project_id: binding.source.projectId,
          source_id: binding.source.sourceId,
          capabilities: ["read", "search", "import"],
          key_epoch: binding.keyEpoch,
        })),
      });
      await ws.waitForMessage("project_remote_access_registered", undefined, 20_000);
      reconnectAttempt = 0;
      options.onLifecycle?.({ state: "connected" });
      removeRequestListener = ws.onProjectRemoteAccessRequest((frame) => {
        void handleLiveRemoteAccessRequest(ws!, opened.ownerId, options.sourceSessionId, options.bindings, frame);
      });
      heartbeatTimer = setInterval(() => {
        void ws?.sendAsync("project_remote_access_heartbeat", { source_session_id: options.sourceSessionId });
      }, 15_000);
      await Promise.race([ws.waitForClose(), waitForAbort(options.signal)]);
      if (options.signal.aborted) {
        await ws.sendAsync("project_remote_access_disconnect", { source_session_id: options.sourceSessionId }).catch(() => undefined);
        options.onLifecycle?.({ state: "disconnected" });
        return;
      }
    } catch (error) {
      if (error instanceof WebSocketProtocolError) throw error;
      const message = error instanceof Error ? error.message : String(error);
      if (/session expired|invalid|not logged in/i.test(message)) throw error;
    } finally {
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      removeRequestListener?.();
      ws?.close();
    }
    reconnectAttempt += 1;
    const delayMs = reconnectDelayMs(reconnectAttempt);
    options.onLifecycle?.({ state: "reconnecting", attempt: reconnectAttempt, delayMs });
    await waitForAbort(options.signal, delayMs);
  }
}

async function handleLiveRemoteAccessRequest(
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
    requesting_client_id?: string;
    requester_handshake?: RemoteAccessHandshake;
    operation?: ProjectRemoteAccessRequestFrame["operation"];
    arguments?: Record<string, unknown>;
  };
  try {
    bootstrap = JSON.parse(bootstrapText) as typeof bootstrap;
  } catch {
    return;
  }
  if (
    !bootstrap.requesting_client_id
    || bootstrap.requesting_client_id !== frame.requesting_client_id
    || !bootstrap.requester_handshake
    || bootstrap.operation !== frame.operation
    || !bootstrap.arguments
  ) return;
  const identity: RemoteAccessCryptoIdentity = {
    ownerId,
    projectId: frame.project_id,
    sourceId: frame.source_id,
    sourceSessionId,
    requestingClientId: bootstrap.requesting_client_id,
    keyEpoch: binding.keyEpoch,
  };
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
    let response: Record<string, unknown>;
    try {
      response = {
        ok: true,
        result: await executeRemoteAccessOperation(binding.source.rootPath, frame.operation, bootstrap.arguments),
      };
    } catch (error) {
      response = { ok: false, error: remoteAccessOperationErrorCode(error) };
    }
    const envelope = await sealRemoteAccessEnvelope(
      sessionKey,
      identity,
      frame.request_id,
      "result",
      new TextEncoder().encode(JSON.stringify(response)),
    );
    await ws.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
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
): Promise<unknown> {
  const relativePath = typeof args.path === "string" ? args.path : ".";
  if (operation === "list") {
    return listRemoteAccessDirectory({ sourceRoot, relativePath });
  }
  if (operation === "read_text") {
    return readRemoteAccessTextFile({ sourceRoot, relativePath });
  }
  const query = typeof args.query === "string" ? args.query : "";
  if (!query) throw new Error("Search query is required");
  return searchRemoteSource({ query, sourceRoot, runRg: runRgCommand });
}

function remoteAccessOperationErrorCode(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  if (/protected|ignored/i.test(message)) return "protected_path";
  if (/binary|unsupported/i.test(message)) return "unsupported_file";
  if (/symbolic link|approved source root|not a directory|not a regular file|ENOENT/i.test(message)) return "invalid_path";
  if (/Search query is required/i.test(message)) return "search_query_required";
  return "operation_failed";
}

function isGitIgnoredPath(sourceRoot: string, relativePath: string): boolean {
  if (!existsSync(join(sourceRoot, ".git"))) return false;
  const result = spawnSync("git", ["check-ignore", "--quiet", "--", relativePath], {
    cwd: sourceRoot,
    stdio: "ignore",
  });
  if (result.error) throw result.error;
  if (result.status === 0) return true;
  if (result.status === 1) return false;
  throw new Error("Could not evaluate Git ignored-file policy");
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

export function resolveRemoteCachePath(sourceId: string, homeDirectory = homedir()): string {
  assertSafeSourceId(sourceId);
  return join(homeDirectory, ".openmates", "remote-cache", sourceId);
}

export function startRemoteAccessSource(input: StartRemoteAccessSourceInput): RemoteAccessSourceRecord {
  assertSafeSourceId(input.sourceId);
  const homeDirectory = input.homeDirectory ?? homedir();
  const requestedRootPath = resolve(input.rootPath);
  if (!existsSync(requestedRootPath) || !statSync(requestedRootPath).isDirectory()) {
    throw new Error(`Remote source path does not exist or is not a directory: ${requestedRootPath}`);
  }
  const rootPath = realpathSync(requestedRootPath);
  const now = Math.floor(Date.now() / 1000);
  const source: RemoteAccessSourceRecord = {
    sourceId: input.sourceId,
    projectId: input.projectId,
    sourceType: input.sourceType ?? "local_folder",
    rootPath,
    displayName: input.displayName ?? input.sourceId,
    cachePath: resolveRemoteCachePath(input.sourceId, homeDirectory),
    status: "offline",
    createdAt: now,
    updatedAt: now,
  };
  const sources = listRemoteAccessSources(homeDirectory).filter((entry) => entry.sourceId !== input.sourceId);
  saveRemoteAccessSources([...sources, source], homeDirectory);
  mkdirSync(source.cachePath, { recursive: true, mode: 0o700 });
  return source;
}

export function listRemoteAccessSources(homeDirectory = homedir()): RemoteAccessSourceRecord[] {
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
    userProtectedPatterns: options.userProtectedPatterns,
    runRg: options.runRg,
  });
}

export async function searchRemoteSource(options: RemoteAccessSearchOptions): Promise<RemoteAccessSearchResult> {
  const sourceRoot = resolve(options.sourceRoot);
  const maxResults = normalizeMaxResults(options.maxResults);
  let output: string;
  try {
    output = await options.runRg(
      buildRgSearchArgs(options.query, options.userProtectedPatterns ?? []),
      sourceRoot,
      maxResults + 1,
    );
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    return searchRemoteSourceWithoutRg(options.query, sourceRoot, maxResults, options.userProtectedPatterns ?? []);
  }
  const matches: RemoteAccessSearchMatch[] = [];
  let omitted = 0;
  let excluded = 0;

  for (const line of output.split("\n")) {
    if (!line.trim()) continue;
    const match = parseRgMatch(line);
    if (!match) continue;
    if (shouldExcludePath(sourceRoot, match.path, options.userProtectedPatterns ?? [])) {
      excluded += 1;
      continue;
    }
    if (matches.length >= maxResults) {
      omitted += 1;
      continue;
    }
    matches.push(match);
  }

  return { matches, omitted, excluded };
}

function searchRemoteSourceWithoutRg(
  query: string,
  sourceRoot: string,
  maxResults: number,
  userProtectedPatterns: string[],
): RemoteAccessSearchResult {
  const root = realpathSync(sourceRoot);
  const deadline = Date.now() + SEARCH_TIMEOUT_MS;
  const directories = [root];
  const matches: RemoteAccessSearchMatch[] = [];
  let inspectedFiles = 0;
  let omitted = 0;
  let excluded = 0;

  while (directories.length > 0) {
    if (Date.now() >= deadline) throw new Error("Remote source search timed out");
    const directory = directories.pop()!;
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
        || isGitIgnoredPath(root, relativePath)
        || classifyProjectFileRisk(relativePath, userProtectedPatterns).isHighRisk
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
      inspectedFiles += 1;
      if (inspectedFiles > MAX_FALLBACK_SEARCH_FILES) {
        omitted += 1;
        return { matches, omitted, excluded };
      }
      let content: string;
      try {
        content = readRemoteAccessTextFile({
          sourceRoot: root,
          relativePath,
          userProtectedPatterns,
        }).content;
      } catch {
        excluded += 1;
        continue;
      }
      const lines = content.split(/(?<=\n)/);
      for (let index = 0; index < lines.length; index += 1) {
        if (!lines[index].includes(query)) continue;
        if (matches.length >= maxResults) {
          omitted += 1;
          return { matches, omitted, excluded };
        }
        matches.push({ path: relativePath, line: index + 1, snippet: lines[index].slice(0, MAX_SEARCH_SNIPPET_CHARS) });
      }
    }
  }
  return { matches, omitted, excluded };
}

function assertSafeSourceId(sourceId: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(sourceId) || sourceId.length > MAX_SOURCE_ID_LENGTH) {
    throw new Error("Remote source ID must be 1-128 characters and contain only letters, numbers, dot, underscore, or hyphen");
  }
}

function normalizeMaxResults(value: number | undefined): number {
  const maxResults = value ?? DEFAULT_MAX_SEARCH_RESULTS;
  if (!Number.isInteger(maxResults) || maxResults <= 0 || maxResults > DEFAULT_MAX_SEARCH_RESULTS) {
    throw new Error(`Remote source search limit must be between 1 and ${DEFAULT_MAX_SEARCH_RESULTS}`);
  }
  return maxResults;
}

function buildRgSearchArgs(query: string, userProtectedPatterns: string[]): string[] {
  const args = ["--json", "--line-number"];
  for (const pattern of [...PROJECT_HIGH_RISK_GLOBS, ...binaryRgGlobs(), ...userProtectedPatterns]) {
    args.push("--glob", `!${pattern.replace(/\\/g, "/")}`);
  }
  args.push("--", query, ".");
  return args;
}

function binaryRgGlobs(): string[] {
  return [...BINARY_EXTENSIONS].flatMap((extension) => [`*${extension}`, `**/*${extension}`]);
}

export async function runRgCommand(args: string[], cwd: string, maxOutputMatches?: number): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn("rg", args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdoutLines: string[] = [];
    const stderrChunks: string[] = [];
    let pendingStdout = "";
    let matchCount = 0;
    let killedForCap = false;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, SEARCH_TIMEOUT_MS);

    child.stdout.setEncoding("utf-8");
    child.stdout.on("data", (chunk: string) => {
      pendingStdout += chunk;
      const lines = pendingStdout.split("\n");
      pendingStdout = lines.pop() ?? "";
      for (const line of lines) {
        if (!line) continue;
        stdoutLines.push(line);
        if (line.includes('"type":"match"')) {
          matchCount += 1;
        }
        if (maxOutputMatches !== undefined && matchCount >= maxOutputMatches) {
          killedForCap = true;
          child.kill();
          break;
        }
      }
    });

    child.stderr.setEncoding("utf-8");
    child.stderr.on("data", (chunk: string) => stderrChunks.push(chunk));

    child.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timeout);
      if (pendingStdout) stdoutLines.push(pendingStdout);
      if (timedOut) {
        reject(new Error("Remote source search timed out"));
        return;
      }
      if (code === 0 || code === 1 || killedForCap) {
        resolvePromise(stdoutLines.join("\n"));
        return;
      }
      reject(new Error(`rg failed with exit code ${code}: ${stderrChunks.join("").trim()}`));
    });
  });
}

function shouldExcludePath(sourceRoot: string, relativePath: string, userProtectedPatterns: string[]): boolean {
  if (!isPathInsideRoot(sourceRoot, relativePath)) return true;
  if (isBinaryPath(relativePath)) return true;
  return classifyProjectFileRisk(relativePath, userProtectedPatterns).isHighRisk;
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
    const path = parsed.data?.path?.text;
    const lineNumber = parsed.data?.line_number;
    const snippet = parsed.data?.lines?.text;
    if (typeof path !== "string" || typeof lineNumber !== "number" || typeof snippet !== "string") {
      return null;
    }
    return { path, line: lineNumber, snippet: snippet.slice(0, MAX_SEARCH_SNIPPET_CHARS) };
  } catch {
    return null;
  }
}

function resolveApprovedPath(sourceRoot: string, relativePath: string): string {
  if (!relativePath || relativePath.includes("\0")) throw new Error("Remote source path is invalid");
  const lexical = resolve(sourceRoot, relativePath);
  assertInsideRoot(sourceRoot, lexical);
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

function remoteAccessStorePath(homeDirectory: string): string {
  return join(homeDirectory, ".openmates", "remote-sources.json");
}

function saveRemoteAccessSources(sources: RemoteAccessSourceRecord[], homeDirectory: string): void {
  const filePath = remoteAccessStorePath(homeDirectory);
  const stateDir = join(homeDirectory, ".openmates");
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
