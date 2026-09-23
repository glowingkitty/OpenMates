/** Per-execution AppArmor policy lease for commands inside a bubblewrap sandbox.
 *
 * The privileged broker accepts a bounded semantic deny specification, never
 * caller-provided AppArmor text, parser flags, profile names or output paths.
 */

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { lstatSync, readFileSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, relative } from "node:path";

export const REMOTE_COMMAND_APPARMOR_BROKER = "/usr/libexec/openmates-command-apparmor";
export const REMOTE_COMMAND_APPARMOR_EXEC = "/usr/bin/aa-exec";
export const REMOTE_COMMAND_BWRAP = "/usr/libexec/openmates-bwrap";
export const REMOTE_COMMAND_GIT_CONFIG_MASK = "/usr/libexec/openmates-git-config-mask.so";
const SUDO = "/usr/bin/sudo";
const BROKER_TIMEOUT_MS = 10_000;
const MAX_BROKER_OUTPUT_BYTES = 64 * 1024;
const MAX_BROKER_REQUEST_BYTES = 256 * 1024;
const MAX_POLICY_GLOBS = 256;
const MAX_POLICY_PATHS = 1_024;
const MAX_POLICY_PATH_BYTES = 512;

export interface RemoteCommandAppArmorPath {
  path: string;
  kind: "file" | "directory";
}

export interface RemoteCommandAppArmorPolicyInput {
  execution_id: string;
  source_root: string;
  private_policy_digest: string;
  private_globs: readonly string[];
  exact_private_aliases: readonly Readonly<RemoteCommandAppArmorPath>[];
  exact_readonly_paths: readonly Readonly<RemoteCommandAppArmorPath>[];
}

export interface CanonicalRemoteCommandAppArmorPolicy {
  protocol_version: 1;
  execution_id: string;
  project_root_digest: string;
  private_policy_digest: string;
  private_globs: string[];
  exact_private_aliases: RemoteCommandAppArmorPath[];
  exact_readonly_paths: RemoteCommandAppArmorPath[];
}

export interface RemoteCommandAppArmorCapability {
  supported: boolean;
  reason?: string;
}

export interface RemoteCommandAppArmorConfinement {
  profile_name: string;
  definition_digest: string;
  sandbox_command: { executable: string; args: string[] };
  sandbox_environment: { LD_PRELOAD: string };
  dispose(): Promise<void>;
}

export type RemoteCommandAppArmorBrokerRequest = (CanonicalRemoteCommandAppArmorPolicy & {
  action: "prepare";
}) | {
  protocol_version: 1;
  action: "release";
  lease_id: string;
  definition_digest: string;
};

export type RemoteCommandAppArmorBrokerRunner = (request: RemoteCommandAppArmorBrokerRequest) => Promise<unknown>;

export interface RemoteCommandAppArmorOptions {
  brokerPath?: string;
  aaExecPath?: string;
  bwrapPath?: string;
  gitConfigMaskPath?: string;
  runBroker?: RemoteCommandAppArmorBrokerRunner;
}

export function inspectRemoteCommandAppArmorCapability(
  options: Pick<RemoteCommandAppArmorOptions, "brokerPath" | "aaExecPath" | "bwrapPath" | "gitConfigMaskPath"> = {},
): RemoteCommandAppArmorCapability {
  if (process.platform !== "linux") return { supported: false, reason: `AppArmor command confinement is not implemented for ${process.platform}` };
  try {
    if (readFileSync("/sys/module/apparmor/parameters/enabled", "utf8").trim() !== "Y") {
      return { supported: false, reason: "AppArmor is not enabled" };
    }
    assertTrustedRootExecutable(options.aaExecPath ?? REMOTE_COMMAND_APPARMOR_EXEC, "aa-exec");
    assertTrustedRootExecutable(options.brokerPath ?? REMOTE_COMMAND_APPARMOR_BROKER, "AppArmor broker");
    assertTrustedRootExecutable(options.bwrapPath ?? REMOTE_COMMAND_BWRAP, "OpenMates bubblewrap launcher");
    assertTrustedRootExecutable(options.gitConfigMaskPath ?? REMOTE_COMMAND_GIT_CONFIG_MASK, "Git config compatibility library");
    assertTrustedRootExecutable(SUDO, "sudo");
    return { supported: true };
  } catch (error) {
    return { supported: false, reason: error instanceof Error ? error.message : "AppArmor command confinement is unavailable" };
  }
}

export function canonicalRemoteCommandAppArmorPolicy(
  input: RemoteCommandAppArmorPolicyInput,
): CanonicalRemoteCommandAppArmorPolicy {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(input.execution_id)) throw new Error("Invalid AppArmor execution ID");
  if (!/^[a-f0-9]{64}$/.test(input.private_policy_digest)) throw new Error("Invalid AppArmor private-policy digest");
  const root = realpathSync(input.source_root);
  if (!statSync(root).isDirectory()) throw new Error("AppArmor Project root must be a directory");
  const privateGlobs = canonicalStrings(input.private_globs, "private glob", validatePolicyGlob);
  const privateAliases = canonicalPaths(input.exact_private_aliases, "private alias");
  const readonlyPaths = canonicalPaths(input.exact_readonly_paths, "readonly path");
  if (privateGlobs.length > MAX_POLICY_GLOBS) throw new Error(`AppArmor command policy exceeds ${MAX_POLICY_GLOBS} private patterns`);
  if (privateAliases.length > MAX_POLICY_PATHS || readonlyPaths.length > MAX_POLICY_PATHS) {
    throw new Error(`AppArmor command policy exceeds ${MAX_POLICY_PATHS} exact paths per class`);
  }
  const policy: CanonicalRemoteCommandAppArmorPolicy = {
    protocol_version: 1,
    execution_id: input.execution_id,
    project_root_digest: sha256(root),
    private_policy_digest: input.private_policy_digest,
    private_globs: privateGlobs,
    exact_private_aliases: privateAliases,
    exact_readonly_paths: readonlyPaths,
  };
  if (Buffer.byteLength(JSON.stringify({ ...policy, action: "prepare" })) > MAX_BROKER_REQUEST_BYTES) {
    throw new Error("AppArmor command policy exceeds the broker request limit");
  }
  return policy;
}

export async function prepareRemoteCommandAppArmorConfinement(
  input: RemoteCommandAppArmorPolicyInput,
  toolchainPaths: readonly string[],
  options: RemoteCommandAppArmorOptions = {},
): Promise<RemoteCommandAppArmorConfinement> {
  const aaExec = realpathSync(options.aaExecPath ?? REMOTE_COMMAND_APPARMOR_EXEC);
  const gitConfigMask = realpathSync(options.gitConfigMaskPath ?? REMOTE_COMMAND_GIT_CONFIG_MASK);
  if (!toolchainPaths.some((root) => isInside(realpathSync(root), aaExec))) {
    throw new Error(`AppArmor confinement requires ${aaExec} in an approved toolchain`);
  }
  if (!toolchainPaths.some((root) => isInside(realpathSync(root), gitConfigMask))) {
    throw new Error(`Git config compatibility requires ${gitConfigMask} in an approved toolchain`);
  }
  const policy = canonicalRemoteCommandAppArmorPolicy(input);
  const runBroker = options.runBroker ?? createDefaultBrokerRunner(options.brokerPath ?? REMOTE_COMMAND_APPARMOR_BROKER);
  const response = brokerRecord(await runBroker({
    ...policy,
    action: "prepare",
  }), "prepare");
  const definitionDigest = brokerIdentifier(response.definition_digest, "definition_digest", /^[a-f0-9]{64}$/);
  const uid = process.getuid?.();
  if (!Number.isSafeInteger(uid) || (uid as number) <= 0) throw new Error("AppArmor confinement requires a non-root Unix user");
  const expectedProfileName = `openmates-command.${uid}.${definitionDigest}`;
  const profileName = brokerIdentifier(response.profile_name, "profile_name", /^openmates-command\.[0-9]+\.[a-f0-9]{64}$/);
  const leaseId = brokerIdentifier(response.lease_id, "lease_id", /^[A-Za-z0-9][A-Za-z0-9._:-]{15,191}$/);
  if (profileName !== expectedProfileName || response.private_policy_digest !== policy.private_policy_digest) {
    throw new Error("AppArmor broker prepared a profile for a different command policy");
  }

  let disposed = false;
  return {
    profile_name: profileName,
    definition_digest: definitionDigest,
    sandbox_command: { executable: aaExec, args: ["--profile", profileName] },
    sandbox_environment: { LD_PRELOAD: gitConfigMask },
    dispose: async () => {
      if (disposed) return;
      const released = brokerRecord(await runBroker({
        protocol_version: 1,
        action: "release",
        lease_id: leaseId,
        definition_digest: definitionDigest,
      }), "release");
      if (released.definition_digest !== definitionDigest
        || released.released !== false
        || released.retained !== true) {
        throw new Error("AppArmor broker did not safely retain the immutable command profile");
      }
      disposed = true;
    },
  };
}

function createDefaultBrokerRunner(brokerPath: string): RemoteCommandAppArmorBrokerRunner {
  const broker = realpathSync(brokerPath);
  assertTrustedRootExecutable(broker, "AppArmor broker");
  assertTrustedRootExecutable(SUDO, "sudo");
  return async (request) => {
    const child = spawn(SUDO, ["-n", "--", broker], {
      env: { PATH: "/usr/sbin:/usr/bin:/sbin:/bin", LANG: "C.UTF-8", LC_ALL: "C.UTF-8" },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let exceeded = false;
    const append = (current: string, chunk: Buffer): string => {
      const next = current + chunk.toString("utf8");
      if (Buffer.byteLength(next) > MAX_BROKER_OUTPUT_BYTES) {
        exceeded = true;
        child.kill("SIGKILL");
      }
      return next.slice(0, MAX_BROKER_OUTPUT_BYTES);
    };
    child.stdout.on("data", (chunk: Buffer) => { stdout = append(stdout, chunk); });
    child.stderr.on("data", (chunk: Buffer) => { stderr = append(stderr, chunk); });
    child.stdin.end(`${JSON.stringify(request)}\n`);
    const result = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolvePromise, reject) => {
      const timer = setTimeout(() => child.kill("SIGKILL"), BROKER_TIMEOUT_MS);
      child.once("error", (error) => { clearTimeout(timer); reject(error); });
      child.once("close", (code, signal) => { clearTimeout(timer); resolvePromise({ code, signal }); });
    });
    if (exceeded) throw new Error("AppArmor broker output exceeded its limit");
    if (result.code !== 0) {
      let detail = stderr.trim().slice(0, 1_000);
      try {
        const reported = JSON.parse(stdout) as { error?: unknown; message?: unknown };
        if (reported.error === "confinement_unavailable" && typeof reported.message === "string") {
          detail = reported.message.slice(0, 1_000);
        }
      } catch {
        // A failed broker may produce no JSON; retain the bounded stderr detail.
      }
      detail ||= `exit ${result.signal ?? result.code ?? "unknown"}`;
      throw new Error(`AppArmor broker failed: ${detail}`);
    }
    try {
      return JSON.parse(stdout);
    } catch {
      throw new Error("AppArmor broker returned invalid JSON");
    }
  };
}

function canonicalPaths(values: readonly Readonly<RemoteCommandAppArmorPath>[], context: string): RemoteCommandAppArmorPath[] {
  if (!Array.isArray(values)) throw new Error(`Invalid AppArmor ${context} paths`);
  const paths = values.map((item) => {
    if (!item || (item.kind !== "file" && item.kind !== "directory")) throw new Error(`Invalid AppArmor ${context}`);
    return { path: validateProjectPath(item.path, context), kind: item.kind };
  });
  paths.sort((left, right) => left.path.localeCompare(right.path) || left.kind.localeCompare(right.kind));
  if (new Set(paths.map((item) => item.path)).size !== paths.length) throw new Error(`Duplicate AppArmor ${context}`);
  return paths;
}

function canonicalStrings(
  values: readonly string[],
  context: string,
  validate: (value: string, context: string) => string,
): string[] {
  if (!Array.isArray(values)) throw new Error(`Invalid AppArmor ${context}s`);
  const result = values.map((value) => validate(value, context)).sort();
  if (new Set(result).size !== result.length) throw new Error(`Duplicate AppArmor ${context}`);
  return result;
}

function validatePolicyGlob(value: string, context: string): string {
  const normalized = typeof value === "string" ? value.replace(/^\.\//, "") : value;
  if (typeof normalized !== "string" || !normalized || Buffer.byteLength(normalized) > MAX_POLICY_PATH_BYTES
    || normalized.startsWith("/") || normalized.startsWith("!") || normalized.includes("\\")
    || normalized.split("/").some((part) => !part || part === "." || part === "..") || hasControl(normalized)) {
    throw new Error(`Invalid AppArmor ${context}`);
  }
  return normalized;
}

function validateProjectPath(value: string, context: string): string {
  if (typeof value !== "string" || !value || Buffer.byteLength(value) > MAX_POLICY_PATH_BYTES
    || isAbsolute(value) || value.includes("\\") || value.includes("*") || value.includes("?")
    || value.split("/").some((part) => !part || part === "." || part === "..") || hasControl(value)) {
    throw new Error(`Invalid AppArmor ${context} path`);
  }
  return value;
}

function assertTrustedRootExecutable(path: string, label: string): void {
  const link = lstatSync(path);
  if (link.isSymbolicLink()) throw new Error(`${label} must not be a symbolic link: ${path}`);
  const stat = statSync(path);
  if (!stat.isFile() || stat.uid !== 0 || (stat.mode & 0o022) !== 0 || (stat.mode & 0o111) === 0) {
    throw new Error(`${label} is not a trusted root-owned executable: ${path}`);
  }
}

function brokerRecord(value: unknown, action: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`AppArmor broker returned an invalid ${action} response`);
  return value as Record<string, unknown>;
}

function brokerIdentifier(value: unknown, context: string, pattern: RegExp): string {
  if (typeof value !== "string" || !pattern.test(value)) throw new Error(`AppArmor broker returned an invalid ${context}`);
  return value;
}

function isInside(root: string, candidate: string): boolean {
  const path = relative(root, candidate);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}

function hasControl(value: string): boolean {
  return [...value].some((character) => {
    const code = character.charCodeAt(0);
    return code < 32 || code === 127;
  });
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}
