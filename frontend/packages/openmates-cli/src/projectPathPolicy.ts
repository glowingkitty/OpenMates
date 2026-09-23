/** Filesystem-backed Project ignore/private policy with sticky trusted private paths. */

import { createHash, randomBytes } from "node:crypto";
import {
  chmodSync,
  closeSync,
  constants,
  existsSync,
  fstatSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";

import {
  createProjectPathPolicy,
  PROJECT_BUILTIN_PRIVATE_PATHS,
  ProjectPathPolicyError,
  type ProjectIgnoreFile,
  type ProjectPathPolicy,
} from "../../ui/src/utils/projectPathPolicy.js";
import { loadRemoteCommandPermissions, type RemoteCommandPermissions } from "./remoteCommandPermissions.js";
import { canonicalProjectSourceRoot } from "./projectSourceRootPolicy.js";
import { resolveStateDir } from "./storage.js";

const DEFAULT_MAX_IGNORE_FILES = 128;
const DEFAULT_MAX_IGNORE_BYTES = 1024 * 1024;
const MAX_POLICY_ENTRIES = 50_000;
const POLICY_STATE_DIRECTORY = "project-path-policies";

export type ProjectPathAccessErrorCode =
  | "private_path"
  | "ignored_path_requires_approval"
  | "invalid_path_policy";

export class ProjectPathAccessError extends Error {
  readonly code: ProjectPathAccessErrorCode;

  constructor(code: ProjectPathAccessErrorCode, message: string) {
    super(message);
    this.name = "ProjectPathAccessError";
    this.code = code;
  }
}

export interface LoadProjectPathPolicyOptions {
  /** Additional trusted state supplied by a caller outside the command-writable source root. */
  trustedPrivatePaths?: readonly string[];
  stateDirectory?: string;
  maxIgnoreFiles?: number;
  maxIgnoreBytes?: number;
  maxEntries?: number;
  /** Load nested ignore files throughout the searchable tree. Direct operations should use targetPaths. */
  discoverNestedIgnoreFiles?: boolean;
  /** Source-relative paths whose ancestor ignore files are needed for a direct operation. */
  targetPaths?: readonly string[];
}

export interface LoadedProjectPathPolicy extends ProjectPathPolicy {
  sourceRoot: string;
  digest: string;
  /** Private boundary only; ignore edits do not invalidate command approval. */
  privateDigest: string;
  /** Ripgrep exclusions that must be applied before starting content search. */
  rgExclusionGlobs(): readonly string[];
  assertReadablePath(path: string, isIgnoredReadApproved?: (path: string) => boolean): void;
  assertWritablePath(path: string): void;
}

interface StickyPrivatePathState {
  schema_version: 1;
  private_paths: string[];
}

export function loadProjectPathPolicy(
  sourceRoot: string,
  options: LoadProjectPathPolicyOptions = {},
): LoadedProjectPathPolicy {
  try {
    const root = canonicalProjectSourceRoot(sourceRoot, { stateDirectory: options.stateDirectory });
    const policyRoot = findGitPolicyRoot(root);
    const sourcePrefix = normalizeRelative(policyRoot, root);
    const config = loadRemoteCommandPermissions(root) as PermissionsWithFileAccess | null;
    const configured = config?.file_access?.private_paths ?? [];
    const stickyPrivatePaths = updateStickyPrivatePaths(
      root,
      [...configured, ...(options.trustedPrivatePaths ?? [])],
      options.stateDirectory ?? resolveStateDir(),
    );
    const privatePolicy = createProjectPathPolicy({ ignoreFiles: [], privatePaths: stickyPrivatePaths });
    const ignoreFiles = collectIgnoreFiles(policyRoot, root, {
      maxFiles: boundedInteger(options.maxIgnoreFiles, DEFAULT_MAX_IGNORE_FILES, "ignore file"),
      maxBytes: boundedInteger(options.maxIgnoreBytes, DEFAULT_MAX_IGNORE_BYTES, "ignore byte"),
      maxEntries: boundedInteger(options.maxEntries, MAX_POLICY_ENTRIES, "policy entry"),
      discoverNested: options.discoverNestedIgnoreFiles === true,
      targetPaths: options.targetPaths ?? [],
      privatePolicy,
    });
    const gitPolicy = createProjectPathPolicy({ ignoreFiles, privatePaths: [] });

    const sourcePath = (path: string): string => {
      const normalized = normalizeSourceRelativePath(path);
      return sourcePrefix ? `${sourcePrefix}/${normalized}` : normalized;
    };
    const isIgnoredByPattern = (path: string, isDirectory = false) => gitPolicy.isIgnored(sourcePath(path), isDirectory);
    const isPrivateByPattern = (path: string, isDirectory = false) => privatePolicy.isPrivate(path, isDirectory);
    const privateGlobs = [...privatePolicy.privateGlobs()];
    const privateDigest = sha256(stableJson({
      root: sha256(root),
      builtin_private_paths: PROJECT_BUILTIN_PRIVATE_PATHS,
      private_paths: stickyPrivatePaths,
    }));
    const digest = sha256(stableJson({
      private_digest: privateDigest,
      ignore_files: ignoreFiles.map((file) => ({ path: file.path, digest: sha256(file.content) })),
    }));

    const policy: LoadedProjectPathPolicy = {
      sourceRoot: root,
      digest,
      privateDigest,
      isIgnored(path, isDirectory = false) {
        const normalized = normalizeSourceRelativePath(path);
        return isIgnoredByPattern(normalized, isDirectory);
      },
      isPrivate(path, isDirectory = false) {
        const normalized = normalizeSourceRelativePath(path);
        return isPrivateByPattern(normalized, isDirectory);
      },
      privateGlobs() {
        return privateGlobs;
      },
      rgExclusionGlobs() {
        return privateGlobs;
      },
      assertReadablePath(path, isIgnoredReadApproved) {
        const normalized = normalizeSourceRelativePath(path);
        if (policy.isPrivate(normalized)) throw new ProjectPathAccessError("private_path", "Project path is protected and private");
        if (policy.isIgnored(normalized) && isIgnoredReadApproved?.(normalized) !== true) {
          throw new ProjectPathAccessError("ignored_path_requires_approval", "Project path is ignored and requires explicit approval");
        }
      },
      assertWritablePath(path) {
        const normalized = normalizeSourceRelativePath(path);
        if (policy.isPrivate(normalized) || policy.isIgnored(normalized)) {
          throw new ProjectPathAccessError("private_path", "Project path is protected");
        }
      },
    };
    return policy;
  } catch (error) {
    if (error instanceof ProjectPathAccessError) throw error;
    const detail = error instanceof Error ? error.message : String(error);
    throw new ProjectPathAccessError("invalid_path_policy", `Could not load Project path policy: ${detail}`);
  }
}

type PermissionsWithFileAccess = RemoteCommandPermissions & {
  file_access?: { private_paths: string[] };
};

function findGitPolicyRoot(sourceRoot: string): string {
  let current = sourceRoot;
  while (true) {
    if (existsSync(join(current, ".git"))) return current;
    const parent = dirname(current);
    if (parent === current) return sourceRoot;
    current = parent;
  }
}

function collectIgnoreFiles(
  policyRoot: string,
  sourceRoot: string,
  limits: {
    maxFiles: number;
    maxBytes: number;
    maxEntries: number;
    discoverNested: boolean;
    targetPaths: readonly string[];
    privatePolicy: ProjectPathPolicy;
  },
): ProjectIgnoreFile[] {
  const files: ProjectIgnoreFile[] = [];
  let bytes = 0;
  let entries = 0;
  const add = (path: string) => {
    if (!existsSync(path)) return;
    const stat = lstatSync(path);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`${path} must be a regular ignore file`);
    if (++entries > limits.maxEntries || files.length >= limits.maxFiles || bytes + stat.size > limits.maxBytes) {
      throw new Error("Project ignore policy exceeds its bounded load limits");
    }
    const content = readBoundedRegularFile(path, limits.maxBytes - bytes);
    bytes += Buffer.byteLength(content);
    files.push({ path: normalizeRelative(policyRoot, path), content });
  };

  const chain: string[] = [];
  let current = sourceRoot;
  while (true) {
    chain.push(current);
    if (current === policyRoot) break;
    const parent = dirname(current);
    if (parent === current || !isInside(policyRoot, parent)) throw new Error("Source root is outside its Git policy root");
    current = parent;
  }
  for (const directory of chain.reverse()) add(join(directory, ".gitignore"));

  for (const target of limits.targetPaths) {
    const normalized = target === "." ? "" : normalizeSourceRelativePath(target);
    const absolute = normalized ? resolve(sourceRoot, normalized) : sourceRoot;
    if (!isInside(sourceRoot, absolute)) throw new Error("Project policy target escapes its source root");
    const targetIsDirectory = existsSync(absolute) && lstatSync(absolute).isDirectory();
    let directory = targetIsDirectory ? absolute : dirname(absolute);
    const ancestors: string[] = [];
    while (isInside(sourceRoot, directory)) {
      ancestors.push(directory);
      if (directory === sourceRoot) break;
      directory = dirname(directory);
    }
    for (const ancestor of ancestors.reverse()) {
      const ignorePath = join(ancestor, ".gitignore");
      if (!files.some((file) => file.path === normalizeRelative(policyRoot, ignorePath))) add(ignorePath);
    }
  }

  if (!limits.discoverNested) return files;

  const directories = [sourceRoot];
  const seen = new Set(chain.map((directory) => realpathSync(directory)));
  let currentPolicy = createProjectPathPolicy({ ignoreFiles: files, privatePaths: [] });
  while (directories.length > 0) {
    const directory = directories.pop() as string;
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (++entries > limits.maxEntries) throw new Error("Project path policy scan exceeds its entry limit");
      if (entry.name === ".git" || entry.isSymbolicLink() || !entry.isDirectory()) continue;
      const child = join(directory, entry.name);
      const canonical = realpathSync(child);
      if (!isInside(sourceRoot, canonical) || seen.has(canonical)) continue;
      const sourceRelative = normalizeRelative(sourceRoot, child);
      const policyRelative = normalizeRelative(policyRoot, child);
      if (limits.privatePolicy.isPrivate(sourceRelative, true) || currentPolicy.isIgnored(policyRelative, true)) continue;
      seen.add(canonical);
      const before = files.length;
      add(join(child, ".gitignore"));
      if (files.length !== before) currentPolicy = createProjectPathPolicy({ ignoreFiles: files, privatePaths: [] });
      directories.push(child);
    }
  }
  return files;
}

function updateStickyPrivatePaths(sourceRoot: string, additions: readonly string[], stateDirectory: string): string[] {
  const stateRoot = resolve(stateDirectory, POLICY_STATE_DIRECTORY);
  if (isInside(sourceRoot, stateRoot) || isInside(stateRoot, sourceRoot)) {
    throw new Error("Project path policy state must stay outside the source root");
  }
  const key = sha256(realpathSync(sourceRoot));
  const path = join(stateRoot, `${key}.json`);
  if (additions.length === 0 && !existsSync(path)) return [];
  preparePrivateDirectory(stateRoot);
  const lock = join(stateRoot, `${key}.lock`);
  try {
    mkdirSync(lock, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") throw new Error("Project path policy state is busy");
    throw error;
  }
  try {
    const current = readStickyState(path);
    const privatePaths = [...new Set([...current.private_paths, ...additions])].sort();
    // Validate every persisted pattern through the shared strict parser before writing it.
    createProjectPathPolicy({ ignoreFiles: [], privatePaths });
    writePrivateJson(path, { schema_version: 1, private_paths: privatePaths });
    return privatePaths;
  } finally {
    rmSync(lock, { recursive: true, force: true });
  }
}

function readStickyState(path: string): StickyPrivatePathState {
  if (!existsSync(path)) return { schema_version: 1, private_paths: [] };
  const source = readBoundedRegularFile(path, 256 * 1024);
  const parsed = JSON.parse(source) as Partial<StickyPrivatePathState>;
  if (parsed.schema_version !== 1 || !Array.isArray(parsed.private_paths)
    || parsed.private_paths.some((item) => typeof item !== "string")) {
    throw new Error("Stored Project private-path policy is invalid");
  }
  return { schema_version: 1, private_paths: parsed.private_paths };
}

function writePrivateJson(path: string, value: StickyPrivatePathState): void {
  const temp = `${path}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`;
  let descriptor: number | undefined;
  try {
    descriptor = openSync(temp, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600);
    const content = Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
    writeSync(descriptor, content, 0, content.length, 0);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    chmodSync(temp, 0o600);
    renameSync(temp, path);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    try { unlinkSync(temp); } catch { /* Atomic rename already consumed it. */ }
  }
}

function readBoundedRegularFile(path: string, maxBytes: number): string {
  let descriptor: number | undefined;
  try {
    descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    const stat = fstatSync(descriptor);
    if (!stat.isFile() || stat.size > maxBytes) throw new Error(`${path} is not a bounded regular file`);
    const buffer = Buffer.alloc(stat.size);
    const bytes = readSync(descriptor, buffer, 0, stat.size, 0);
    return buffer.subarray(0, bytes).toString("utf8");
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}

function preparePrivateDirectory(path: string): void {
  mkdirSync(path, { recursive: true, mode: 0o700 });
  chmodSync(path, 0o700);
  if (!statSync(path).isDirectory()) throw new Error("Project path policy state is not a directory");
}

function normalizeSourceRelativePath(value: string): string {
  if (typeof value !== "string" || !value || value.includes("\\") || isAbsolute(value)
    || value.split("/").some((part) => !part || part === "." || part === "..")
    || [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) {
    throw new ProjectPathPolicyError(`Project path is invalid: ${String(value)}`);
  }
  return value;
}

function normalizeRelative(root: string, target: string): string {
  const result = relative(root, target).split("\\").join("/");
  if (!result || result === ".") return "";
  if (result.startsWith("../") || result === ".." || isAbsolute(result)) throw new Error("Project policy path escapes its root");
  return result;
}

function boundedInteger(value: number | undefined, fallback: number, label: string): number {
  const result = value ?? fallback;
  if (!Number.isInteger(result) || result < 1 || result > fallback) throw new Error(`Invalid ${label} limit`);
  return result;
}

function isInside(root: string, candidate: string): boolean {
  const relation = relative(resolve(root), resolve(candidate));
  return relation === "" || (!relation.startsWith("..") && !isAbsolute(relation));
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item) => {
    if (!item || Array.isArray(item) || typeof item !== "object") return item;
    return Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right)));
  });
}
