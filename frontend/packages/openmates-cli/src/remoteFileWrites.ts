/** Bounded, crash-recoverable create/update operations for approved Project source roots. */

import { createHash, randomBytes } from "node:crypto";
import {
  chmodSync,
  closeSync,
  constants,
  existsSync,
  fstatSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readSync,
  realpathSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import lockfile from "proper-lockfile";

import { applyProjectFilePatch, ProjectFilePatchError } from "../../ui/src/utils/projectFilePatch.js";
import {
  validateProjectFileMutation,
  type ProjectFileMutation,
} from "../../ui/src/utils/projectFileMutationProtocol.js";
import { classifyProjectFileReadRisk } from "./projectFileRisk.js";
import { canonicalProjectSourceRoot } from "./projectSourceRootPolicy.js";
import { acquireRemoteProjectFileEditLock } from "./remoteCommandSourceLock.js";

export type { ProjectFileMutation } from "../../ui/src/utils/projectFileMutationProtocol.js";

export type RemoteFileMutationErrorCode =
  | "file_changed"
  | "target_exists"
  | "invalid_patch"
  | "protected_path"
  | "invalid_path"
  | "unsupported_file"
  | "operation_conflict"
  | "operation_unconfirmed"
  | "size_limit_exceeded";

export class RemoteFileMutationError extends Error {
  readonly code: RemoteFileMutationErrorCode;

  constructor(code: RemoteFileMutationErrorCode, message: string) {
    super(message);
    this.name = "RemoteFileMutationError";
    this.code = code;
  }
}

export interface RemoteFileMutationResult {
  operation_id: string;
  path: string;
  operation: ProjectFileMutation["operation"];
  before_hash: string | null;
  after_hash: string;
  content: string;
  applied_diff: string;
  replayed: boolean;
  already_applied: boolean;
}

export interface ProjectFileVersion {
  content: string;
  expected_base: string;
  sizeBytes: number;
}

export interface ExecuteRemoteFileMutationOptions {
  sourceRoot: string;
  mutation: ProjectFileMutation;
  /** Trusted caller/account/chat identity; operation IDs are unique only within this scope. */
  operationScope: string;
  authorize: () => Promise<void>;
  userProtectedPatterns?: string[];
  journalRoot?: string;
}

interface OpenedFile {
  content: string;
  hash: string;
  size: number;
  mode: number;
  dev: number;
  ino: number;
}

interface PinnedParent {
  descriptor: number;
  procPath: string;
  identity: string;
  targetName: string;
}

interface JournalRecord {
  schema_version: 1;
  operation_id: string;
  scope_digest: string;
  payload_digest: string;
  state: "prepared" | "applied";
  before_hash: string | null;
  after_hash: string;
  preimage: string | null;
  result: Omit<RemoteFileMutationResult, "replayed" | "already_applied">;
}

const MAX_FILE_BYTES = 200 * 1024;
const LOCK_ROOT = join(tmpdir(), `openmates-remote-file-locks-${typeof process.getuid === "function" ? process.getuid() : "user"}`);
const DEFAULT_JOURNAL_ROOT = join(tmpdir(), `openmates-remote-file-journal-${typeof process.getuid === "function" ? process.getuid() : "user"}`);

export function sha256ProjectFile(content: string | Uint8Array): string {
  return createHash("sha256").update(content).digest("hex");
}

export function readProjectFileVersion(options: {
  sourceRoot: string;
  path: string;
  userProtectedPatterns?: string[];
}): ProjectFileVersion {
  const root = canonicalRoot(options.sourceRoot);
  const path = validateRelativePath(options.path);
  enforcePathPolicy(root, path, options.userProtectedPatterns ?? []);
  const parent = openPinnedParent(root, path);
  try {
    const current = readPinnedFile(parent);
    if (!current) throw new RemoteFileMutationError("invalid_path", "Project file does not exist");
    return { content: current.content, expected_base: current.hash, sizeBytes: current.size };
  } finally {
    closeSync(parent.descriptor);
  }
}

export async function executeRemoteFileMutation(
  options: ExecuteRemoteFileMutationOptions,
): Promise<RemoteFileMutationResult> {
  const mutation = validateMutation(options.mutation);
  if (!options.operationScope || options.operationScope.length > 2048) {
    throw new RemoteFileMutationError("invalid_path", "Operation scope is missing or invalid");
  }
  const root = canonicalRoot(options.sourceRoot);
  enforcePathPolicy(root, mutation.path, options.userProtectedPatterns ?? []);
  const journalRoot = preparePrivateDirectory(options.journalRoot ?? DEFAULT_JOURNAL_ROOT);
  if (isInside(root, realpathSync(journalRoot))) {
    throw new RemoteFileMutationError("invalid_path", "Mutation journal must be outside the source root");
  }
  const scopeDigest = sha256ProjectFile(options.operationScope);
  const payloadDigest = sha256ProjectFile(stableJson(mutation));
  const journalPath = join(journalRoot, scopeDigest, `${sha256ProjectFile(`${options.operationScope}\0${mutation.operation_id}`)}.json`);
  preparePrivateDirectory(dirname(journalPath));

  // Replaying a prior receipt still requires current Project authority.
  await options.authorize();

  const existingJournal = readJournal(journalPath);
  if (existingJournal) {
    assertJournalIdentity(existingJournal, mutation, scopeDigest, payloadDigest);
    if (existingJournal.state === "applied") return replayResult(existingJournal.result);
  }

  const previewParent = openPinnedParent(root, mutation.path);
  let preview: { parentIdentity: string; current: OpenedFile | null; afterContent: string; appliedDiff: string };
  try {
    const current = readPinnedFile(previewParent);
    const proposed = proposedMutation(mutation, current);
    preview = { parentIdentity: previewParent.identity, current, ...proposed };
  } finally {
    closeSync(previewParent.descriptor);
  }

  const sourceLock = await acquireRemoteProjectFileEditLock(root);
  let pathLock: (() => Promise<void>) | undefined;
  try {
    pathLock = await acquirePathLock(preview.parentIdentity, mutation.path);
    // Revalidate after lock acquisition: a Project setting/focus may have changed
    // while a different file writer or source-mutating command held the boundary.
    await options.authorize();
    const journal = readJournal(journalPath);
    if (journal) {
      assertJournalIdentity(journal, mutation, scopeDigest, payloadDigest);
      if (journal.state === "applied") return replayResult(journal.result);
    }

    const parent = openPinnedParent(root, mutation.path);
    try {
      if (parent.identity !== preview.parentIdentity) {
        throw new RemoteFileMutationError("file_changed", "Project file parent changed during authorization");
      }
      const current = readPinnedFile(parent);
      if (journal?.state === "prepared") {
        if (current?.hash === journal.after_hash) {
          const recovered = { ...journal, state: "applied" as const };
          writeJournal(journalPath, recovered);
          return replayResult(recovered.result);
        }
        throw new RemoteFileMutationError(
          "operation_unconfirmed",
          "A previous attempt reached the mutation boundary but its outcome cannot be confirmed safely",
        );
      }
      assertPreviewStillCurrent(mutation, preview.current, current);
      const proposed = proposedMutation(mutation, current);
      if (proposed.afterContent !== preview.afterContent || proposed.appliedDiff !== preview.appliedDiff) {
        throw new RemoteFileMutationError("file_changed", "Project file changed during authorization");
      }
      const baseResult: Omit<RemoteFileMutationResult, "replayed" | "already_applied"> = {
        operation_id: mutation.operation_id,
        path: mutation.path,
        operation: mutation.operation,
        before_hash: current?.hash ?? null,
        after_hash: sha256ProjectFile(proposed.afterContent),
        content: proposed.afterContent,
        applied_diff: proposed.appliedDiff,
      };
      const prepared: JournalRecord = {
        schema_version: 1,
        operation_id: mutation.operation_id,
        scope_digest: scopeDigest,
        payload_digest: payloadDigest,
        state: "prepared",
        before_hash: baseResult.before_hash,
        after_hash: baseResult.after_hash,
        preimage: current?.content ?? null,
        result: baseResult,
      };
      sourceLock.assertHeld();
      writeJournal(journalPath, prepared);

      if (mutation.operation === "create_file") createPinnedFile(parent, proposed.afterContent);
      else replacePinnedFile(parent, current as OpenedFile, proposed.afterContent);

      const applied = { ...prepared, state: "applied" as const };
      writeJournal(journalPath, applied);
      return { ...baseResult, replayed: false, already_applied: false };
    } finally {
      closeSync(parent.descriptor);
    }
  } finally {
    try { await pathLock?.(); } finally { await sourceLock.release(); }
  }
}

function validateMutation(input: ProjectFileMutation): ProjectFileMutation {
  let parsed: ProjectFileMutation;
  try {
    parsed = validateProjectFileMutation(input);
  } catch (error) {
    if (error instanceof Error && error.message === "file_mutation_too_large") {
      throw new RemoteFileMutationError("size_limit_exceeded", `Mutation exceeds ${MAX_FILE_BYTES} bytes`);
    }
    throw new RemoteFileMutationError("invalid_patch", "Invalid Project file mutation payload");
  }
  return { ...parsed, path: validateRelativePath(parsed.path) };
}

function validateRelativePath(value: string): string {
  if (
    typeof value !== "string"
    || value.length === 0
    || value.length > 4096
    || isAbsolute(value)
    || value.includes("\\")
    || [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
    || value.split("/").some((part) => !part || part === "." || part === "..")
  ) {
    throw new RemoteFileMutationError("invalid_path", "Project file path must be a strict root-relative POSIX path");
  }
  return value;
}

function canonicalRoot(sourceRoot: string): string {
  try {
    return canonicalProjectSourceRoot(sourceRoot);
  } catch {
    throw new RemoteFileMutationError("invalid_path", "Source root is unavailable or protected");
  }
}

function enforcePathPolicy(root: string, path: string, userProtectedPatterns: string[]): void {
  if (path.split("/").includes(".git") || path === ".openmates/permissions.yml"
    || classifyProjectFileReadRisk(path, userProtectedPatterns).isHighRisk) {
    throw new RemoteFileMutationError("protected_path", "Project file path is protected");
  }
  if (!existsSync(join(root, ".git"))) return;
  const ignored = spawnSync("git", ["check-ignore", "--quiet", "--", path], { cwd: root, stdio: "ignore" });
  if (ignored.error) throw ignored.error;
  if (ignored.status === 0) throw new RemoteFileMutationError("protected_path", "Project file path is ignored");
  if (ignored.status !== 1) throw new RemoteFileMutationError("protected_path", "Could not evaluate ignored-file policy");
}

function openPinnedParent(root: string, path: string): PinnedParent {
  if (process.platform !== "linux" || !existsSync("/proc/self/fd")) {
    throw new RemoteFileMutationError("unsupported_file", "Safe Project writes require Linux descriptor paths");
  }
  const parts = path.split("/");
  const targetName = parts.pop() as string;
  let descriptor: number;
  try {
    descriptor = openSync(root, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  } catch {
    throw new RemoteFileMutationError("invalid_path", "Could not pin the source root");
  }
  try {
    for (const part of parts) {
      const next = openSync(`/proc/self/fd/${descriptor}/${part}`, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
      closeSync(descriptor);
      descriptor = next;
    }
    const stats = fstatSync(descriptor);
    if (!stats.isDirectory()) throw new Error("not a directory");
    return {
      descriptor,
      procPath: `/proc/self/fd/${descriptor}`,
      identity: `${stats.dev}:${stats.ino}:${targetName}`,
      targetName,
    };
  } catch (error) {
    closeSync(descriptor);
    if ((error as NodeJS.ErrnoException).code === "ELOOP") {
      throw new RemoteFileMutationError("invalid_path", "Project file path contains a symbolic link");
    }
    throw new RemoteFileMutationError("invalid_path", "Project file parent does not exist or is unsupported");
  }
}

function readPinnedFile(parent: PinnedParent): OpenedFile | null {
  let descriptor: number;
  try {
    descriptor = openSync(join(parent.procPath, parent.targetName), constants.O_RDONLY | constants.O_NOFOLLOW);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    if ((error as NodeJS.ErrnoException).code === "ELOOP") {
      throw new RemoteFileMutationError("invalid_path", "Project file target is a symbolic link");
    }
    throw new RemoteFileMutationError("invalid_path", "Project file target cannot be opened safely");
  }
  try {
    const stats = fstatSync(descriptor);
    if (!stats.isFile() || stats.nlink !== 1) {
      throw new RemoteFileMutationError("unsupported_file", "Project file must be a regular file with one link");
    }
    if (stats.size > MAX_FILE_BYTES) {
      throw new RemoteFileMutationError("size_limit_exceeded", `Project file exceeds ${MAX_FILE_BYTES} bytes`);
    }
    const bytes = Buffer.alloc(stats.size);
    let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(descriptor, bytes, offset, bytes.length - offset, offset);
      if (count === 0) break;
      offset += count;
    }
    if (offset !== bytes.length) throw new RemoteFileMutationError("file_changed", "Project file changed while it was read");
    if (bytes.includes(0)) throw new RemoteFileMutationError("unsupported_file", "Binary Project files are unsupported");
    let content: string;
    try {
      content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      throw new RemoteFileMutationError("unsupported_file", "Project file is not valid UTF-8 text");
    }
    const after = fstatSync(descriptor);
    if (after.size !== stats.size || after.mtimeMs !== stats.mtimeMs || after.ino !== stats.ino || after.dev !== stats.dev) {
      throw new RemoteFileMutationError("file_changed", "Project file changed while it was read");
    }
    return { content, hash: sha256ProjectFile(bytes), size: bytes.length, mode: stats.mode & 0o777, dev: stats.dev, ino: stats.ino };
  } finally {
    closeSync(descriptor);
  }
}

function proposedMutation(
  mutation: ProjectFileMutation,
  current: OpenedFile | null,
): { afterContent: string; appliedDiff: string } {
  if (mutation.operation === "create_file") {
    if (current) throw new RemoteFileMutationError("target_exists", "Create target already exists");
    const content = mutation.content as string;
    return { afterContent: content, appliedDiff: createFileDiff(mutation.path, content) };
  }
  if (!current) throw new RemoteFileMutationError("file_changed", "Update target no longer exists");
  if (current.hash !== mutation.expected_base) {
    throw new RemoteFileMutationError("file_changed", "Project file no longer matches expected_base");
  }
  try {
    const applied = applyProjectFilePatch(current.content, mutation.patch as string, mutation.path);
    assertBoundedUtf8(applied.content, "Updated file");
    return { afterContent: applied.content, appliedDiff: applied.appliedDiff };
  } catch (error) {
    if (error instanceof RemoteFileMutationError) throw error;
    if (error instanceof ProjectFilePatchError) {
      throw new RemoteFileMutationError("invalid_patch", error.message);
    }
    throw error;
  }
}

function assertPreviewStillCurrent(mutation: ProjectFileMutation, before: OpenedFile | null, current: OpenedFile | null): void {
  if (mutation.operation === "create_file") {
    if (current) throw new RemoteFileMutationError("target_exists", "Create target appeared during authorization");
    return;
  }
  if (!before || !current || before.hash !== current.hash || before.dev !== current.dev || before.ino !== current.ino) {
    throw new RemoteFileMutationError("file_changed", "Project file changed during authorization");
  }
}

function createPinnedFile(parent: PinnedParent, content: string): void {
  const temp = temporaryName();
  const tempPath = join(parent.procPath, temp);
  const targetPath = join(parent.procPath, parent.targetName);
  let descriptor: number | undefined;
  try {
    descriptor = openSync(tempPath, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o666);
    writeFileSync(descriptor, content, "utf8");
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    linkSync(tempPath, targetPath);
    unlinkSync(tempPath);
    fsyncSync(parent.descriptor);
  } catch (error) {
    if (descriptor !== undefined) closeSync(descriptor);
    try { unlinkSync(tempPath); } catch { /* best effort temporary cleanup */ }
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new RemoteFileMutationError("target_exists", "Create target appeared during the final write");
    }
    throw error;
  }
}

function replacePinnedFile(parent: PinnedParent, expected: OpenedFile, content: string): void {
  const tempPath = join(parent.procPath, temporaryName());
  let descriptor: number | undefined;
  try {
    descriptor = openSync(tempPath, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, expected.mode);
    writeFileSync(descriptor, content, "utf8");
    chmodSync(tempPath, expected.mode);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    const nearWrite = readPinnedFile(parent);
    if (!nearWrite || nearWrite.hash !== expected.hash || nearWrite.dev !== expected.dev || nearWrite.ino !== expected.ino) {
      throw new RemoteFileMutationError("file_changed", "Project file changed at the final write boundary");
    }
    renameSync(tempPath, join(parent.procPath, parent.targetName));
    fsyncSync(parent.descriptor);
  } catch (error) {
    if (descriptor !== undefined) closeSync(descriptor);
    try { unlinkSync(tempPath); } catch { /* best effort temporary cleanup */ }
    throw error;
  }
}

function createFileDiff(path: string, content: string): string {
  if (content === "") return `--- /dev/null\n+++ b/${path}\n`;
  const hasFinalNewline = content.endsWith("\n");
  const lines = content.split("\n");
  if (hasFinalNewline) lines.pop();
  const body = lines.map((line) => `+${line}\n`).join("");
  return `--- /dev/null\n+++ b/${path}\n@@ -0,0 +1,${lines.length} @@\n${body}${hasFinalNewline ? "" : "\\ No newline at end of file\n"}`;
}

async function acquirePathLock(parentIdentity: string, path: string): Promise<() => Promise<void>> {
  preparePrivateDirectory(LOCK_ROOT);
  const target = join(LOCK_ROOT, sha256ProjectFile(`${parentIdentity}\0${basename(path)}`));
  preparePrivateDirectory(target);
  try {
    return await lockfile.lock(target, {
      realpath: false,
      stale: 30_000,
      retries: { retries: 20, factor: 1, minTimeout: 5, maxTimeout: 10 },
    });
  } catch (error) {
    throw new RemoteFileMutationError("operation_unconfirmed", `Could not serialize Project file mutation: ${String(error)}`);
  }
}

function preparePrivateDirectory(path: string): string {
  mkdirSync(path, { recursive: true, mode: 0o700 });
  const stats = lstatSync(path);
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new RemoteFileMutationError("invalid_path", "Private mutation state path is unsafe");
  }
  if (typeof process.getuid === "function" && stats.uid !== process.getuid()) {
    throw new RemoteFileMutationError("invalid_path", "Private mutation state path has the wrong owner");
  }
  chmodSync(path, 0o700);
  return path;
}

function writeJournal(path: string, record: JournalRecord): void {
  const temp = `${path}.${randomBytes(8).toString("hex")}.tmp`;
  let descriptor: number | undefined;
  try {
    descriptor = openSync(temp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    writeFileSync(descriptor, JSON.stringify(record), "utf8");
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    renameSync(temp, path);
    chmodSync(path, 0o600);
    const directory = openSync(dirname(path), constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try { fsyncSync(directory); } finally { closeSync(directory); }
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    try { unlinkSync(temp); } catch { /* renamed or best effort cleanup */ }
  }
}

function readJournal(path: string): JournalRecord | null {
  try {
    const stats = lstatSync(path);
    if (!stats.isFile() || stats.isSymbolicLink() || stats.nlink !== 1 || stats.size > 3 * MAX_FILE_BYTES) {
      throw new RemoteFileMutationError("operation_unconfirmed", "Mutation journal entry is unsafe or invalid");
    }
    const parsed = JSON.parse(readFileSync(path, "utf8")) as JournalRecord;
    if (parsed.schema_version !== 1 || !["prepared", "applied"].includes(parsed.state) || !parsed.result) {
      throw new Error("invalid journal schema");
    }
    return parsed;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    if (error instanceof RemoteFileMutationError) throw error;
    throw new RemoteFileMutationError("operation_unconfirmed", "Mutation journal entry cannot be verified");
  }
}

function assertJournalIdentity(
  journal: JournalRecord,
  mutation: ProjectFileMutation,
  scopeDigest: string,
  payloadDigest: string,
): void {
  if (
    journal.operation_id !== mutation.operation_id
    || journal.scope_digest !== scopeDigest
    || journal.payload_digest !== payloadDigest
  ) {
    throw new RemoteFileMutationError("operation_conflict", "Operation ID was already used for a different mutation");
  }
}

function replayResult(
  result: Omit<RemoteFileMutationResult, "replayed" | "already_applied">,
): RemoteFileMutationResult {
  return { ...result, replayed: true, already_applied: true };
}

function assertBoundedUtf8(value: string, label: string): void {
  if (Buffer.byteLength(value, "utf8") > MAX_FILE_BYTES) {
    throw new RemoteFileMutationError("size_limit_exceeded", `${label} exceeds ${MAX_FILE_BYTES} bytes`);
  }
}

function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item) => {
    if (!item || Array.isArray(item) || typeof item !== "object") return item;
    return Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right)));
  });
}

function temporaryName(): string {
  return `.openmates-write-${process.pid}-${randomBytes(10).toString("hex")}.tmp`;
}

function isInside(root: string, candidate: string): boolean {
  const relation = relative(root, candidate);
  return relation === "" || (!relation.startsWith("..") && !isAbsolute(relation) && resolve(root, relation) === resolve(candidate));
}
