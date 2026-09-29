/** User-initiated, source-local file copy/move. File bytes never traverse the bridge. */

import {
  closeSync, constants, copyFileSync, existsSync, fstatSync, lstatSync,
  mkdirSync, openSync, readdirSync, unlinkSync,
} from "node:fs";
import { basename } from "node:path";
import { spawnSync } from "node:child_process";

import { canonicalProjectSourceRoot } from "./projectSourceRootPolicy.js";
import { loadProjectPathPolicy, ProjectPathAccessError } from "./projectPathPolicy.js";
import { classifyProjectFileReadRisk } from "./projectFileRisk.js";
import { acquireRemoteProjectFileEditLock } from "./remoteCommandSourceLock.js";

export type RemoteFileTransferOperation = "copy_entries" | "move_entries";
export type RemoteFileTransferCode = "invalid_path" | "protected_path" | "target_exists" | "unsupported_file" | "operation_failed" | "source_missing" | "operation_unconfirmed";

export class RemoteFileTransferError extends Error {
  readonly code: RemoteFileTransferCode;

  constructor(code: RemoteFileTransferCode, message: string) {
    super(message);
    this.name = "RemoteFileTransferError";
    this.code = code;
  }
}

export interface RemoteFileTransferResult {
  operation: RemoteFileTransferOperation;
  destination_path: string;
  completed: string[];
  failed: Array<{ path: string; code: RemoteFileTransferCode }>;
}

const MAX_BATCH = 20;
const MAX_FOLDER_ENTRIES = 2_000;
const MAX_FOLDER_DEPTH = 64;
const LINUX_RENAME_NO_REPLACE = `import ctypes,os,sys\nlib=ctypes.CDLL(None,use_errno=True)\nresult=lib.renameat2(3,os.fsencode(sys.argv[1]),4,os.fsencode(sys.argv[2]),1)\nif result:\n sys.stderr.write(str(ctypes.get_errno()))\n sys.exit(1)\n`;

function strictPath(value: unknown, allowRoot = false): string {
  if (allowRoot && value === ".") return ".";
  if (typeof value !== "string" || !value || value.length > 4096 || value.startsWith("/")
    || value.includes("\\") || [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
    || value.split("/").some((part) => !part || part === "." || part === ".." || part.startsWith("."))) {
    throw new RemoteFileTransferError("invalid_path", "File path is outside the visible Project source");
  }
  return value;
}

function policyAllows(root: string, path: string, targetPaths: string[]): void {
  if (path === ".") return;
  if (classifyProjectFileReadRisk(path, []).isHighRisk) {
    throw new RemoteFileTransferError("protected_path", "This Project file is protected");
  }
  try {
    loadProjectPathPolicy(root, { targetPaths }).assertWritablePath(path);
  } catch (error) {
    if (error instanceof ProjectPathAccessError) {
      throw new RemoteFileTransferError("protected_path", "This Project file is ignored or private");
    }
    throw error;
  }
}

function openDirectory(root: string, path: string): number {
  if (process.platform !== "linux" || !existsSync("/proc/self/fd")) {
    throw new RemoteFileTransferError("unsupported_file", "Safe file transfers require Linux descriptor paths");
  }
  let fd: number;
  try {
    fd = openSync(root, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  } catch {
    throw new RemoteFileTransferError("invalid_path", "Project source root is unavailable");
  }
  try {
    for (const part of path === "." ? [] : path.split("/")) {
      const next = openSync(`/proc/self/fd/${fd}/${part}`, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
      closeSync(fd);
      fd = next;
    }
    return fd;
  } catch {
    closeSync(fd);
    throw new RemoteFileTransferError("invalid_path", "Folder is unavailable or contains a symbolic link");
  }
}

function noReplaceMove(fromParent: number, name: string, toParent: number): void {
  // renameat2 with RENAME_NOREPLACE also works for directories. Parent file
  // descriptors are passed as inherited fds, so a renamed ancestor cannot
  // redirect the move outside the approved source root.
  const result = spawnSync("python3", ["-c", LINUX_RENAME_NO_REPLACE, name, name], {
    stdio: ["ignore", "pipe", "pipe", fromParent, toParent],
    timeout: 10_000,
    encoding: "utf8",
  });
  if (result.status === 0) return;
  const errno = Number(result.stderr);
  if (errno === 17) throw new RemoteFileTransferError("target_exists", "Destination already exists");
  if (errno === 18) throw new RemoteFileTransferError("unsupported_file", "Moving across filesystem mounts is unsupported");
  throw new RemoteFileTransferError("operation_failed", "Could not move this Project entry safely");
}

function copyEntry(root: string, sourceParent: number, name: string, destinationParent: number, relativePath: string, destinationRelativePath: string, budget: { entries: number }, depth: number, onCreated?: () => void): void {
  if (++budget.entries > MAX_FOLDER_ENTRIES || depth > MAX_FOLDER_DEPTH) {
    throw new RemoteFileTransferError("unsupported_file", "Folder copy exceeds the safe entry or depth limit");
  }
  policyAllows(root, relativePath, [relativePath]);
  policyAllows(root, destinationRelativePath, [destinationRelativePath]);
  const sourcePath = `/proc/self/fd/${sourceParent}/${name}`;
  const destinationPath = `/proc/self/fd/${destinationParent}/${name}`;
  const before = lstatSync(sourcePath);
  if (before.isSymbolicLink() || (!before.isFile() && !before.isDirectory()) || (before.isFile() && before.nlink !== 1)) {
    throw new RemoteFileTransferError("unsupported_file", "Linked or special files cannot be transferred");
  }
  if (before.isFile()) {
    const sourceFd = openSync(sourcePath, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const pinned = fstatSync(sourceFd);
      if (!pinned.isFile() || pinned.nlink !== 1 || pinned.dev !== before.dev || pinned.ino !== before.ino) {
        throw new RemoteFileTransferError("invalid_path", "Source file changed before copy");
      }
      try {
        copyFileSync(`/proc/self/fd/${sourceFd}`, destinationPath, constants.COPYFILE_EXCL);
      } catch (error) {
        // COPYFILE_EXCL prevents overwrites, but a failed write can leave a
        // partial destination behind. Its contents are then unknown, so make
        // the failure explicit instead of reporting an ordinary retryable error.
        if ((error as NodeJS.ErrnoException).code !== "EEXIST" && existsSync(destinationPath)) {
          throw new RemoteFileTransferError("operation_unconfirmed", "A partial file copy may remain at the destination");
        }
        throw error;
      }
      onCreated?.();
      const after = fstatSync(sourceFd);
      if (after.size !== pinned.size || after.mtimeMs !== pinned.mtimeMs) {
        throw new RemoteFileTransferError("invalid_path", "Source file changed during copy");
      }
    } finally { closeSync(sourceFd); }
    return;
  }
  const sourceFd = openSync(sourcePath, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try {
    const pinned = fstatSync(sourceFd);
    if (pinned.dev !== before.dev || pinned.ino !== before.ino) {
      throw new RemoteFileTransferError("invalid_path", "Source folder changed before copy");
    }
    mkdirSync(destinationPath, { mode: before.mode & 0o777 });
    onCreated?.();
    const destinationFd = openSync(destinationPath, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try {
      for (const child of readdirSync(`/proc/self/fd/${sourceFd}`, { withFileTypes: true })) {
        if (child.name.startsWith(".") || child.isSymbolicLink() || (!child.isFile() && !child.isDirectory())) {
          throw new RemoteFileTransferError("protected_path", "Folder contains hidden, linked, or special entries");
        }
        copyEntry(root, sourceFd, child.name, destinationFd, `${relativePath}/${child.name}`, `${destinationRelativePath}/${child.name}`, budget, depth + 1);
      }
    } finally { closeSync(destinationFd); }
  } finally { closeSync(sourceFd); }
}

function inspectTree(root: string, parent: number, name: string, relativePath: string, budget: { entries: number }, depth: number): void {
  if (++budget.entries > MAX_FOLDER_ENTRIES || depth > MAX_FOLDER_DEPTH) {
    throw new RemoteFileTransferError("unsupported_file", "Folder move exceeds the safe entry or depth limit");
  }
  policyAllows(root, relativePath, [relativePath]);
  const source = `/proc/self/fd/${parent}/${name}`;
  const stat = lstatSync(source);
  if (stat.isSymbolicLink() || (!stat.isFile() && !stat.isDirectory()) || (stat.isFile() && stat.nlink !== 1)) {
    throw new RemoteFileTransferError("unsupported_file", "Linked or special files cannot be transferred");
  }
  if (!stat.isDirectory()) return;
  const fd = openSync(source, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try {
    if (fstatSync(fd).ino !== stat.ino || fstatSync(fd).dev !== stat.dev) {
      throw new RemoteFileTransferError("invalid_path", "Folder changed during validation");
    }
    for (const child of readdirSync(`/proc/self/fd/${fd}`, { withFileTypes: true })) {
      if (child.name.startsWith(".") || child.isSymbolicLink() || (!child.isFile() && !child.isDirectory())) {
        throw new RemoteFileTransferError("protected_path", "Folder contains hidden, linked, or special entries");
      }
      inspectTree(root, fd, child.name, `${relativePath}/${child.name}`, budget, depth + 1);
    }
  } finally { closeSync(fd); }
}

function transferOne(root: string, operation: RemoteFileTransferOperation, path: string, destinationPath: string): void {
  const sourceParentPath = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ".";
  const name = basename(path);
  const sourceParent = openDirectory(root, sourceParentPath);
  const destinationParent = openDirectory(root, destinationPath);
  try {
    const source = `/proc/self/fd/${sourceParent}/${name}`;
    const destination = `/proc/self/fd/${destinationParent}/${name}`;
    const destinationRelativePath = destinationPath === "." ? name : `${destinationPath}/${name}`;
    policyAllows(root, destinationRelativePath, [destinationRelativePath]);
    let before;
    try { before = lstatSync(source); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        throw new RemoteFileTransferError("source_missing", "Source is gone; inspect the destination before retrying");
      }
      throw error;
    }
    if ((!before.isFile() && !before.isDirectory()) || before.isSymbolicLink() || (before.isFile() && before.nlink !== 1)) {
      throw new RemoteFileTransferError("unsupported_file", "Linked or special files cannot be transferred");
    }
    if (existsSync(destination)) throw new RemoteFileTransferError("target_exists", "Destination already exists");
    inspectTree(root, sourceParent, name, path, { entries: 0 }, 0);
    if (operation === "move_entries") {
      noReplaceMove(sourceParent, name, destinationParent);
      return;
    }
    const budget = { entries: 0 };
    let createdByThisRequest = false;
    const createdState: { identity: { dev: number; ino: number; size: number; mtimeMs: number } | null } = { identity: null };
    try {
      copyEntry(root, sourceParent, name, destinationParent, path, destinationRelativePath, budget, 0, () => {
        createdByThisRequest = true;
        const created = lstatSync(destination);
        createdState.identity = { dev: created.dev, ino: created.ino, size: created.size, mtimeMs: created.mtimeMs };
      });
    } catch (error) {
      // Only clean up the entry this request created. A successful collision
      // check never removes a pre-existing destination.
      try {
        if (createdByThisRequest && existsSync(destination)) {
          const current = lstatSync(destination);
          const identity = createdState.identity;
          if (identity && current.dev === identity.dev && current.ino === identity.ino) {
            if (current.isDirectory()) {
              throw new RemoteFileTransferError("operation_unconfirmed", "A partial folder copy remains at the destination");
            }
            if (current.isFile() && current.size === identity.size && current.mtimeMs === identity.mtimeMs) unlinkSync(destination);
          }
        }
      } catch (cleanupError) {
        if (cleanupError instanceof RemoteFileTransferError && cleanupError.code === "operation_unconfirmed") throw cleanupError;
        // Keep the original transfer error when cleanup itself fails.
      }
      throw error;
    }
  } finally {
    closeSync(sourceParent);
    closeSync(destinationParent);
  }
}

export async function executeRemoteFileTransfer(input: {
  sourceRoot: string;
  operation: RemoteFileTransferOperation;
  paths: unknown;
  destinationPath: unknown;
  authorize?: () => Promise<void>;
}): Promise<RemoteFileTransferResult> {
  if (input.operation !== "copy_entries" && input.operation !== "move_entries") {
    throw new RemoteFileTransferError("invalid_path", "Unsupported file transfer");
  }
  if (!Array.isArray(input.paths) || input.paths.length < 1 || input.paths.length > MAX_BATCH) {
    throw new RemoteFileTransferError("invalid_path", "Select up to 20 Project entries");
  }
  const paths = input.paths.map((value) => strictPath(value));
  const destinationPath = strictPath(input.destinationPath, true);
  if (new Set(paths).size !== paths.length || paths.some((path) => paths.some((other) => path !== other && path.startsWith(`${other}/`)))) {
    throw new RemoteFileTransferError("invalid_path", "Selection contains duplicate or nested entries");
  }
  if (paths.some((path) => destinationPath === path || destinationPath.startsWith(`${path}/`))) {
    throw new RemoteFileTransferError("invalid_path", "Cannot transfer a folder into itself");
  }
  const root = canonicalProjectSourceRoot(input.sourceRoot);
  for (const path of paths) policyAllows(root, path, [path]);
  policyAllows(root, destinationPath, [destinationPath]);
  await input.authorize?.();
  const lock = await acquireRemoteProjectFileEditLock(root);
  const completed: string[] = [];
  const failed: RemoteFileTransferResult["failed"] = [];
  try {
    await input.authorize?.();
    for (const path of paths) {
      lock.assertHeld();
      try {
        transferOne(root, input.operation, path, destinationPath);
        completed.push(path);
      } catch (error) {
        failed.push({ path, code: error instanceof RemoteFileTransferError ? error.code
          : (error as NodeJS.ErrnoException)?.code === "EEXIST" ? "target_exists" : "operation_failed" });
      }
    }
  } finally { await lock.release(); }
  return { operation: input.operation, destination_path: destinationPath, completed, failed };
}
