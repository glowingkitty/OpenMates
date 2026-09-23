/** Source-side transport for client-encrypted, Project-confined remote commands. */

import { existsSync, realpathSync, statSync } from "node:fs";
import { basename, dirname, relative, resolve } from "node:path";

import type { OpenMatesClient } from "./client.js";
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "./crypto.js";
import type { LiveRemoteAccessBinding } from "./remoteAccess.js";
import {
  canonicalPortableRemoteCommandRequest,
  listRemoteCommandPresetGrants,
  remoteCommandPortableRequestDigest,
  type PortableRemoteCommandRequest,
  type RemoteCommandApprovalChoice,
} from "./remoteCommandClient.js";
import {
  createRemoteCommandPreflight,
  RemoteCommandError,
  RemoteCommandRuntime,
  type RemoteCommandAuthority,
  type RemoteCommandCapability,
  type RemoteCommandJobEvent,
  type RemoteCommandNetworkConfinement,
  type RemoteCommandNetworkClaim,
  type RemoteCommandPreflight,
  type RemoteCommandRequest,
  type RemoteCommandRuntimeOptions,
  type RemoteCommandSandboxLaunch,
  type RemoteCommandSandboxProcess,
  type RemoteCommandStatus,
} from "./remoteCommandRuntime.js";
import { createRemoteHttpsConnectNetworkAdapter } from "./remoteCommandNetwork.js";
import type { RemoteCommandAppArmorConfinement } from "./remoteCommandAppArmor.js";
import {
  loadRemoteCommandPermissions,
  type RemoteCommandPermissions,
  type RemoteCommandPolicy,
} from "./remoteCommandPermissions.js";
import { resolveRemoteCommandResourceGrants } from "./remoteCommandResourceGrants.js";
import { resolveStateDir } from "./storage.js";
import type { OpenMatesWsClient } from "./ws.js";

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const TERMINAL = new Set<RemoteCommandStatus>(["succeeded", "failed", "stopped", "timed_out"]);
const HEARTBEAT_MS = 30_000;
const RESPONSE_TIMEOUT_MS = 20_000;
const MAX_MODEL_TEXT_BYTES = 512 * 1024;

export interface RemoteCommandTrustedResourceGrants {
  writable_targets: Array<{ profile_id: string; host_path: string }>;
  network_profiles: Array<{ profile_id: string; destinations: string[] }>;
  credential_profiles: Array<{ profile_id: string; environment: Record<string, string> }>;
}

export interface RemoteCommandResourceContext {
  binding: LiveRemoteAccessBinding;
  permissions: RemoteCommandPermissions | null;
  policy: Readonly<RemoteCommandPolicy>;
}

export interface RemoteCommandSourceRuntimeHooks {
  capability?: () => RemoteCommandCapability;
  launchSandbox?: (launch: RemoteCommandSandboxLaunch) => RemoteCommandSandboxProcess;
  prepareNetworkConfinement?: (
    claim: RemoteCommandNetworkClaim,
    preflight: RemoteCommandPreflight,
  ) => Promise<RemoteCommandNetworkConfinement>;
  prepareAppArmorConfinement?: (preflight: RemoteCommandPreflight) => Promise<RemoteCommandAppArmorConfinement>;
  now?: () => Date;
  maxRetainedOutputBytes?: number;
}

export interface RemoteCommandSourceControllerOptions {
  client: OpenMatesClient;
  sourceSessionId: string;
  bindings: LiveRemoteAccessBinding[];
  resolveResourceGrants?: (context: RemoteCommandResourceContext) =>
    RemoteCommandTrustedResourceGrants | Promise<RemoteCommandTrustedResourceGrants>;
  toolchainPaths?: string[] | ((binding: LiveRemoteAccessBinding) => string[] | Promise<string[]>);
  runtime?: RemoteCommandSourceRuntimeHooks;
  responseTimeoutMs?: number;
}

export interface RemoteCommandSourceWebSocket {
  sendAsync(type: string, payload: unknown): Promise<void>;
  onMessageType<T = unknown>(type: string, handler: (payload: T) => void): () => void;
}

export interface RegisterRemoteCommandSourceOptions extends RemoteCommandSourceControllerOptions {
  ws: OpenMatesWsClient | RemoteCommandSourceWebSocket;
  controller?: RemoteCommandSourceController;
}

interface Lease {
  token: string;
  generation: number;
  expiresAt: number;
}

interface PendingEvent {
  eventKind: "status" | "output" | "output_truncated" | "terminal";
  status: RemoteCommandStatus;
  payload: Record<string, unknown>;
  assignedSequence?: number;
  encryptedEvent?: string;
}

interface ExecutionState {
  executionId: string;
  binding: LiveRemoteAccessBinding;
  runtime: RemoteCommandRuntime;
  portable: PortableRemoteCommandRequest | null;
  outerRequestDigest: string;
  internalRequestDigest: string | null;
  approval: RemoteCommandApprovalChoice | null;
  lease: Lease | null;
  nextSequence: number;
  pending: PendingEvent[];
  flushing: boolean;
  completed: boolean;
  stopped: boolean;
  lastSentAt: number;
  modelText: string;
  modelTextBytes: number;
  lastRuntimeOutputSequence: number | null;
  upstreamTruncated: boolean;
  sourceExcerptTruncated: boolean;
}

interface ClaimedRequest extends Record<string, unknown> {
  protocol_version: 1;
  execution_id: string;
  chat_id: string;
  project_id: string;
  source_id: string;
  state: string;
  encrypted_request: string;
  request_digest: string;
  approval: RemoteCommandApprovalChoice;
  key_epoch: number;
  lease_token: string;
  lease_generation: number;
  lease_expires_at: number;
  last_sequence?: number;
  launch_allowed?: boolean;
}

interface LeaseResponse extends Record<string, unknown> {
  execution_id: string;
  lease_token: string;
  lease_generation: number;
  lease_expires_at: number;
  last_sequence?: number;
}

interface BindingRuntime {
  binding: LiveRemoteAccessBinding;
  runtime: RemoteCommandRuntime;
  unsubscribe: () => void;
}

export class RemoteCommandSourceController {
  readonly #options: RemoteCommandSourceControllerOptions;
  readonly #bindingRuntimes = new Map<string, BindingRuntime>();
  readonly #states = new Map<string, ExecutionState>();
  readonly #claims = new Map<string, Promise<void>>();
  readonly #pendingRequests = new Set<{ ws: RemoteCommandSourceWebSocket; cancel: () => void }>();
  readonly #pendingStops = new Map<string, { projectId: string; sourceId: string }>();
  #ws: RemoteCommandSourceWebSocket | null = null;
  #detach: (() => void) | null = null;
  #closed = false;
  #stopping = false;
  #stopPromise: Promise<void> | null = null;
  #discovery: Promise<void> | null = null;
  #discoveryRequested = false;
  #heartbeat: NodeJS.Timeout;

  constructor(options: RemoteCommandSourceControllerOptions) {
    if (!IDENTIFIER.test(options.sourceSessionId)) throw new Error("Invalid remote command source session");
    if (!options.bindings.length) throw new Error("Remote command source requires at least one binding");
    this.#options = options;
    for (const binding of options.bindings) {
      const key = bindingKey(binding.source.projectId, binding.source.sourceId);
      if (!binding.source.projectId || !binding.source.sourceId || this.#bindingRuntimes.has(key)) {
        throw new Error("Remote command source bindings must be unique and complete");
      }
      if (!(binding.projectKey instanceof Uint8Array) || binding.projectKey.byteLength !== 32) {
        throw new Error("Remote command source binding has an invalid Project key");
      }
      assertSourceRootDoesNotExposeState(binding.source.rootPath);
      const runtime = this.#createRuntime(binding);
      const unsubscribe = runtime.subscribe((event) => this.#runtimeEvent(event));
      this.#bindingRuntimes.set(key, { binding, runtime, unsubscribe });
    }
    this.#heartbeat = setInterval(() => this.#heartbeatRunning(), HEARTBEAT_MS);
    this.#heartbeat.unref?.();
  }

  attach(ws: OpenMatesWsClient | RemoteCommandSourceWebSocket): () => void {
    if (this.#closed || this.#stopping) throw new Error("Remote command source controller is stopped");
    this.#detach?.();
    this.#ws = ws;
    for (const state of this.#states.values()) state.lease = null;
    const offAvailable = ws.onMessageType("remote_command_available", (payload) => {
      void this.#available(payload).catch(() => undefined);
    });
    const offStop = ws.onMessageType("remote_command_stop_requested", (payload) => {
      void this.#stopRequested(payload).catch(() => undefined);
    });
    let detached = false;
    const detach = () => {
      if (detached) return;
      detached = true;
      offAvailable();
      offStop();
      if (this.#ws === ws) {
        this.#ws = null;
        this.#cancelRequests(ws);
      }
      if (this.#detach === detach) this.#detach = null;
    };
    this.#detach = detach;
    this.#scheduleDiscovery();
    return detach;
  }

  stop(): Promise<void> {
    if (this.#stopPromise) return this.#stopPromise;
    this.#stopPromise = this.#stopOnce();
    return this.#stopPromise;
  }

  async #stopOnce(): Promise<void> {
    if (this.#closed) return;
    this.#stopping = true;
    clearInterval(this.#heartbeat);
    await Promise.allSettled([...this.#bindingRuntimes.values()].map(({ runtime }) => runtime.stopAll()));
    await this.#drainForShutdown();
    this.#closed = true;
    this.#detach?.();
    for (const { runtime, unsubscribe } of this.#bindingRuntimes.values()) {
      unsubscribe();
      await runtime.dispose().catch(() => undefined);
    }
    this.#states.clear();
  }

  #createRuntime(binding: LiveRemoteAccessBinding): RemoteCommandRuntime {
    const hooks = this.#options.runtime ?? {};
    const runtimeOptions: RemoteCommandRuntimeOptions = {
      approve: async (preflight) => this.#runtimeApproval(preflight),
      revalidateAuthority: async (preflight) => this.#runtimeAuthority(preflight),
      resolvePresetState: async () => {
        const config = loadRemoteCommandPermissions(binding.source.rootPath);
        if (!config) throw new RemoteCommandError("invalid_approval", "Command preset definition is unavailable");
        return { config, activeGrants: listRemoteCommandPresetGrants() };
      },
      ...(hooks.capability ? { capability: hooks.capability } : {}),
      ...(hooks.launchSandbox ? { launchSandbox: hooks.launchSandbox } : {}),
      prepareNetworkConfinement: hooks.prepareNetworkConfinement ?? createRemoteHttpsConnectNetworkAdapter(),
      ...(hooks.prepareAppArmorConfinement ? { prepareAppArmorConfinement: hooks.prepareAppArmorConfinement } : {}),
      ...(hooks.now ? { now: hooks.now } : {}),
      ...(hooks.maxRetainedOutputBytes === undefined ? {} : { maxRetainedOutputBytes: hooks.maxRetainedOutputBytes }),
    };
    return new RemoteCommandRuntime(runtimeOptions);
  }

  async #discover(): Promise<void> {
    for (const { binding } of this.#bindingRuntimes.values()) {
      if (!this.#ws || this.#closed || this.#stopping) return;
      const response = await this.#request(
        "remote_command_discover",
        {
          protocol_version: 1,
          project_id: binding.source.projectId,
          source_id: binding.source.sourceId,
          source_session_id: this.#options.sourceSessionId,
          ...(binding.teamId ? { team_id: binding.teamId } : {}),
        },
        "remote_command_jobs",
        () => true,
      );
      const body = record(response, "remote command discovery");
      if (!Array.isArray(body.jobs)) throw new Error("Invalid remote command discovery response");
      for (const value of body.jobs) {
        const job = validateSummary(value);
        if (job.project_id !== binding.source.projectId || job.source_id !== binding.source.sourceId) continue;
        const local = this.#states.get(job.execution_id);
        if (local && ["AWAITING_ORIGIN_COMPLETION", "TERMINAL"].includes(job.state)
          && local.pending.some((item) => item.eventKind === "terminal")) {
          local.pending = [];
          local.lease = null;
          local.completed = true;
        } else if (job.state === "WAITING_FOR_EXECUTOR") {
          await this.#claim(job, binding, true);
        } else if (local && local.runtime.get(job.execution_id)) {
          if (job.lease_expires_at > Math.floor(Date.now() / 1000)) await this.#claim(job, binding, false);
          else await this.#recover(job, local);
        }
      }
    }
  }

  #scheduleDiscovery(): void {
    if (this.#closed || this.#stopping || !this.#ws) return;
    if (this.#discovery) {
      this.#discoveryRequested = true;
      return;
    }
    this.#discoveryRequested = false;
    const discovery = this.#discover().finally(() => {
      if (this.#discovery === discovery) {
        this.#discovery = null;
        if (this.#discoveryRequested) this.#scheduleDiscovery();
      }
    });
    this.#discovery = discovery;
    void discovery.catch(() => undefined);
  }

  async #available(value: unknown): Promise<void> {
    if (this.#stopping || this.#closed) return;
    const summary = validateSummary(value);
    const bindingRuntime = this.#bindingRuntimes.get(bindingKey(summary.project_id, summary.source_id));
    if (!bindingRuntime || summary.state !== "WAITING_FOR_EXECUTOR") return;
    await this.#claim(summary, bindingRuntime.binding, true);
  }

  async #claim(summary: CommandSummary, binding: LiveRemoteAccessBinding, allowLaunch: boolean): Promise<void> {
    if (this.#stopping || this.#closed) return;
    const inFlight = this.#claims.get(summary.execution_id);
    if (inFlight) return inFlight;
    const claim = this.#claimOnce(summary, binding, allowLaunch)
      .finally(() => this.#claims.delete(summary.execution_id));
    this.#claims.set(summary.execution_id, claim);
    return claim;
  }

  async #claimOnce(summary: CommandSummary, binding: LiveRemoteAccessBinding, allowLaunch: boolean): Promise<void> {
    const response = await this.#request(
      "remote_command_claim",
      {
        protocol_version: 1,
        execution_id: summary.execution_id,
        project_id: summary.project_id,
        source_id: summary.source_id,
        source_session_id: this.#options.sourceSessionId,
        ...(binding.teamId ? { team_id: binding.teamId } : {}),
      },
      "remote_command_request",
      (payload) => record(payload, "remote command claim").execution_id === summary.execution_id,
      summary.execution_id,
    );
    const claimed = validateClaimedRequest(response, summary, binding, this.#options.sourceSessionId);
    let state = this.#states.get(claimed.execution_id);
    if (state) {
      if (state.outerRequestDigest !== claimed.request_digest
        || JSON.stringify(state.approval) !== JSON.stringify(claimed.approval)) {
        throw new RemoteCommandError("authority_revoked", "Reconnected command identity changed");
      }
      this.#applyLease(state, claimed);
      void this.#flush(state);
      return;
    }
    if (!allowLaunch) return;
    if (claimed.launch_allowed !== true) return;
    const bindingRuntime = this.#bindingRuntimes.get(bindingKey(claimed.project_id, claimed.source_id));
    if (!bindingRuntime) return;
    state = {
      executionId: claimed.execution_id,
      binding,
      runtime: bindingRuntime.runtime,
      portable: null,
      outerRequestDigest: claimed.request_digest,
      internalRequestDigest: null,
      approval: claimed.approval,
      lease: null,
      nextSequence: 0,
      pending: [],
      flushing: false,
      completed: false,
      stopped: false,
      lastSentAt: Date.now(),
      modelText: "",
      modelTextBytes: 0,
      lastRuntimeOutputSequence: null,
      upstreamTruncated: false,
      sourceExcerptTruncated: false,
    };
    this.#states.set(state.executionId, state);
    this.#applyLease(state, claimed);
    const pendingStop = this.#pendingStops.get(state.executionId);
    if (pendingStop) {
      this.#pendingStops.delete(state.executionId);
      if (pendingStop.projectId !== claimed.project_id || pendingStop.sourceId !== claimed.source_id) {
        throw new RemoteCommandError("authority_revoked", "Pending stop binding changed");
      }
      state.stopped = true;
      state.completed = true;
      this.#enqueue(state, { eventKind: "terminal", status: "stopped", payload: { stop_requested: true } });
      return;
    }
    try {
      const plaintext = await decryptWithAesGcmCombined(claimed.encrypted_request, binding.projectKey);
      if (!plaintext) throw new Error("Remote command request authentication failed");
      const portable = parsePortableRequest(plaintext);
      assertPortableBinding(portable, claimed);
      const digest = await remoteCommandPortableRequestDigest(binding.projectKey, portable);
      if (digest !== claimed.request_digest) throw new Error("Remote command request HMAC mismatch");
      state.portable = portable;
      const request = await this.#buildRuntimeRequest(binding, portable.policy, portable.execution_id);
      const preflight = createRemoteCommandPreflight(request);
      state.internalRequestDigest = preflight.request_digest;
      if (state.stopped) {
        state.completed = true;
        this.#enqueue(state, { eventKind: "terminal", status: "stopped", payload: { stop_requested: true } });
        return;
      }
      void state.runtime.start(request).catch(() => undefined);
    } catch (error) {
      state.completed = true;
      this.#enqueue(state, {
        eventKind: "terminal",
        status: "failed",
        payload: {
          error_code: error instanceof RemoteCommandError ? error.code : "invalid_request",
          error_message: error instanceof Error ? error.message : "Remote command request rejected",
        },
      });
    }
  }

  async #recover(summary: CommandSummary, state: ExecutionState): Promise<void> {
    const job = state.runtime.get(state.executionId);
    if (!job) return;
    const response = validateLeaseResponse(await this.#request(
      "remote_command_recover",
      {
        protocol_version: 1,
        execution_id: state.executionId,
        project_id: state.binding.source.projectId,
        source_id: state.binding.source.sourceId,
        source_session_id: this.#options.sourceSessionId,
        ...(state.binding.teamId ? { team_id: state.binding.teamId } : {}),
        last_sequence: summary.last_sequence,
        runtime_status: state.pending.some((item) => item.eventKind === "terminal")
          ? "terminal_pending"
          : state.stopped ? "stopping" : "running",
      },
      "remote_command_recovered",
      (payload) => record(payload, "remote command recovery").execution_id === state.executionId,
      state.executionId,
    ), state.executionId);
    if (response.launch_allowed !== false) throw new Error("Recovered command unexpectedly received launch authority");
    this.#applyLease(state, response);
    if (response.stop_requested === true) {
      state.stopped = true;
      await state.runtime.stop(state.executionId).catch(() => undefined);
    }
    void this.#flush(state);
  }

  #applyLease(state: ExecutionState, claimed: LeaseResponse): void {
    const serverLast = integer(claimed.last_sequence ?? -1, "last_sequence", -1);
    state.lease = {
      token: claimed.lease_token,
      generation: claimed.lease_generation,
      expiresAt: claimed.lease_expires_at,
    };
    while (state.pending[0]?.assignedSequence !== undefined
      && (state.pending[0].assignedSequence as number) <= serverLast) state.pending.shift();
    for (const pending of state.pending) {
      if (pending.assignedSequence !== undefined && pending.assignedSequence !== serverLast + 1) {
        pending.assignedSequence = undefined;
        pending.encryptedEvent = undefined;
      }
    }
    state.nextSequence = serverLast + 1;
  }

  async #buildRuntimeRequest(
    binding: LiveRemoteAccessBinding,
    policy: RemoteCommandPolicy,
    executionId: string,
  ): Promise<RemoteCommandRequest> {
    const permissions = loadRemoteCommandPermissions(binding.source.rootPath);
    const grants = await this.#resolveGrants({ binding, permissions, policy });
    const writableTargets = policy.writable_profiles.map((profileId) => {
      const definition = permissions?.resource_profiles.writable.find((item) => item.id === profileId);
      const grant = grants.writable_targets.find((item) => item.profile_id === profileId);
      if (!definition || !grant) throw new RemoteCommandError("resource_not_granted", `Writable profile is disabled: ${profileId}`);
      assertResourceDoesNotExposeState(grant.host_path, "Writable profile");
      return { profile_id: profileId, purpose: definition.purpose, host_path: grant.host_path };
    });
    const network = policy.network_profile === null ? null : (() => {
      const definition = permissions?.resource_profiles.network.find((item) => item.id === policy.network_profile);
      const grant = grants.network_profiles.find((item) => item.profile_id === policy.network_profile);
      if (!definition || !grant || !sameStrings(definition.destinations, grant.destinations)) {
        throw new RemoteCommandError("resource_not_granted", `Network profile is disabled: ${policy.network_profile}`);
      }
      return { profile_id: definition.id, destinations: [...definition.destinations] };
    })();
    const credentials = policy.credential_profiles.map((profileId) => {
      const definition = permissions?.resource_profiles.credentials.find((item) => item.id === profileId);
      const grant = grants.credential_profiles.find((item) => item.profile_id === profileId);
      if (!definition || !grant || !sameStrings(definition.environment, Object.keys(grant.environment))) {
        throw new RemoteCommandError("credential_unavailable", `Credential profile is disabled: ${profileId}`);
      }
      return { profile_id: profileId, environment: [...definition.environment] };
    });
    return {
      execution_id: executionId,
      project_id: binding.source.projectId as string,
      source_root: binding.source.rootPath,
      policy,
      toolchain_paths: await this.#toolchainPaths(binding),
      writable_targets: writableTargets,
      network,
      credentials,
    };
  }

  async #runtimeApproval(preflight: RemoteCommandPreflight) {
    const state = this.#requireState(preflight);
    if (!state.approval || state.stopped) return null;
    if (state.approval.kind === "one_run") {
      return { kind: "one_run" as const, execution_id: state.executionId, request_digest: preflight.request_digest };
    }
    return {
      kind: "preset" as const,
      preset_id: state.approval.preset_id,
      definition_digest: state.approval.definition_digest,
      request_digest: preflight.request_digest,
    };
  }

  async #runtimeAuthority(preflight: RemoteCommandPreflight): Promise<RemoteCommandAuthority> {
    const state = this.#requireState(preflight);
    if (state.stopped || this.#closed || this.#stopping || !state.portable || !state.lease) return deniedAuthority(preflight);
    const current = await this.#buildRuntimeRequest(state.binding, state.portable.policy, state.executionId);
    const currentPreflight = createRemoteCommandPreflight(current);
    if (currentPreflight.request_digest !== preflight.request_digest
      || state.internalRequestDigest !== preflight.request_digest) return deniedAuthority(preflight);
    const response = record(await this.#request(
      "remote_command_revalidate",
      this.#leasePayload(state),
      "remote_command_authority",
      (payload) => record(payload, "remote command authority").execution_id === state.executionId,
      state.executionId,
    ), "remote command authority");
    if (response.request_digest !== state.outerRequestDigest || response.authorized !== true || response.stop_requested === true) {
      state.stopped = response.stop_requested === true;
      return deniedAuthority(preflight);
    }
    const grants = await this.#resolveGrants({
      binding: state.binding,
      permissions: loadRemoteCommandPermissions(state.binding.source.rootPath),
      policy: state.portable.policy,
    });
    return {
      authorized: true,
      project_id: preflight.project_id,
      source_root: state.binding.source.rootPath,
      request_digest: preflight.request_digest,
      toolchain_paths: await this.#toolchainPaths(state.binding),
      writable_targets: grants.writable_targets,
      network_profiles: grants.network_profiles,
      credential_profiles: grants.credential_profiles,
    };
  }

  #requireState(preflight: RemoteCommandPreflight): ExecutionState {
    const state = this.#states.get(preflight.execution_id);
    if (!state || state.binding.source.projectId !== preflight.project_id) {
      throw new RemoteCommandError("authority_revoked", "Remote command execution binding is unavailable");
    }
    if (state.internalRequestDigest && state.internalRequestDigest !== preflight.request_digest) {
      throw new RemoteCommandError("invalid_approval", "Canonical runtime request digest changed");
    }
    return state;
  }

  async #resolveGrants(context: RemoteCommandResourceContext): Promise<RemoteCommandTrustedResourceGrants> {
    const grants = this.#options.resolveResourceGrants
      ? await this.#options.resolveResourceGrants(context)
      : resolveRemoteCommandResourceGrants(context);
    return validateTrustedGrants(grants);
  }

  async #toolchainPaths(binding: LiveRemoteAccessBinding): Promise<string[]> {
    const configured = typeof this.#options.toolchainPaths === "function"
      ? await this.#options.toolchainPaths(binding)
      : this.#options.toolchainPaths ?? defaultToolchainPaths();
    if (!Array.isArray(configured) || configured.some((path) => typeof path !== "string")) {
      throw new RemoteCommandError("resource_not_granted", "Invalid trusted toolchain profile");
    }
    for (const path of configured) assertResourceDoesNotExposeState(path, "Toolchain");
    return [...configured];
  }

  #runtimeEvent(event: RemoteCommandJobEvent): void {
    const state = this.#states.get(event.execution_id);
    if (!state) return;
    if (event.type === "status") {
      const terminal = TERMINAL.has(event.job.status);
      state.completed = terminal;
      this.#enqueue(state, {
        eventKind: terminal ? "terminal" : "status",
        status: event.job.status,
        payload: terminal ? {
          job: event.job,
          output_selection: {
            coverage: state.upstreamTruncated || state.sourceExcerptTruncated ? "selected_excerpt" : "full",
            upstream_truncated: state.upstreamTruncated || event.job.output_truncated,
            source_excerpt_truncated: state.sourceExcerptTruncated,
          },
        } : { job: event.job },
      });
    } else if (event.type === "output") {
      if (state.lastRuntimeOutputSequence !== null && event.sequence !== state.lastRuntimeOutputSequence + 1) {
        state.upstreamTruncated = true;
      }
      state.lastRuntimeOutputSequence = event.sequence;
      this.#appendModelText(state, event.stream, event.text);
      this.#enqueue(state, {
        eventKind: "output",
        status: state.runtime.get(event.execution_id)?.status ?? "running",
        payload: { stream: event.stream, text: event.text, trusted: false },
      });
    } else {
      state.upstreamTruncated = true;
      this.#enqueue(state, {
        eventKind: "output_truncated",
        status: state.runtime.get(event.execution_id)?.status ?? "running",
        payload: { retained_bytes: event.retained_bytes },
      });
    }
  }

  #enqueue(state: ExecutionState, event: PendingEvent): void {
    if (state.pending.some((item) => item.eventKind === "terminal")) return;
    state.pending.push(event);
    void this.#flush(state);
  }

  #appendModelText(state: ExecutionState, stream: "stdout" | "stderr", value: string): void {
    const prefix = state.modelText && !state.modelText.endsWith("\n") ? "\n" : "";
    const candidate = `${prefix}[${stream}] ${value}`;
    const available = MAX_MODEL_TEXT_BYTES - state.modelTextBytes;
    if (available <= 0) {
      state.sourceExcerptTruncated = true;
      return;
    }
    const bounded = truncateUtf8(candidate, available);
    if (Buffer.byteLength(bounded) < Buffer.byteLength(candidate)) state.sourceExcerptTruncated = true;
    state.modelText += bounded;
    state.modelTextBytes += Buffer.byteLength(bounded);
  }

  async #flush(state: ExecutionState): Promise<void> {
    if (state.flushing) return;
    state.flushing = true;
    try {
      while (!this.#closed && this.#ws && state.lease && state.pending.length) {
        const requestLease = state.lease;
        const item = state.pending[0] as PendingEvent;
        const sequence = item.assignedSequence ?? state.nextSequence;
        item.assignedSequence = sequence;
        const encryptedEvent = item.encryptedEvent ?? await encryptWithAesGcmCombined(JSON.stringify({
          execution_id: state.executionId,
          sequence,
          event_kind: item.eventKind,
          status: item.status,
          ...item.payload,
        }), state.binding.projectKey);
        item.encryptedEvent = encryptedEvent;
        try {
          const isTerminal = item.eventKind === "terminal";
          const ack = record(await this.#request(
            isTerminal ? "remote_command_source_completion" : "remote_command_event",
            isTerminal ? {
              ...this.#leasePayload(state),
              sequence,
              status: item.status,
              encrypted_event: encryptedEvent,
              model_text: completionModelText(state, item.status),
            } : {
              ...this.#leasePayload(state),
              sequence,
              event_kind: item.eventKind,
              status: item.status,
              encrypted_event: encryptedEvent,
            },
            isTerminal ? "remote_command_source_completion_ack" : "remote_command_event_ack",
            (payload) => record(payload, "remote command event acknowledgement").execution_id === state.executionId,
            state.executionId,
          ), "remote command event acknowledgement");
          if (integer(ack.last_sequence, "last_sequence", -1) < sequence) throw new Error("Remote command event was not acknowledged");
          state.pending.shift();
          state.nextSequence = sequence + 1;
          state.lastSentAt = Date.now();
          if (item.eventKind === "terminal") state.lease = null;
        } catch {
          if (state.lease === requestLease) state.lease = null;
          break;
        }
      }
    } finally {
      state.flushing = false;
    }
  }

  async #drainForShutdown(): Promise<void> {
    if (!this.#ws) return;
    const deadline = Date.now() + Math.min(this.#options.responseTimeoutMs ?? RESPONSE_TIMEOUT_MS, 5_000);
    while (Date.now() < deadline) {
      await Promise.all([...this.#states.values()].map((state) => this.#flush(state)));
      if ([...this.#states.values()].every((state) => !state.flushing && state.pending.length === 0)) return;
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 20));
    }
  }

  #leasePayload(state: ExecutionState): Record<string, unknown> {
    if (!state.lease) throw new RemoteCommandError("authority_revoked", "Remote command lease is unavailable");
    return {
      protocol_version: 1,
      execution_id: state.executionId,
      project_id: state.binding.source.projectId,
      source_id: state.binding.source.sourceId,
      source_session_id: this.#options.sourceSessionId,
      ...(state.binding.teamId ? { team_id: state.binding.teamId } : {}),
      lease_token: state.lease.token,
      lease_generation: state.lease.generation,
    };
  }

  async #stopRequested(value: unknown): Promise<void> {
    const summary = validateSummary(value);
    const state = this.#states.get(summary.execution_id);
    if (!state) {
      if (!this.#bindingRuntimes.has(bindingKey(summary.project_id, summary.source_id))) return;
      if (this.#pendingStops.size >= 1_024) this.#pendingStops.delete(this.#pendingStops.keys().next().value as string);
      this.#pendingStops.set(summary.execution_id, { projectId: summary.project_id, sourceId: summary.source_id });
      return;
    }
    if (state.binding.source.projectId !== summary.project_id || state.binding.source.sourceId !== summary.source_id) return;
    state.stopped = true;
    if (state.runtime.get(state.executionId)) {
      await state.runtime.stop(state.executionId).catch(() => undefined);
    } else {
      state.completed = true;
      this.#enqueue(state, { eventKind: "terminal", status: "stopped", payload: { stop_requested: true } });
    }
  }

  #heartbeatRunning(): void {
    if (!this.#ws || this.#closed) return;
    let needsDiscovery = false;
    const nowSeconds = Math.floor(Date.now() / 1000);
    for (const state of this.#states.values()) {
      const job = state.runtime.get(state.executionId);
      if (!job || TERMINAL.has(job.status)) continue;
      if (!state.lease || state.lease.expiresAt <= nowSeconds) {
        state.lease = null;
        needsDiscovery = true;
        continue;
      }
      if (job.status !== "running" || state.pending.length
        || Date.now() - state.lastSentAt < HEARTBEAT_MS) continue;
      this.#enqueue(state, { eventKind: "status", status: "running", payload: { job } });
    }
    if (needsDiscovery) this.#scheduleDiscovery();
  }

  async #request(
    requestType: string,
    payload: unknown,
    responseType: string,
    predicate: (payload: unknown) => boolean,
    executionId?: string,
  ): Promise<unknown> {
    const ws = this.#ws;
    if (!ws) throw new Error("Remote command source transport is disconnected");
    const timeoutMs = this.#options.responseTimeoutMs ?? RESPONSE_TIMEOUT_MS;
    return new Promise<unknown>((resolvePromise, rejectPromise) => {
      let settled = false;
      let offResponse: () => void = () => undefined;
      let offError: () => void = () => undefined;
      const pending = {
        ws,
        cancel: () => finish(new Error("Remote command source transport disconnected")),
      };
      const finish = (error: Error | null, result?: unknown) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        offResponse();
        offError();
        this.#pendingRequests.delete(pending);
        if (error) rejectPromise(error);
        else resolvePromise(result);
      };
      offResponse = ws.onMessageType(responseType, (response) => {
        try { if (predicate(response)) finish(null, response); } catch (error) { finish(asError(error)); }
      });
      offError = ws.onMessageType("remote_command_error", (response) => {
        const error = record(response, "remote command error");
        if (executionId && error.execution_id !== executionId) return;
        finish(Object.assign(new Error(typeof error.code === "string" ? error.code : "remote_command_failed"), {
          code: typeof error.code === "string" ? error.code : "remote_command_failed",
        }));
      });
      const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${responseType}`)), timeoutMs);
      this.#pendingRequests.add(pending);
      void ws.sendAsync(requestType, payload).catch((error) => finish(asError(error)));
    });
  }

  #cancelRequests(ws: RemoteCommandSourceWebSocket): void {
    for (const pending of [...this.#pendingRequests]) {
      if (pending.ws === ws) pending.cancel();
    }
  }
}

export function createRemoteCommandSourceController(
  options: RemoteCommandSourceControllerOptions,
): RemoteCommandSourceController {
  return new RemoteCommandSourceController(options);
}

export function registerRemoteCommandSource(options: RegisterRemoteCommandSourceOptions): () => Promise<void> {
  const controller = options.controller ?? createRemoteCommandSourceController(options);
  const detach = controller.attach(options.ws);
  return async () => {
    detach();
    if (!options.controller) await controller.stop();
  };
}

interface CommandSummary {
  protocol_version: 1;
  execution_id: string;
  chat_id: string;
  project_id: string;
  source_id: string;
  state: string;
  last_sequence: number;
  lease_expires_at: number;
}

function validateSummary(value: unknown): CommandSummary {
  const item = record(value, "remote command summary");
  if (item.protocol_version !== 1) throw new Error("Invalid remote command protocol version");
  return {
    protocol_version: 1,
    execution_id: identifier(item.execution_id, "execution_id"),
    chat_id: identifier(item.chat_id, "chat_id"),
    project_id: identifier(item.project_id, "project_id"),
    source_id: identifier(item.source_id, "source_id"),
    state: text(item.state, "state"),
    last_sequence: integer(item.last_sequence ?? -1, "last_sequence", -1),
    lease_expires_at: integer(item.lease_expires_at ?? 0, "lease_expires_at", 0),
  };
}

function validateClaimedRequest(
  value: unknown,
  summary: CommandSummary,
  binding: LiveRemoteAccessBinding,
  sourceSessionId: string,
): ClaimedRequest {
  const item = record(value, "remote command request");
  if (item.protocol_version !== 1
    || item.execution_id !== summary.execution_id
    || item.chat_id !== summary.chat_id
    || item.project_id !== binding.source.projectId
    || item.source_id !== binding.source.sourceId
    || (item.team_id ?? undefined) !== binding.teamId
    || !IDENTIFIER.test(sourceSessionId)
    || item.key_epoch !== binding.keyEpoch) throw new Error("Remote command server binding mismatch");
  const approval = parseApproval(item.approval);
  return {
    ...item,
    protocol_version: 1,
    execution_id: identifier(item.execution_id, "execution_id"),
    chat_id: identifier(item.chat_id, "chat_id"),
    project_id: identifier(item.project_id, "project_id"),
    source_id: identifier(item.source_id, "source_id"),
    state: text(item.state, "state"),
    encrypted_request: text(item.encrypted_request, "encrypted_request"),
    request_digest: text(item.request_digest, "request_digest"),
    approval,
    key_epoch: integer(item.key_epoch, "key_epoch", 1),
    lease_token: text(item.lease_token, "lease_token"),
    lease_generation: integer(item.lease_generation, "lease_generation", 1),
    lease_expires_at: integer(item.lease_expires_at, "lease_expires_at", 1),
    last_sequence: integer(item.last_sequence ?? -1, "last_sequence", -1),
    launch_allowed: item.launch_allowed === true,
  };
}

function validateLeaseResponse(value: unknown, executionId: string): LeaseResponse & {
  launch_allowed: boolean;
  stop_requested: boolean;
} {
  const item = record(value, "remote command recovery");
  if (item.execution_id !== executionId) throw new Error("Remote command recovery identity mismatch");
  return {
    ...item,
    execution_id: executionId,
    lease_token: text(item.lease_token, "lease_token"),
    lease_generation: integer(item.lease_generation, "lease_generation", 1),
    lease_expires_at: integer(item.lease_expires_at, "lease_expires_at", 1),
    last_sequence: integer(item.last_sequence ?? -1, "last_sequence", -1),
    launch_allowed: item.launch_allowed === true,
    stop_requested: item.stop_requested === true,
  };
}

function parsePortableRequest(plaintext: string): PortableRemoteCommandRequest {
  const item = record(JSON.parse(plaintext), "portable remote command request");
  exactKeys(item, ["protocol_version", "execution_id", "chat_id", "project_id", "source_id", "policy", "approval"]);
  if (item.protocol_version !== 1) throw new Error("Invalid portable remote command protocol");
  const policy = parsePolicy(item.policy);
  const request: PortableRemoteCommandRequest = {
    protocol_version: 1,
    execution_id: identifier(item.execution_id, "execution_id"),
    chat_id: identifier(item.chat_id, "chat_id"),
    project_id: identifier(item.project_id, "project_id"),
    source_id: identifier(item.source_id, "source_id"),
    policy,
    approval: parseApproval(item.approval),
  };
  if (canonicalPortableRemoteCommandRequest(request) !== plaintext) {
    throw new Error("Portable remote command is not canonical");
  }
  return request;
}

function parsePolicy(value: unknown): RemoteCommandPolicy {
  const policy = record(value, "remote command policy");
  exactKeys(policy, [
    "argv", "cwd", "mode", "source_access", "deadline_ms",
    "writable_profiles", "network_profile", "credential_profiles",
  ]);
  if (!Array.isArray(policy.argv) || policy.argv.some((item) => typeof item !== "string")) throw new Error("Invalid command argv");
  if (!Array.isArray(policy.writable_profiles) || policy.writable_profiles.some((item) => typeof item !== "string")) throw new Error("Invalid writable profiles");
  if (!Array.isArray(policy.credential_profiles) || policy.credential_profiles.some((item) => typeof item !== "string")) throw new Error("Invalid credential profiles");
  return {
    argv: [...policy.argv] as string[],
    cwd: text(policy.cwd, "cwd"),
    mode: oneOf(policy.mode, ["foreground", "background"] as const, "mode"),
    source_access: oneOf(policy.source_access, ["read_only", "read_write"] as const, "source_access"),
    deadline_ms: integer(policy.deadline_ms, "deadline_ms", 100),
    writable_profiles: [...policy.writable_profiles] as string[],
    network_profile: policy.network_profile === null ? null : text(policy.network_profile, "network_profile"),
    credential_profiles: [...policy.credential_profiles] as string[],
  };
}

function parseApproval(value: unknown): RemoteCommandApprovalChoice {
  const approval = record(value, "remote command approval");
  if (approval.kind === "one_run") {
    exactKeys(approval, ["kind"]);
    return { kind: "one_run" };
  }
  exactKeys(approval, ["kind", "preset_id", "definition_digest"]);
  if (approval.kind !== "preset" || typeof approval.definition_digest !== "string"
    || !/^[a-f0-9]{64}$/i.test(approval.definition_digest)) throw new Error("Invalid preset approval");
  return {
    kind: "preset",
    preset_id: identifier(approval.preset_id, "preset_id"),
    definition_digest: approval.definition_digest,
  };
}

function assertPortableBinding(portable: PortableRemoteCommandRequest, claimed: ClaimedRequest): void {
  if (portable.execution_id !== claimed.execution_id
    || portable.chat_id !== claimed.chat_id
    || portable.project_id !== claimed.project_id
    || portable.source_id !== claimed.source_id
    || JSON.stringify(portable.approval) !== JSON.stringify(claimed.approval)) {
    throw new Error("Encrypted remote command binding mismatch");
  }
}

function validateTrustedGrants(value: RemoteCommandTrustedResourceGrants): RemoteCommandTrustedResourceGrants {
  if (!value || !Array.isArray(value.writable_targets)
    || !Array.isArray(value.network_profiles) || !Array.isArray(value.credential_profiles)) {
    throw new RemoteCommandError("resource_not_granted", "Trusted resource grant state is invalid");
  }
  const result = {
    writable_targets: value.writable_targets.map((item) => ({
      profile_id: identifier(item.profile_id, "writable profile"),
      host_path: text(item.host_path, "writable host path"),
    })),
    network_profiles: value.network_profiles.map((item) => {
      if (!Array.isArray(item.destinations) || item.destinations.some((destination) => typeof destination !== "string")) {
        throw new RemoteCommandError("resource_not_granted", "Trusted network grant is invalid");
      }
      return {
        profile_id: identifier(item.profile_id, "network profile"),
        destinations: item.destinations.map((destination) => text(destination, "network destination")),
      };
    }),
    credential_profiles: value.credential_profiles.map((item) => {
      if (!item.environment || typeof item.environment !== "object" || Array.isArray(item.environment)
        || Object.entries(item.environment).some(([name, secret]) => !/^[A-Z_][A-Z0-9_]{0,127}$/.test(name)
          || typeof secret !== "string" || secret.includes("\0") || Buffer.byteLength(secret) > 64 * 1024)) {
        throw new RemoteCommandError("credential_unavailable", "Trusted credential grant is invalid");
      }
      return {
        profile_id: identifier(item.profile_id, "credential profile"),
        environment: { ...item.environment },
      };
    }),
  };
  for (const group of [result.writable_targets, result.network_profiles, result.credential_profiles]) {
    if (new Set(group.map((item) => item.profile_id)).size !== group.length) {
      throw new RemoteCommandError("resource_not_granted", "Trusted resource grants contain duplicates");
    }
  }
  return result;
}

function deniedAuthority(preflight: RemoteCommandPreflight): RemoteCommandAuthority {
  return {
    authorized: false,
    project_id: preflight.project_id,
    source_root: preflight.source_root,
    request_digest: preflight.request_digest,
    toolchain_paths: [],
    writable_targets: [],
    network_profiles: [],
    credential_profiles: [],
  };
}

function defaultToolchainPaths(): string[] {
  const candidates = ["/usr", dirname(realpathSync(process.execPath)), "/etc/ssl/certs"]
    .filter((path) => existsSync(path) && statSync(path).isDirectory())
    .map((path) => realpathSync(path));
  return [...new Set(candidates)].filter((path, index, paths) => !paths.some((parent, parentIndex) => (
    parentIndex !== index && isInsideDirectory(parent, path)
  )));
}

function assertSourceRootDoesNotExposeState(sourceRoot: string): void {
  try {
    const root = realpathSync(sourceRoot);
    if (pathsOverlap(root, canonicalStateDirectory())) {
      throw new Error("Project source cannot contain OpenMates private state");
    }
  } catch (error) {
    if (error instanceof Error && error.message === "Project source cannot contain OpenMates private state") throw error;
    throw new Error("Project source root is unavailable");
  }
}

function assertResourceDoesNotExposeState(path: string, context: string): void {
  try {
    if (pathsOverlap(realpathSync(path), canonicalStateDirectory())) {
      throw new RemoteCommandError("resource_not_granted", `${context} overlaps OpenMates private state`);
    }
  } catch (error) {
    if (error instanceof RemoteCommandError) throw error;
    throw new RemoteCommandError("resource_not_granted", `${context} path is unavailable`);
  }
}

function canonicalStateDirectory(): string {
  const path = resolveStateDir();
  if (existsSync(path)) return realpathSync(path);
  const tail: string[] = [];
  let parent = resolve(path);
  while (!existsSync(parent)) {
    const next = dirname(parent);
    if (next === parent) break;
    tail.unshift(basename(parent));
    parent = next;
  }
  return resolve(realpathSync(parent), ...tail);
}

function pathsOverlap(left: string, right: string): boolean {
  return left === right || isInsideDirectory(left, right) || isInsideDirectory(right, left);
}

function isInsideDirectory(parent: string, child: string): boolean {
  const value = relative(parent, child);
  return value !== "" && !value.startsWith("..") && !value.startsWith("/");
}

function bindingKey(projectId: string | undefined, sourceId: string): string {
  return `${projectId ?? ""}\0${sourceId}`;
}

function record(value: unknown, context: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`Invalid ${context}`);
  return value as Record<string, unknown>;
}
function exactKeys(value: Record<string, unknown>, keys: string[]): void {
  if (Object.keys(value).length !== keys.length || Object.keys(value).some((key) => !keys.includes(key))) throw new Error("Remote command request contains unexpected fields");
}
function identifier(value: unknown, context: string): string {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) throw new Error(`Invalid ${context}`);
  return value;
}
function text(value: unknown, context: string): string {
  if (typeof value !== "string" || !value || value.length > 1_048_576 || value.includes("\0")) throw new Error(`Invalid ${context}`);
  return value;
}
function integer(value: unknown, context: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum) throw new Error(`Invalid ${context}`);
  return Number(value);
}
function oneOf<T extends string>(value: unknown, choices: readonly T[], context: string): T {
  if (typeof value !== "string" || !choices.includes(value as T)) throw new Error(`Invalid ${context}`);
  return value as T;
}
function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
}
function truncateUtf8(value: string, maximum: number): string {
  const bytes = Buffer.from(value);
  if (bytes.length <= maximum) return value;
  return bytes.subarray(0, maximum).toString("utf8").replace(/\uFFFD$/, "");
}
function completionModelText(state: ExecutionState, status: RemoteCommandStatus): string {
  const incomplete = state.upstreamTruncated || state.sourceExcerptTruncated;
  const marker = incomplete ? "[OpenMates output excerpt is incomplete]\n" : "";
  const content = state.modelText || `Command ${status}.`;
  return `${marker}${truncateUtf8(content, MAX_MODEL_TEXT_BYTES - Buffer.byteLength(marker))}`;
}
function asError(value: unknown): Error { return value instanceof Error ? value : new Error(String(value)); }
