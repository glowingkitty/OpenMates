/** Cross-process Project source coordination backed by Linux flock(2).
 *
 * File mutations take a shared lock only for their final commit boundary.
 * Source-writing commands run under the exclusive lock. V1 deliberately uses
 * one per-user lock: file edits may run together, while a source-writing
 * command serializes against every OpenMates file commit and source-writing
 * command. This conservative scope safely covers nested roots and aliases.
 * There is no stale timestamp or TTL: the kernel releases a lock only after
 * its owning open-file descriptions close. External editors do not participate.
 */

import { closeSync, constants, lstatSync, mkdirSync, openSync, realpathSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, spawnSync } from "node:child_process";

export interface RemoteProjectSourceLockCapability {
  supported: boolean;
  reason?: string;
}

export interface RemoteProjectFileEditLock {
  lock_path: string;
  assertHeld(): void;
  release(): Promise<void>;
}

export interface WrappedRemoteProjectSourceCommand {
  executable: string;
  args: string[];
  lock_path: string;
}

export class RemoteProjectSourceLockError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RemoteProjectSourceLockError";
  }
}

const FLOCK = "/usr/bin/flock";
const SETPRIV = "/usr/bin/setpriv";
const SHELL = "/bin/sh";
const LOCK_READY_BYTE = 0;
const LOCK_ACQUIRE_TIMEOUT_MS = 30_000;

export function inspectRemoteProjectSourceLockCapability(): RemoteProjectSourceLockCapability {
  if (process.platform !== "linux") return { supported: false, reason: `Project source locks are not implemented for ${process.platform}` };
  for (const executable of [FLOCK, SETPRIV, SHELL]) {
    try {
      if (!statSync(executable).isFile()) return { supported: false, reason: `${executable} is unavailable` };
    } catch {
      return { supported: false, reason: `${executable} is unavailable` };
    }
  }
  const result = spawnSync(SETPRIV, ["--pdeathsig", "KILL", "--", FLOCK, "--version"], { encoding: "utf8", timeout: 5_000 });
  if (result.status !== 0) return { supported: false, reason: (result.stderr || result.error?.message || "flock probe failed").trim() };
  return { supported: true };
}

export async function acquireRemoteProjectFileEditLock(
  sourceRoot: string,
  options: { timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<RemoteProjectFileEditLock> {
  const capability = inspectRemoteProjectSourceLockCapability();
  if (!capability.supported) throw new RemoteProjectSourceLockError(capability.reason ?? "Project source locking is unavailable");
  const lockPath = remoteProjectSourceLockPath(sourceRoot);
  const timeoutMs = options.timeoutMs ?? LOCK_ACQUIRE_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 5 * 60 * 1000) throw new RemoteProjectSourceLockError("Invalid Project lock timeout");
  if (options.signal?.aborted) throw new RemoteProjectSourceLockError("Project lock acquisition was canceled");

  // setpriv makes parent death kill the eventual fixed shell. flock --no-fork
  // execs that shell while retaining the shared lock descriptor. Closing stdin
  // makes the shell exit and releases the descriptor deterministically.
  const child = spawn(SETPRIV, [
    "--pdeathsig", "KILL", "--",
    FLOCK, "--no-fork", "--shared", lockPath,
    SHELL, "-c", `printf '\\000'; cat >/dev/null`,
  ], { stdio: ["pipe", "pipe", "pipe"] });

  let released = false;
  let lostError: RemoteProjectSourceLockError | null = null;
  let timer: NodeJS.Timeout | null = null;
  let abortListener: (() => void) | null = null;
  await new Promise<void>((resolvePromise, reject) => {
    let stderr = "";
    const onError = (error: Error) => fail(`Failed to start Project lock holder: ${error.message}`);
    const onExit = (code: number | null, signal: NodeJS.Signals | null) => fail(`Project lock holder exited before acquisition (${signal ?? code}): ${stderr.trim()}`);
    const cleanup = () => {
      if (timer) clearTimeout(timer);
      if (abortListener && options.signal) options.signal.removeEventListener("abort", abortListener);
      child.removeListener("error", onError);
      child.removeListener("exit", onExit);
    };
    const fail = (message: string) => {
      cleanup();
      child.kill("SIGKILL");
      reject(new RemoteProjectSourceLockError(message));
    };
    child.stderr.on("data", (chunk: Buffer) => { stderr = `${stderr}${chunk.toString("utf8")}`.slice(-2_000); });
    child.once("error", onError);
    child.once("exit", onExit);
    child.stdout.once("data", (chunk: Buffer) => {
      if (chunk[0] !== LOCK_READY_BYTE) return fail("Project lock holder returned an invalid readiness signal");
      cleanup();
      resolvePromise();
    });
    timer = setTimeout(() => fail(`Timed out waiting ${timeoutMs}ms for the Project file-edit lock`), timeoutMs);
    if (options.signal) {
      abortListener = () => fail("Project lock acquisition was canceled");
      options.signal.addEventListener("abort", abortListener, { once: true });
    }
  });
  child.once("error", (error) => {
    if (!released) lostError = new RemoteProjectSourceLockError(`Project file-edit lock holder failed: ${error.message}`);
  });
  child.once("exit", (code, signal) => {
    if (!released) lostError = new RemoteProjectSourceLockError(`Project file-edit lock was lost (${signal ?? code})`);
  });

  return {
    lock_path: lockPath,
    assertHeld: () => {
      if (released) throw new RemoteProjectSourceLockError("Project file-edit lock was already released");
      if (lostError) throw lostError;
    },
    release: async () => {
      if (released) return;
      released = true;
      child.stdin.end();
      await new Promise<void>((resolvePromise) => {
        if (child.exitCode !== null || child.signalCode !== null) return resolvePromise();
        const timer = setTimeout(() => { child.kill("SIGKILL"); resolvePromise(); }, 2_000);
        child.once("exit", () => { clearTimeout(timer); resolvePromise(); });
      });
    },
  };
}

export function wrapRemoteProjectSourceCommand(
  sourceRoot: string,
  executable: string,
  args: readonly string[],
): WrappedRemoteProjectSourceCommand {
  const capability = inspectRemoteProjectSourceLockCapability();
  if (!capability.supported) throw new RemoteProjectSourceLockError(capability.reason ?? "Project source locking is unavailable");
  const lockPath = remoteProjectSourceLockPath(sourceRoot);
  const sandboxArgs = executable === "/usr/bin/bwrap" && !args.includes("--preserve-fds")
    ? ["--preserve-fds", "1", ...args]
    : [...args];
  return {
    executable: SETPRIV,
    args: [
      "--pdeathsig", "KILL", "--",
      FLOCK, "--no-fork", "--exclusive", lockPath,
      executable, ...sandboxArgs,
    ],
    lock_path: lockPath,
  };
}

export function remoteProjectSourceLockPath(sourceRoot: string): string {
  const root = realpathSync(sourceRoot);
  const stat = statSync(root);
  if (!stat.isDirectory()) throw new RemoteProjectSourceLockError("Project source root must be a directory");
  const uid = typeof process.getuid === "function" ? process.getuid() : null;
  if (uid === null) throw new RemoteProjectSourceLockError("Project source locks require a numeric user identity");
  const directory = join(tmpdir(), `openmates-project-source-locks-${uid}`);
  preparePrivateDirectory(directory, uid);
  const lockPath = join(directory, "source-writes.lock");
  const descriptor = openSync(lockPath, constants.O_CREAT | constants.O_RDWR | constants.O_NOFOLLOW, 0o600);
  closeSync(descriptor);
  const lockStat = lstatSync(lockPath);
  if (!lockStat.isFile() || lockStat.isSymbolicLink() || lockStat.uid !== uid || (lockStat.mode & 0o077) !== 0) {
    throw new RemoteProjectSourceLockError("Project source lockfile is not private and trustworthy");
  }
  return lockPath;
}

function preparePrivateDirectory(path: string, uid: number): void {
  try {
    mkdirSync(path, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const stat = lstatSync(path);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== uid || (stat.mode & 0o077) !== 0) {
    throw new RemoteProjectSourceLockError("Project source lock directory is not private and trustworthy");
  }
}
