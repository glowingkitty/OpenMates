/** Managed, OS-confined remote command execution for a single authorized Project. */

import { createHash, randomUUID } from "node:crypto";
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync, lstatSync, readdirSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import type { Readable } from "node:stream";

import {
  matchEnabledRemoteCommandPreset,
  type ActiveRemoteCommandPresetGrant,
  type RemoteCommandPermissions,
  type RemoteCommandPolicy,
} from "./remoteCommandPermissions.js";
import { RemoteProjectSourceLockError, wrapRemoteProjectSourceCommand } from "./remoteCommandSourceLock.js";
import { classifyProjectFileReadRisk } from "./projectFileRisk.js";
import {
  canonicalOpenMatesStateDirectory,
  canonicalProjectSourceRoot,
} from "./projectSourceRootPolicy.js";
import { loadProjectPathPolicy, type LoadedProjectPathPolicy } from "./projectPathPolicy.js";
import {
  inspectRemoteCommandAppArmorCapability,
  prepareRemoteCommandAppArmorConfinement,
  REMOTE_COMMAND_BWRAP,
  type RemoteCommandAppArmorConfinement,
} from "./remoteCommandAppArmor.js";

export type RemoteCommandStatus = "authorizing" | "running" | "succeeded" | "failed" | "stopped" | "timed_out";

export type RemoteCommandErrorCode =
  | "invalid_request"
  | "duplicate_execution"
  | "approval_required"
  | "invalid_approval"
  | "authority_revoked"
  | "resource_not_granted"
  | "coordination_required"
  | "unsupported_platform"
  | "confinement_unavailable"
  | "network_profile_unavailable"
  | "credential_unavailable"
  | "launch_failed"
  | "unknown_execution";

export class RemoteCommandError extends Error {
  readonly code: RemoteCommandErrorCode;

  constructor(code: RemoteCommandErrorCode, message: string) {
    super(message);
    this.name = "RemoteCommandError";
    this.code = code;
  }
}

export interface RemoteCommandWritableTarget {
  profile_id: string;
  purpose: "cache" | "output";
  host_path: string;
}

export interface RemoteCommandNetworkClaim {
  profile_id: string;
  destinations: string[];
}

export interface RemoteCommandCredentialClaim {
  profile_id: string;
  environment: string[];
}

export interface RemoteCommandRequest {
  execution_id?: string;
  project_id: string;
  source_root: string;
  policy: RemoteCommandPolicy;
  toolchain_paths: string[];
  writable_targets: RemoteCommandWritableTarget[];
  network: RemoteCommandNetworkClaim | null;
  credentials: RemoteCommandCredentialClaim[];
}

export interface RemoteCommandPreflight {
  execution_id: string;
  project_id: string;
  source_root: string;
  request_digest: string;
  policy: Readonly<RemoteCommandPolicy>;
  toolchain_paths: readonly string[];
  writable_targets: readonly Readonly<RemoteCommandWritableTarget>[];
  network: Readonly<RemoteCommandNetworkClaim> | null;
  credentials: readonly Readonly<RemoteCommandCredentialClaim>[];
  /** Sticky effective private-path policy, pinned into the exact approval digest. */
  path_policy_digest: string;
  /** Conservative live path-denial patterns installed by the trusted AppArmor broker. */
  private_path_globs: readonly string[];
  /** Existing credential/control paths hidden from the sandbox source mount. */
  masked_project_paths: readonly Readonly<{ path: string; kind: "file" | "directory" }>[];
  /** In-Project policy and agent rule paths kept immutable for source-writing commands. */
  protected_project_paths: readonly Readonly<{ path: string; kind: "file" | "directory" }>[];
}

export type RemoteCommandApproval =
  | { kind: "one_run"; execution_id: string; request_digest: string }
  | { kind: "preset"; preset_id: string; definition_digest: string; request_digest: string };

export interface RemoteCommandAuthority {
  authorized: boolean;
  project_id: string;
  source_root: string;
  request_digest: string;
  toolchain_paths: string[];
  writable_targets: Array<{ profile_id: string; host_path: string }>;
  network_profiles: Array<{ profile_id: string; destinations: string[] }>;
  credential_profiles: Array<{ profile_id: string; environment: Record<string, string> }>;
}

export interface RemoteCommandCapability {
  supported: boolean;
  platform: NodeJS.Platform;
  mechanism: "bubblewrap" | null;
  executable?: string;
  reason?: string;
}

export interface RemoteCommandNetworkConfinement {
  /** Exact destinations the adapter enforces. Must equal the approved claim. */
  enforced_destinations: string[];
  bwrap_args: string[];
  environment?: Record<string, string>;
  /** Trusted wrapper run inside the isolated namespace before the exact argv. */
  sandbox_command?: { executable: string; args: string[] };
  /** Releases host-side proxy/socket resources after launch failure or process exit. */
  dispose?: () => Promise<void>;
}

export interface RemoteCommandSandboxLaunch {
  executable: string;
  args: string[];
  environment: Record<string, string>;
  preflight: RemoteCommandPreflight;
}

export interface RemoteCommandSandboxProcess {
  readonly pid?: number;
  readonly stdout: Readable;
  readonly stderr: Readable;
  wait(): Promise<{ code: number | null; signal: NodeJS.Signals | null }>;
  terminate(): Promise<void>;
}

export interface RemoteCommandJob {
  execution_id: string;
  project_id: string;
  request_digest: string;
  status: RemoteCommandStatus;
  mode: "foreground" | "background";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  deadline_at: string | null;
  exit_code: number | null;
  exit_signal: NodeJS.Signals | null;
  error_code: RemoteCommandErrorCode | null;
  error_message: string | null;
  output_bytes: number;
  output_truncated: boolean;
}

export type RemoteCommandJobEvent =
  | { type: "status"; execution_id: string; job: RemoteCommandJob }
  | { type: "output"; execution_id: string; sequence: number; stream: "stdout" | "stderr"; text: string; trusted: false }
  | { type: "output_truncated"; execution_id: string; retained_bytes: number };

export interface RemoteCommandPresetState {
  config: RemoteCommandPermissions;
  activeGrants: readonly ActiveRemoteCommandPresetGrant[];
}

export interface RemoteCommandRuntimeOptions {
  approve: (preflight: RemoteCommandPreflight) => Promise<RemoteCommandApproval | null>;
  revalidateAuthority: (preflight: RemoteCommandPreflight) => Promise<RemoteCommandAuthority>;
  resolvePresetState?: () => Promise<RemoteCommandPresetState>;
  prepareNetworkConfinement?: (claim: RemoteCommandNetworkClaim, preflight: RemoteCommandPreflight) => Promise<RemoteCommandNetworkConfinement>;
  prepareAppArmorConfinement?: (preflight: RemoteCommandPreflight) => Promise<RemoteCommandAppArmorConfinement>;
  capability?: () => RemoteCommandCapability;
  launchSandbox?: (launch: RemoteCommandSandboxLaunch) => RemoteCommandSandboxProcess;
  now?: () => Date;
  maxRetainedOutputBytes?: number;
}

interface MutableJob extends RemoteCommandJob {
  sequence: number;
  retained: number;
  process: RemoteCommandSandboxProcess | null;
  timer: NodeJS.Timeout | null;
  requestedStop: "stopped" | "timed_out" | null;
  redactionSecrets: string[];
  completion: Promise<RemoteCommandJob>;
  resolveCompletion: (job: RemoteCommandJob) => void;
}

const MAX_RETAINED_OUTPUT_BYTES = 256 * 1024;
const MAX_OUTPUT_CHUNK_BYTES = 16 * 1024;
const MAX_ARGUMENTS = 128;
const MAX_ARGUMENT_BYTES = 16 * 1024;
const MAX_PROJECT_MASK_SCAN_ENTRIES = 250_000;
const MIN_DEADLINE_MS = 100;
const MAX_DEADLINE_MS = 24 * 60 * 60 * 1000;
const GIT_CONFIG_PRIVATE_GLOB = "**/.git/config";
const SAFE_ENVIRONMENT = Object.freeze({
  PATH: "/usr/local/bin:/usr/bin:/bin",
  HOME: "/tmp/openmates-home",
  TMPDIR: "/tmp",
  LANG: "C.UTF-8",
  LC_ALL: "C.UTF-8",
  NO_COLOR: "1",
});

export class RemoteCommandRuntime {
  readonly #options: RemoteCommandRuntimeOptions;
  readonly #jobs = new Map<string, MutableJob>();
  readonly #listeners = new Set<(event: RemoteCommandJobEvent) => void>();

  constructor(options: RemoteCommandRuntimeOptions) {
    this.#options = options;
  }

  subscribe(listener: (event: RemoteCommandJobEvent) => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  list(): RemoteCommandJob[] {
    return [...this.#jobs.values()].map(snapshot);
  }

  get(executionId: string): RemoteCommandJob | null {
    const job = this.#jobs.get(executionId);
    return job ? snapshot(job) : null;
  }

  async start(request: RemoteCommandRequest): Promise<RemoteCommandJob> {
    const preflight = createRemoteCommandPreflight(request);
    if (this.#jobs.has(preflight.execution_id)) {
      throw new RemoteCommandError("duplicate_execution", `Execution already exists: ${preflight.execution_id}`);
    }
    const job = this.#createJob(preflight);
    this.#jobs.set(preflight.execution_id, job);
    this.#emitStatus(job);

    let network: RemoteCommandNetworkConfinement | null = null;
    let appArmor: RemoteCommandAppArmorConfinement | null = null;
    try {
      const capability = (this.#options.capability ?? inspectRemoteCommandCapability)();
      assertCapability(capability);
      const approval = await this.#options.approve(preflight);
      if (this.#canceled(job)) return snapshot(job);
      if (!approval) throw new RemoteCommandError("approval_required", "This exact command requires user approval");
      await this.#validateApproval(preflight, approval);
      if (this.#canceled(job)) return snapshot(job);
      await this.#assertAuthority(preflight);
      if (this.#canceled(job)) return snapshot(job);

      if (preflight.policy.source_access === "read_write") {
        if (preflight.policy.mode === "background") {
          throw new RemoteCommandError("invalid_request", "Background commands cannot write Project source");
        }
      }

      // Recheck immediately before launch. Source-writing commands acquire the
      // shared engine's exclusive kernel lock inside their process wrapper.
      const authority = await this.#assertAuthority(preflight);
      if (this.#canceled(job)) return snapshot(job);
      if (approval.kind === "preset") await this.#validatePresetApproval(preflight, approval);
      if (this.#canceled(job)) return snapshot(job);
      assertProjectPathPolicyCurrent(preflight);
      job.redactionSecrets = credentialValues(preflight, authority);
      appArmor = await this.#prepareAppArmor(preflight);
      // The broker profile is immutable. Recheck after its privileged setup so
      // a policy edit during preparation cannot launch under stale denials.
      assertProjectPathPolicyCurrent(preflight);
      if (this.#canceled(job)) {
        await appArmor.dispose();
        appArmor = null;
        job.redactionSecrets = [];
        return snapshot(job);
      }
      network = await this.#prepareNetwork(preflight);
      if (this.#canceled(job)) {
        if (network?.dispose) await network.dispose();
        network = null;
        await appArmor.dispose();
        appArmor = null;
        job.redactionSecrets = [];
        return snapshot(job);
      }
      const launch = prepareSandboxLaunch(preflight, authority, capability, network, appArmor);
      if (this.#canceled(job)) {
        if (network?.dispose) await network.dispose();
        network = null;
        await appArmor.dispose();
        appArmor = null;
        job.redactionSecrets = [];
        return snapshot(job);
      }
      const process = (this.#options.launchSandbox ?? launchBubblewrapSandbox)(launch);
      job.process = process;
      job.status = "running";
      job.started_at = this.#now().toISOString();
      job.deadline_at = new Date(this.#now().getTime() + preflight.policy.deadline_ms).toISOString();
      this.#emitStatus(job);
      this.#collectOutput(job, process.stdout, "stdout");
      this.#collectOutput(job, process.stderr, "stderr");
      job.timer = setTimeout(() => void this.#requestStop(job, "timed_out"), preflight.policy.deadline_ms);
      void this.#complete(job, process, [
        ...(network?.dispose ? [{ dispose: network.dispose, errorCode: "network_profile_unavailable" as const }] : []),
        { dispose: appArmor.dispose, errorCode: "confinement_unavailable" as const },
      ]);
      network = null;
      appArmor = null;
      return snapshot(job);
    } catch (error) {
      if (network?.dispose) await network.dispose().catch(() => undefined);
      if (appArmor) await appArmor.dispose().catch(() => undefined);
      if (this.#canceled(job)) {
        job.redactionSecrets = [];
        return snapshot(job);
      }
      const commandError = asRemoteCommandError(error);
      job.status = "failed";
      job.error_code = commandError.code;
      job.error_message = redactCredentialValues(commandError.message, job.redactionSecrets);
      job.finished_at = this.#now().toISOString();
      job.redactionSecrets = [];
      this.#emitStatus(job);
      job.resolveCompletion(snapshot(job));
      throw new RemoteCommandError(commandError.code, job.error_message);
    }
  }

  async wait(executionId: string): Promise<RemoteCommandJob> {
    const job = this.#jobs.get(executionId);
    if (!job) throw new RemoteCommandError("unknown_execution", `Unknown execution: ${executionId}`);
    return job.completion;
  }

  async stop(executionId: string): Promise<RemoteCommandJob> {
    const job = this.#jobs.get(executionId);
    if (!job) throw new RemoteCommandError("unknown_execution", `Unknown execution: ${executionId}`);
    if (job.status === "authorizing") {
      job.requestedStop = "stopped";
      job.status = "stopped";
      job.finished_at = this.#now().toISOString();
      this.#emitStatus(job);
      job.resolveCompletion(snapshot(job));
      return snapshot(job);
    }
    if (job.status === "running") {
      await this.#requestStop(job, "stopped");
      return job.completion;
    }
    return snapshot(job);
  }

  async stopAll(): Promise<RemoteCommandJob[]> {
    return Promise.all([...this.#jobs.values()]
      .filter((job) => job.status === "authorizing" || job.status === "running")
      .map((job) => this.stop(job.execution_id)));
  }

  async dispose(): Promise<void> {
    await this.stopAll();
    this.#listeners.clear();
  }

  async #validateApproval(preflight: RemoteCommandPreflight, approval: RemoteCommandApproval): Promise<void> {
    if (approval.request_digest !== preflight.request_digest) {
      throw new RemoteCommandError("invalid_approval", "Approval does not match the exact command and resources");
    }
    if (approval.kind === "one_run") {
      if (approval.execution_id !== preflight.execution_id) {
        throw new RemoteCommandError("invalid_approval", "One-run approval belongs to another execution");
      }
      return;
    }
    await this.#validatePresetApproval(preflight, approval);
  }

  async #validatePresetApproval(preflight: RemoteCommandPreflight, approval: Extract<RemoteCommandApproval, { kind: "preset" }>): Promise<void> {
    if (!this.#options.resolvePresetState) {
      throw new RemoteCommandError("invalid_approval", "Preset approval cannot be checked against trusted active grants");
    }
    const state = await this.#options.resolvePresetState();
    const match = matchEnabledRemoteCommandPreset({
      config: state.config,
      projectId: preflight.project_id,
      policy: preflight.policy as RemoteCommandPolicy,
      activeGrants: state.activeGrants,
      presetId: approval.preset_id,
    });
    if (!match || match.definitionDigest !== approval.definition_digest) {
      throw new RemoteCommandError("invalid_approval", "Command preset is inactive, changed, or does not exactly match");
    }
    assertClaimsMatchDefinitions(preflight, state.config);
  }

  async #assertAuthority(preflight: RemoteCommandPreflight): Promise<RemoteCommandAuthority> {
    const authority = await this.#options.revalidateAuthority(preflight);
    if (!authority.authorized
      || authority.project_id !== preflight.project_id
      || authority.request_digest !== preflight.request_digest
      || realpath(authority.source_root) !== preflight.source_root) {
      throw new RemoteCommandError("authority_revoked", "Current Project focus or command authority is no longer valid");
    }
    assertExactStrings(authority.toolchain_paths, [...preflight.toolchain_paths], "toolchain paths");
    for (const requested of preflight.writable_targets) {
      const granted = authority.writable_targets.find((candidate) => candidate.profile_id === requested.profile_id);
      if (!granted || realpath(granted.host_path) !== realpath(requested.host_path)) {
        throw new RemoteCommandError("resource_not_granted", `Writable profile is not currently granted: ${requested.profile_id}`);
      }
    }
    if (preflight.network) {
      const granted = authority.network_profiles.find((candidate) => candidate.profile_id === preflight.network?.profile_id);
      if (!granted || !sameStrings(granted.destinations, preflight.network.destinations)) {
        throw new RemoteCommandError("resource_not_granted", `Network profile is not currently granted: ${preflight.network.profile_id}`);
      }
    }
    for (const requested of preflight.credentials) {
      const granted = authority.credential_profiles.find((candidate) => candidate.profile_id === requested.profile_id);
      if (!granted || !sameStrings(Object.keys(granted.environment), requested.environment)) {
        throw new RemoteCommandError("credential_unavailable", `Credential profile is unavailable or changed: ${requested.profile_id}`);
      }
      for (const name of requested.environment) {
        const value = granted.environment[name];
        if (typeof value !== "string" || value.includes("\0") || Buffer.byteLength(value) > 64 * 1024) {
          throw new RemoteCommandError("credential_unavailable", `Credential value is unavailable: ${name}`);
        }
      }
    }
    return authority;
  }

  async #prepareNetwork(preflight: RemoteCommandPreflight): Promise<RemoteCommandNetworkConfinement | null> {
    if (!preflight.network) return null;
    if (!this.#options.prepareNetworkConfinement) {
      throw new RemoteCommandError(
        "network_profile_unavailable",
        `Approved destinations (${preflight.network.destinations.join(", ")}) cannot be enforced on this executor`,
      );
    }
    const prepared = await this.#options.prepareNetworkConfinement(preflight.network as RemoteCommandNetworkClaim, preflight);
    if (!sameStrings(prepared.enforced_destinations, preflight.network.destinations)) {
      throw new RemoteCommandError("network_profile_unavailable", "Network transport did not enforce the exact approved destinations");
    }
    if (prepared.bwrap_args.includes("--share-net")) {
      throw new RemoteCommandError("network_profile_unavailable", "Network transport attempted to enable unrestricted host networking");
    }
    if (prepared.sandbox_command) {
      const command = prepared.sandbox_command;
      if (!isAbsolute(command.executable)
        || command.executable.includes("\0")
        || !Array.isArray(command.args)
        || command.args.some((argument) => typeof argument !== "string" || argument.includes("\0"))) {
        throw new RemoteCommandError("network_profile_unavailable", "Network transport returned an invalid sandbox bridge command");
      }
    }
    return prepared;
  }

  async #prepareAppArmor(preflight: RemoteCommandPreflight): Promise<RemoteCommandAppArmorConfinement> {
    try {
      const prepare = this.#options.prepareAppArmorConfinement ?? ((current: RemoteCommandPreflight) => (
        prepareRemoteCommandAppArmorConfinement({
          execution_id: current.execution_id,
          source_root: current.source_root,
          private_policy_digest: current.path_policy_digest,
          private_globs: current.private_path_globs,
          exact_private_aliases: current.masked_project_paths,
          exact_readonly_paths: current.protected_project_paths,
        }, current.toolchain_paths)
      ));
      return await prepare(preflight);
    } catch (error) {
      throw new RemoteCommandError(
        "confinement_unavailable",
        error instanceof Error ? error.message : "AppArmor command confinement could not be prepared",
      );
    }
  }

  #createJob(preflight: RemoteCommandPreflight): MutableJob {
    let resolveCompletion!: (job: RemoteCommandJob) => void;
    const completion = new Promise<RemoteCommandJob>((resolvePromise) => { resolveCompletion = resolvePromise; });
    return {
      execution_id: preflight.execution_id,
      project_id: preflight.project_id,
      request_digest: preflight.request_digest,
      status: "authorizing",
      mode: preflight.policy.mode,
      created_at: this.#now().toISOString(),
      started_at: null,
      finished_at: null,
      deadline_at: null,
      exit_code: null,
      exit_signal: null,
      error_code: null,
      error_message: null,
      output_bytes: 0,
      output_truncated: false,
      sequence: 0,
      retained: 0,
      process: null,
      timer: null,
      requestedStop: null,
      redactionSecrets: [],
      completion,
      resolveCompletion,
    };
  }

  #collectOutput(job: MutableJob, stream: Readable, streamName: "stdout" | "stderr"): void {
    let carry = "";
    const secrets = [...job.redactionSecrets];
    const maximumSecretLength = secrets.reduce((maximum, secret) => Math.max(maximum, secret.length), 0);
    stream.on("data", (chunk: Buffer | string) => {
      const sanitized = sanitizeRemoteCommandOutput(`${carry}${typeof chunk === "string" ? chunk : chunk.toString("utf8")}`);
      const retainedCharacters = Math.max(0, maximumSecretLength - 1);
      let boundary = Math.max(0, sanitized.length - retainedCharacters);
      for (const secret of secrets) {
        let occurrence = sanitized.indexOf(secret);
        while (occurrence >= 0) {
          if (occurrence < boundary && occurrence + secret.length > boundary) boundary = occurrence;
          occurrence = sanitized.indexOf(secret, occurrence + 1);
        }
      }
      carry = sanitized.slice(boundary);
      this.#emitOutput(job, redactCredentialValues(sanitized.slice(0, boundary), secrets), streamName);
    });
    stream.once("end", () => {
      this.#emitOutput(job, redactCredentialValues(carry, secrets), streamName);
      carry = "";
    });
  }

  #emitOutput(job: MutableJob, sanitized: string, streamName: "stdout" | "stderr"): void {
    if (!sanitized) return;
    job.output_bytes += Buffer.byteLength(sanitized);
    const maximum = this.#options.maxRetainedOutputBytes ?? MAX_RETAINED_OUTPUT_BYTES;
    const available = Math.max(0, maximum - job.retained);
    if (available === 0) {
      this.#markOutputTruncated(job, maximum);
      return;
    }
    const bounded = truncateUtf8(sanitized, Math.min(available, MAX_OUTPUT_CHUNK_BYTES));
    const bytes = Buffer.byteLength(bounded);
    job.retained += bytes;
    this.#emit({ type: "output", execution_id: job.execution_id, sequence: ++job.sequence, stream: streamName, text: bounded, trusted: false });
    if (bytes < Buffer.byteLength(sanitized)) this.#markOutputTruncated(job, maximum);
  }

  #markOutputTruncated(job: MutableJob, maximum: number): void {
    if (job.output_truncated) return;
    job.output_truncated = true;
    this.#emit({ type: "output_truncated", execution_id: job.execution_id, retained_bytes: Math.min(job.retained, maximum) });
  }

  async #requestStop(job: MutableJob, reason: "stopped" | "timed_out"): Promise<void> {
    if (job.status !== "running" || !job.process) return;
    job.requestedStop = reason;
    await job.process.terminate();
  }

  async #complete(
    job: MutableJob,
    process: RemoteCommandSandboxProcess,
    confinements: Array<{ dispose: () => Promise<void>; errorCode: "network_profile_unavailable" | "confinement_unavailable" }>,
  ): Promise<void> {
    try {
      const result = await process.wait();
      job.exit_code = result.code;
      job.exit_signal = result.signal;
      if (job.requestedStop) job.status = job.requestedStop;
      else if (result.code === 0) job.status = "succeeded";
      else {
        job.status = "failed";
        job.error_code = "launch_failed";
        job.error_message = result.signal ? `Command exited from ${result.signal}` : `Command exited with code ${result.code ?? "unknown"}`;
      }
    } catch (error) {
      job.status = job.requestedStop ?? "failed";
      if (!job.requestedStop) {
        const commandError = asRemoteCommandError(error);
        job.error_code = commandError.code;
        job.error_message = redactCredentialValues(commandError.message, job.redactionSecrets);
      }
    } finally {
      if (job.timer) clearTimeout(job.timer);
      for (const confinement of confinements) {
        try {
          await confinement.dispose();
        } catch (error) {
          if (job.status === "succeeded") {
            job.status = "failed";
            job.error_code = confinement.errorCode;
            job.error_message = redactCredentialValues(
              error instanceof Error ? error.message : "Failed to release command confinement",
              job.redactionSecrets,
            );
          }
        }
      }
      job.process = null;
      job.finished_at = this.#now().toISOString();
      job.redactionSecrets = [];
      this.#emitStatus(job);
      job.resolveCompletion(snapshot(job));
    }
  }

  #emitStatus(job: MutableJob): void {
    this.#emit({ type: "status", execution_id: job.execution_id, job: snapshot(job) });
  }

  #emit(event: RemoteCommandJobEvent): void {
    for (const listener of this.#listeners) listener(event);
  }

  #canceled(job: MutableJob): boolean {
    return job.requestedStop === "stopped" || job.status === "stopped";
  }

  #now(): Date {
    return this.#options.now?.() ?? new Date();
  }
}

export function createRemoteCommandPreflight(request: RemoteCommandRequest): RemoteCommandPreflight {
  if (!request || typeof request !== "object") throw new RemoteCommandError("invalid_request", "Command request must be an object");
  const executionId = request.execution_id ?? randomUUID();
  if (typeof executionId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(executionId)) throw new RemoteCommandError("invalid_request", "Invalid execution ID");
  if (typeof request.project_id !== "string" || !request.project_id || request.project_id.length > 256) throw new RemoteCommandError("invalid_request", "Invalid Project ID");
  if (typeof request.source_root !== "string" || !request.source_root) throw new RemoteCommandError("invalid_request", "Invalid Project source root");
  if (!request.policy || typeof request.policy !== "object") throw new RemoteCommandError("invalid_request", "Invalid command policy");
  if (!Array.isArray(request.toolchain_paths) || !Array.isArray(request.writable_targets) || !Array.isArray(request.credentials)) throw new RemoteCommandError("invalid_request", "Invalid command resource claims");
  if (request.toolchain_paths.some((path) => typeof path !== "string")
    || request.writable_targets.some((target) => !target || typeof target !== "object" || typeof target.profile_id !== "string" || typeof target.host_path !== "string")
    || request.credentials.some((claim) => !claim || typeof claim !== "object" || typeof claim.profile_id !== "string" || !Array.isArray(claim.environment))
    || (request.network !== null && (!request.network || typeof request.network !== "object" || typeof request.network.profile_id !== "string" || !Array.isArray(request.network.destinations)))) {
    throw new RemoteCommandError("invalid_request", "Malformed command resource claim");
  }
  validatePolicy(request.policy);
  const root = realpath(request.source_root);
  if (!statSync(root).isDirectory()) throw new RemoteCommandError("invalid_request", "Project source root must be a directory");
  let privateState: string;
  try {
    privateState = canonicalOpenMatesStateDirectory();
    canonicalProjectSourceRoot(root, { stateDirectory: privateState });
  } catch (error) {
    throw new RemoteCommandError(
      "confinement_unavailable",
      error instanceof Error ? error.message : "Project source root boundary cannot be established",
    );
  }
  const cwd = request.policy.cwd === "." ? root : realpath(join(root, request.policy.cwd));
  if (!isInside(root, cwd) || !statSync(cwd).isDirectory()) throw new RemoteCommandError("invalid_request", "Command cwd escapes the Project root");
  const canonicalPolicy = { ...request.policy, argv: [...request.policy.argv], cwd: relative(root, cwd).split(sep).join("/") || "." };
  const toolchains = request.toolchain_paths.map(canonicalDirectory);
  assertUnique(toolchains, "toolchain paths");
  if (toolchains.some((path) => pathsOverlap(path, root))) {
    throw new RemoteCommandError("invalid_request", "A toolchain mount cannot overlap the Project source root");
  }
  if (toolchains.some((path) => path === privateState || isInside(path, privateState))) {
    throw new RemoteCommandError(
      "resource_not_granted",
      "A toolchain mount cannot contain the private OpenMates state directory",
    );
  }
  const writable = request.writable_targets.map((target) => ({ ...target, host_path: canonicalDirectory(target.host_path) }));
  assertUnique(writable.map((target) => target.profile_id), "writable profiles");
  for (const target of writable) {
    if (!/^[a-z][a-z0-9-]{0,63}$/.test(target.profile_id)) throw new RemoteCommandError("invalid_request", `Invalid writable profile: ${target.profile_id}`);
    if (target.purpose !== "cache" && target.purpose !== "output") throw new RemoteCommandError("invalid_request", `Invalid writable purpose: ${target.profile_id}`);
    if (pathsOverlap(target.host_path, root)) {
      throw new RemoteCommandError("invalid_request", `Writable profile cannot overlap the Project root: ${target.profile_id}`);
    }
    if (pathsOverlap(target.host_path, privateState)) {
      throw new RemoteCommandError(
        "resource_not_granted",
        `Writable profile cannot overlap the private OpenMates state directory: ${target.profile_id}`,
      );
    }
    if (discoverProjectCredentialMasks(target.host_path).length > 0) {
      throw new RemoteCommandError("resource_not_granted", `Writable profile contains protected credential paths: ${target.profile_id}`);
    }
  }
  assertExactStrings(writable.map((target) => target.profile_id), canonicalPolicy.writable_profiles, "writable profile claims");
  const network = request.network ? { ...request.network, destinations: [...request.network.destinations].sort() } : null;
  if ((network?.profile_id ?? null) !== canonicalPolicy.network_profile) throw new RemoteCommandError("invalid_request", "Network claim does not match command policy");
  if (network) {
    if (!/^[a-z][a-z0-9-]{0,63}$/.test(network.profile_id) || !network.destinations.length || network.destinations.some((destination) => !validNetworkDestination(destination))) {
      throw new RemoteCommandError("invalid_request", "Invalid network profile claim");
    }
    assertUnique(network.destinations, "network destinations");
  }
  const credentials = request.credentials.map((claim) => ({ ...claim, environment: [...claim.environment].sort() }));
  assertUnique(credentials.map((claim) => claim.profile_id), "credential profiles");
  assertExactStrings(credentials.map((claim) => claim.profile_id), canonicalPolicy.credential_profiles, "credential profile claims");
  for (const claim of credentials) {
    if (!claim.environment.length || claim.environment.some((name) => !/^[A-Z_][A-Z0-9_]{0,127}$/.test(name))) {
      throw new RemoteCommandError("invalid_request", `Invalid credential environment for profile: ${claim.profile_id}`);
    }
    if (claim.environment.includes("LD_PRELOAD")) {
      throw new RemoteCommandError("invalid_request", "Credential profiles cannot override the Git config compatibility boundary");
    }
    assertUnique(claim.environment, `credential profile ${claim.profile_id}`);
  }
  let pathPolicy: LoadedProjectPathPolicy;
  try {
    pathPolicy = loadProjectPathPolicy(root);
  } catch (error) {
    throw new RemoteCommandError(
      "confinement_unavailable",
      error instanceof Error ? error.message : "Project private-path policy cannot be established",
    );
  }
  const projectPathProtection = discoverProjectPathProtection(root, pathPolicy);
  const privatePathGlobs = [...new Set([...pathPolicy.privateGlobs(), GIT_CONFIG_PRIVATE_GLOB])].sort();
  const digestInput = {
    execution_id: executionId,
    project_id: request.project_id,
    source_root: root,
    policy: canonicalPolicy,
    toolchain_paths: toolchains,
    writable_targets: writable,
    network,
    credentials,
    path_policy_digest: pathPolicy.privateDigest,
    private_path_globs: privatePathGlobs,
    masked_project_paths: projectPathProtection.masked,
    protected_project_paths: projectPathProtection.protected,
  };
  const preflight: RemoteCommandPreflight = {
    ...digestInput,
    request_digest: sha256(stableJson(digestInput)),
  };
  return deepFreeze(preflight);
}

export function inspectRemoteCommandCapability(): RemoteCommandCapability {
  if (process.platform !== "linux") {
    return { supported: false, platform: process.platform, mechanism: null, reason: `OS-enforced command confinement is not implemented for ${process.platform}` };
  }
  const executable = REMOTE_COMMAND_BWRAP;
  if (!existsSync(executable)) {
    return { supported: false, platform: process.platform, mechanism: null, reason: `OpenMates bubblewrap launcher is not installed at ${executable}` };
  }
  const appArmor = inspectRemoteCommandAppArmorCapability({ bwrapPath: executable });
  if (!appArmor.supported) {
    return { supported: false, platform: process.platform, mechanism: null, reason: appArmor.reason };
  }
  const probe = spawnSync(executable, ["--unshare-user", "--unshare-pid", "--unshare-net", "--disable-userns", "--assert-userns-disabled", "--ro-bind", "/", "/", "--", "/bin/true"], {
    encoding: "utf8",
    timeout: 5_000,
    env: { PATH: SAFE_ENVIRONMENT.PATH },
  });
  if (probe.status !== 0) {
    const detail = (probe.stderr || probe.error?.message || "kernel rejected the sandbox probe").trim();
    return { supported: false, platform: process.platform, mechanism: null, reason: `bubblewrap cannot enforce confinement: ${detail}` };
  }
  return { supported: true, platform: process.platform, mechanism: "bubblewrap", executable };
}

export function sanitizeRemoteCommandOutput(value: string): string {
  return value
    // eslint-disable-next-line no-control-regex
    .replace(/\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/g, "")
    // eslint-disable-next-line no-control-regex
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/[\u202a-\u202e\u2066-\u2069]/g, "")
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "");
}

function prepareSandboxLaunch(
  preflight: RemoteCommandPreflight,
  authority: RemoteCommandAuthority,
  capability: RemoteCommandCapability,
  network: RemoteCommandNetworkConfinement | null,
  appArmor: RemoteCommandAppArmorConfinement,
): RemoteCommandSandboxLaunch {
  if (!capability.executable) throw new RemoteCommandError("confinement_unavailable", "Sandbox executable is unavailable");
  const args = ["--unshare-all", "--unshare-user", "--disable-userns", "--assert-userns-disabled", "--die-with-parent", "--new-session", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/openmates-home"];
  for (const path of preflight.toolchain_paths) args.push("--ro-bind", path, path);
  addStandardToolchainSymlinks(args, preflight.toolchain_paths);
  args.push(preflight.policy.source_access === "read_write" ? "--bind" : "--ro-bind", preflight.source_root, "/project");
  if (preflight.policy.source_access === "read_write") {
    for (const protectedPath of preflight.protected_project_paths) {
      args.push("--ro-bind", join(preflight.source_root, protectedPath.path), `/project/${protectedPath.path}`);
    }
  }
  // Private masks must be the final mounts below /project so a read-only
  // control directory cannot reveal a private descendant again.
  for (const masked of preflight.masked_project_paths) {
    const destination = `/project/${masked.path}`;
    if (masked.kind === "directory") args.push("--tmpfs", destination);
    else args.push("--ro-bind", "/dev/null", destination);
  }
  if (preflight.writable_targets.length) {
    args.push("--dir", "/openmates", "--dir", "/openmates/writable");
    for (const target of preflight.writable_targets) args.push("--bind", target.host_path, writableSandboxPath(target.profile_id));
  }
  if (network) args.push(...network.bwrap_args);
  const networkCommand = network?.sandbox_command;
  const approvedCommand = networkCommand
    ? [networkCommand.executable, ...networkCommand.args, "--", ...preflight.policy.argv]
    : preflight.policy.argv;
  const commandArgv = [appArmor.sandbox_command.executable, ...appArmor.sandbox_command.args, "--", ...approvedCommand];
  args.push("--chdir", preflight.policy.cwd === "." ? "/project" : `/project/${preflight.policy.cwd}`, "--", ...commandArgv);
  const networkEnvironment = network?.environment ?? {};
  for (const name of Object.keys(networkEnvironment)) {
    if (name in SAFE_ENVIRONMENT || name === "LD_PRELOAD" || preflight.credentials.some((claim) => claim.environment.includes(name))) {
      throw new RemoteCommandError("network_profile_unavailable", `Network transport attempted to override protected environment variable: ${name}`);
    }
  }
  const appArmorEnvironment = appArmor.sandbox_environment;
  if (!appArmorEnvironment
    || Object.keys(appArmorEnvironment).length !== 1
    || typeof appArmorEnvironment.LD_PRELOAD !== "string"
    || !isAbsolute(appArmorEnvironment.LD_PRELOAD)
    || appArmorEnvironment.LD_PRELOAD.includes("\0")) {
    throw new RemoteCommandError("confinement_unavailable", "AppArmor confinement returned an invalid Git config compatibility library");
  }
  const environment: Record<string, string> = { ...SAFE_ENVIRONMENT, ...networkEnvironment, ...appArmorEnvironment };
  for (const target of preflight.writable_targets) environment[`OPENMATES_WRITABLE_${target.profile_id.toUpperCase().replaceAll("-", "_")}`] = writableSandboxPath(target.profile_id);
  for (const requested of preflight.credentials) {
    const granted = authority.credential_profiles.find((profile) => profile.profile_id === requested.profile_id);
    if (!granted) throw new RemoteCommandError("credential_unavailable", `Credential profile is unavailable: ${requested.profile_id}`);
    for (const name of requested.environment) environment[name] = granted.environment[name] as string;
  }
  if (preflight.policy.source_access === "read_write") {
    try {
      const wrapped = wrapRemoteProjectSourceCommand(preflight.source_root, capability.executable, args);
      return { executable: wrapped.executable, args: wrapped.args, environment, preflight };
    } catch (error) {
      if (error instanceof RemoteProjectSourceLockError) {
        throw new RemoteCommandError("coordination_required", error.message);
      }
      throw error;
    }
  }
  return { executable: capability.executable, args, environment, preflight };
}

function launchBubblewrapSandbox(launch: RemoteCommandSandboxLaunch): RemoteCommandSandboxProcess {
  let child: ChildProcessWithoutNullStreams;
  try {
    child = spawn(launch.executable, launch.args, { env: launch.environment, stdio: "pipe", detached: true });
  } catch (error) {
    throw new RemoteCommandError("launch_failed", error instanceof Error ? error.message : "Failed to launch sandbox");
  }
  const wait = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolvePromise, reject) => {
    child.once("error", (error) => reject(new RemoteCommandError("launch_failed", error.message)));
    child.once("close", (code, signal) => resolvePromise({ code, signal }));
  });
  return {
    pid: child.pid,
    stdout: child.stdout,
    stderr: child.stderr,
    wait: () => wait,
    terminate: async () => {
      if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
      try { process.kill(-child.pid, "SIGTERM"); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
      await new Promise<void>((resolvePromise) => {
        const timer = setTimeout(() => {
          try { process.kill(-(child.pid as number), "SIGKILL"); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
          resolvePromise();
        }, 2_000);
        child.once("exit", () => { clearTimeout(timer); resolvePromise(); });
      });
    },
  };
}

function assertClaimsMatchDefinitions(preflight: RemoteCommandPreflight, config: RemoteCommandPermissions): void {
  for (const claim of preflight.writable_targets) {
    const definition = config.resource_profiles.writable.find((candidate) => candidate.id === claim.profile_id);
    if (!definition || definition.purpose !== claim.purpose) throw new RemoteCommandError("invalid_approval", `Writable profile definition changed: ${claim.profile_id}`);
  }
  if (preflight.network) {
    const definition = config.resource_profiles.network.find((candidate) => candidate.id === preflight.network?.profile_id);
    if (!definition || !sameStrings(definition.destinations, preflight.network.destinations)) throw new RemoteCommandError("invalid_approval", `Network profile definition changed: ${preflight.network.profile_id}`);
  }
  for (const claim of preflight.credentials) {
    const definition = config.resource_profiles.credentials.find((candidate) => candidate.id === claim.profile_id);
    if (!definition || !sameStrings(definition.environment, claim.environment)) throw new RemoteCommandError("invalid_approval", `Credential profile definition changed: ${claim.profile_id}`);
  }
}

function validatePolicy(policy: RemoteCommandPolicy): void {
  if (!Array.isArray(policy.argv) || policy.argv.length === 0 || policy.argv.length > MAX_ARGUMENTS) throw new RemoteCommandError("invalid_request", "Command argv is empty or too large");
  if (policy.argv.some((arg) => typeof arg !== "string" || !arg || Buffer.byteLength(arg) > MAX_ARGUMENT_BYTES || arg.includes("\0"))) throw new RemoteCommandError("invalid_request", "Command argv contains an invalid argument");
  if (policy.mode !== "foreground" && policy.mode !== "background") throw new RemoteCommandError("invalid_request", "Invalid command mode");
  if (policy.source_access !== "read_only" && policy.source_access !== "read_write") throw new RemoteCommandError("invalid_request", "Invalid source access");
  if (policy.mode === "background" && policy.source_access !== "read_only") throw new RemoteCommandError("invalid_request", "Background commands must use read-only source access");
  if (!Number.isSafeInteger(policy.deadline_ms) || policy.deadline_ms < MIN_DEADLINE_MS || policy.deadline_ms > MAX_DEADLINE_MS) throw new RemoteCommandError("invalid_request", "Invalid command deadline");
  if (isAbsolute(policy.cwd) || policy.cwd.includes("\0") || policy.cwd.split(/[\\/]/).includes("..")) throw new RemoteCommandError("invalid_request", "Command cwd must stay inside the Project");
  for (const [name, value] of [["writable_profiles", policy.writable_profiles], ["credential_profiles", policy.credential_profiles]] as const) {
    if (!Array.isArray(value) || value.some((id) => typeof id !== "string" || !/^[a-z][a-z0-9-]{0,63}$/.test(id))) throw new RemoteCommandError("invalid_request", `Invalid ${name}`);
    assertUnique(value, name);
  }
  if (policy.network_profile !== null && (typeof policy.network_profile !== "string" || !/^[a-z][a-z0-9-]{0,63}$/.test(policy.network_profile))) throw new RemoteCommandError("invalid_request", "Invalid network profile");
}

function validNetworkDestination(value: unknown): value is string {
  return typeof value === "string"
    && value.length <= 253
    && /^(?:\[[0-9a-f:]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[1-9][0-9]{0,4})?$/.test(value);
}

function addStandardToolchainSymlinks(args: string[], toolchainPaths: readonly string[]): void {
  const visible = (path: string) => toolchainPaths.some((root) => path === root || isInside(root, path));
  for (const [target, link] of [["/usr/bin", "/bin"], ["/usr/lib", "/lib"], ["/usr/lib64", "/lib64"]] as const) {
    if (visible(target) && !toolchainPaths.includes(link)) args.push("--symlink", target.slice(1), link);
  }
}

interface ProjectPathProtection {
  masked: Array<{ path: string; kind: "file" | "directory" }>;
  protected: Array<{ path: string; kind: "file" | "directory" }>;
}

function discoverProjectCredentialMasks(root: string): Array<{ path: string; kind: "file" | "directory" }> {
  return discoverProjectPathProtection(root, null).masked;
}

function discoverProjectPathProtection(root: string, policy: LoadedProjectPathPolicy | null): ProjectPathProtection {
  const entries: Array<{
    path: string;
    kind: "file" | "directory";
    inode: string | null;
    masked: boolean;
    protected: boolean;
  }> = [];
  const directories = [""];
  let visited = 0;
  try {
    while (directories.length) {
      const parent = directories.pop() as string;
      for (const entry of readdirSync(join(root, parent), { withFileTypes: true })) {
        visited += 1;
        if (visited > MAX_PROJECT_MASK_SCAN_ENTRIES) {
          throw new RemoteCommandError("confinement_unavailable", `Project credential scan exceeds ${MAX_PROJECT_MASK_SCAN_ENTRIES} entries`);
        }
        const path = parent ? `${parent}/${entry.name}` : entry.name;
        const fullPath = join(root, path);
        const stat = lstatSync(fullPath);
        const kind = entry.isDirectory() ? "directory" as const : "file" as const;
        let masked = policy
          ? policy.isPrivate(path, kind === "directory") || path.toLowerCase() === ".git/config"
          : classifyProjectFileReadRisk(path).isHighRisk || path.toLowerCase() === ".git/config";
        let protectedPath = isProjectControlPath(path, kind);
        if (entry.isSymbolicLink()) {
          try {
            const target = realpathSync(fullPath);
            if (!isInside(root, target)) masked = true;
            else {
              const targetPath = relative(root, target).split(sep).join("/");
              const targetKind = statSync(target).isDirectory() ? "directory" as const : "file" as const;
              masked ||= policy
                ? policy.isPrivate(targetPath, targetKind === "directory") || targetPath.toLowerCase() === ".git/config"
                : classifyProjectFileReadRisk(targetPath).isHighRisk || targetPath.toLowerCase() === ".git/config";
              protectedPath ||= isProjectControlPath(targetPath, targetKind);
            }
          } catch {
            // Broken links cannot expose content through the sandbox.
          }
        }
        entries.push({ path, kind, inode: entry.isSymbolicLink() ? null : `${stat.dev}:${stat.ino}`, masked, protected: protectedPath });
        if (entry.isDirectory()) directories.push(path);
      }
    }
  } catch (error) {
    if (error instanceof RemoteCommandError) throw error;
    throw new RemoteCommandError(
      "confinement_unavailable",
      `Project credential paths cannot be enumerated safely: ${error instanceof Error ? error.message : "unknown error"}`,
    );
  }
  const maskedInodes = new Set(entries.filter((entry) => entry.masked && entry.inode).map((entry) => entry.inode));
  const protectedInodes = new Set(entries.filter((entry) => entry.protected && entry.inode).map((entry) => entry.inode));
  const maskedCandidates = entries
    .filter((entry) => entry.masked || (entry.inode !== null && maskedInodes.has(entry.inode)))
    .sort((left, right) => left.path.split("/").length - right.path.split("/").length || left.path.localeCompare(right.path));
  const masks: Array<{ path: string; kind: "file" | "directory" }> = [];
  for (const candidate of maskedCandidates) {
    if (masks.some((mask) => mask.kind === "directory" && candidate.path.startsWith(`${mask.path}/`))) continue;
    masks.push({ path: candidate.path, kind: candidate.kind });
  }
  const protectedPaths: Array<{ path: string; kind: "file" | "directory" }> = [];
  for (const candidate of entries
    .filter((entry) => entry.protected || (entry.inode !== null && protectedInodes.has(entry.inode)))
    .sort((left, right) => left.path.split("/").length - right.path.split("/").length || left.path.localeCompare(right.path))) {
    if (masks.some((mask) => mask.path === candidate.path || (mask.kind === "directory" && candidate.path.startsWith(`${mask.path}/`)))) continue;
    if (protectedPaths.some((item) => item.kind === "directory" && candidate.path.startsWith(`${item.path}/`))) continue;
    protectedPaths.push({ path: candidate.path, kind: candidate.kind });
  }
  return { masked: masks, protected: protectedPaths };
}

function assertProjectPathPolicyCurrent(preflight: RemoteCommandPreflight): void {
  let policy: LoadedProjectPathPolicy;
  try {
    policy = loadProjectPathPolicy(preflight.source_root);
  } catch (error) {
    throw new RemoteCommandError(
      "confinement_unavailable",
      error instanceof Error ? error.message : "Project private-path policy cannot be revalidated",
    );
  }
  const current = discoverProjectPathProtection(preflight.source_root, policy);
  if (policy.privateDigest !== preflight.path_policy_digest
    || stableJson([...new Set([...policy.privateGlobs(), GIT_CONFIG_PRIVATE_GLOB])].sort()) !== stableJson(preflight.private_path_globs)
    || stableJson(current.masked) !== stableJson(preflight.masked_project_paths)
    || stableJson(current.protected) !== stableJson(preflight.protected_project_paths)) {
    throw new RemoteCommandError("confinement_unavailable", "Project private-path policy changed during command authorization; prepare a fresh execution");
  }
}

function isProjectControlPath(path: string, kind: "file" | "directory"): boolean {
  const normalized = path.toLowerCase();
  if (normalized === ".openmates/permissions.yml") return true;
  if (kind === "file" && (normalized === "agents.md" || normalized.endsWith("/agents.md")
    || normalized === "claude.md" || normalized.endsWith("/claude.md"))) return true;
  return normalized === ".openmates/rules" || normalized.startsWith(".openmates/rules/")
    || normalized === ".claude/rules" || normalized.startsWith(".claude/rules/")
    || normalized === ".agents/rules" || normalized.startsWith(".agents/rules/");
}

function assertCapability(capability: RemoteCommandCapability): void {
  if (capability.supported) return;
  const code = capability.platform === "linux" ? "confinement_unavailable" : "unsupported_platform";
  throw new RemoteCommandError(code, capability.reason ?? "OS-enforced command confinement is unavailable");
}

function canonicalDirectory(path: string): string {
  const canonical = realpath(path);
  if (canonical === resolve("/")) throw new RemoteCommandError("invalid_request", "The host filesystem root cannot be mounted as a command resource");
  if (!statSync(canonical).isDirectory()) throw new RemoteCommandError("invalid_request", `Command resource is not a directory: ${path}`);
  return canonical;
}

function pathsOverlap(left: string, right: string): boolean {
  return isInside(left, right) || isInside(right, left);
}

function realpath(path: string): string {
  try {
    const stat = lstatSync(path);
    if (!stat.isDirectory() && !stat.isSymbolicLink()) throw new RemoteCommandError("invalid_request", `Path is not a directory: ${path}`);
    return realpathSync(path);
  } catch (error) {
    if (error instanceof RemoteCommandError) throw error;
    throw new RemoteCommandError("invalid_request", `Path is unavailable: ${path}`);
  }
}

function writableSandboxPath(profileId: string): string {
  return `/openmates/writable/${profileId}`;
}

function snapshot(job: MutableJob): RemoteCommandJob {
  return {
    execution_id: job.execution_id,
    project_id: job.project_id,
    request_digest: job.request_digest,
    status: job.status,
    mode: job.mode,
    created_at: job.created_at,
    started_at: job.started_at,
    finished_at: job.finished_at,
    deadline_at: job.deadline_at,
    exit_code: job.exit_code,
    exit_signal: job.exit_signal,
    error_code: job.error_code,
    error_message: job.error_message,
    output_bytes: job.output_bytes,
    output_truncated: job.output_truncated,
  };
}

function asRemoteCommandError(error: unknown): RemoteCommandError {
  return error instanceof RemoteCommandError
    ? error
    : new RemoteCommandError("launch_failed", error instanceof Error ? error.message : "Remote command failed");
}

function credentialValues(preflight: RemoteCommandPreflight, authority: RemoteCommandAuthority): string[] {
  const values: string[] = [];
  for (const requested of preflight.credentials) {
    const granted = authority.credential_profiles.find((profile) => profile.profile_id === requested.profile_id);
    for (const name of requested.environment) {
      const value = granted?.environment[name];
      if (value) values.push(value);
    }
  }
  return [...new Set(values)].sort((left, right) => right.length - left.length);
}

function redactCredentialValues(value: string, secrets: readonly string[]): string {
  let redacted = value;
  for (const secret of secrets) redacted = redacted.split(secret).join("[REDACTED_CREDENTIAL]");
  return redacted;
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return stableJson([...left].sort()) === stableJson([...right].sort());
}

function assertExactStrings(actual: readonly string[], expected: readonly string[], context: string): void {
  if (!sameStrings(actual, expected)) throw new RemoteCommandError("resource_not_granted", `Current ${context} do not match the request`);
}

function assertUnique(values: string[], context: string): void {
  if (new Set(values).size !== values.length) throw new RemoteCommandError("invalid_request", `${context} contain duplicate values`);
}

function isInside(root: string, candidate: string): boolean {
  const path = relative(root, candidate);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}

function truncateUtf8(value: string, maximum: number): string {
  const bytes = Buffer.from(value);
  if (bytes.length <= maximum) return value;
  return bytes.subarray(0, maximum).toString("utf8").replace(/\uFFFD$/, "");
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.freeze(value);
    for (const item of Object.values(value as Record<string, unknown>)) deepFreeze(item);
  }
  return value;
}
