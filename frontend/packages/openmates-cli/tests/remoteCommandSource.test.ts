import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import { describe, it } from "node:test";

import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "../src/crypto.ts";
import type { LiveRemoteAccessBinding } from "../src/remoteAccess.ts";
import {
  canonicalPortableRemoteCommandRequest,
  remoteCommandPortableRequestDigest,
  type PortableRemoteCommandRequest,
} from "../src/remoteCommandClient.ts";
import type { RemoteCommandSandboxProcess } from "../src/remoteCommandRuntime.ts";
import {
  createRemoteCommandSourceController,
  type RemoteCommandSourceWebSocket,
} from "../src/remoteCommandSource.ts";

class FakeProcess implements RemoteCommandSandboxProcess {
  readonly stdout = new PassThrough();
  readonly stderr = new PassThrough();
  readonly #events = new EventEmitter();
  #result: { code: number | null; signal: NodeJS.Signals | null } | null = null;
  terminated = false;

  wait(): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
    return this.#result
      ? Promise.resolve(this.#result)
      : new Promise((resolvePromise) => this.#events.once("exit", resolvePromise));
  }

  async terminate(): Promise<void> { this.terminated = true; this.exit(null, "SIGTERM"); }

  exit(code: number | null, signal: NodeJS.Signals | null = null): void {
    if (this.#result) return;
    this.#result = { code, signal };
    this.stdout.end();
    this.stderr.end();
    this.#events.emit("exit", this.#result);
  }
}

type Handler = (payload: unknown) => void;

class FakeWebSocket implements RemoteCommandSourceWebSocket {
  readonly sent: Array<{ type: string; payload: Record<string, unknown> }> = [];
  readonly #handlers = new Map<string, Set<Handler>>();
  responder: (type: string, payload: Record<string, unknown>, ws: FakeWebSocket) => void = () => undefined;

  async sendAsync(type: string, value: unknown): Promise<void> {
    const payload = value as Record<string, unknown>;
    this.sent.push({ type, payload });
    queueMicrotask(() => this.responder(type, payload, this));
  }

  onMessageType<T = unknown>(type: string, handler: (payload: T) => void): () => void {
    const handlers = this.#handlers.get(type) ?? new Set<Handler>();
    const wrapped = handler as Handler;
    handlers.add(wrapped);
    this.#handlers.set(type, handlers);
    return () => handlers.delete(wrapped);
  }

  emit(type: string, payload: unknown): void {
    for (const handler of this.#handlers.get(type) ?? []) handler(payload);
  }
}

async function fixture(options: { digest?: string } = {}) {
  const base = mkdtempSync(join(tmpdir(), "openmates-command-source-"));
  const project = join(base, "project");
  const toolchain = join(base, "toolchain");
  mkdirSync(project);
  mkdirSync(toolchain);
  const projectKey = new Uint8Array(32).fill(5);
  const binding: LiveRemoteAccessBinding = {
    source: {
      sourceId: "source-1", projectId: "project-1", sourceType: "local_folder",
      rootPath: project, displayName: "Project", cachePath: join(base, "cache"),
      status: "connected", createdAt: 1, updatedAt: 1,
    },
    projectKey,
    keyEpoch: 3,
  };
  const portable: PortableRemoteCommandRequest = {
    protocol_version: 1,
    execution_id: "execution-1",
    chat_id: "chat-1",
    project_id: "project-1",
    source_id: "source-1",
    policy: {
      argv: ["tool", "check"], cwd: ".", mode: "foreground", source_access: "read_only",
      deadline_ms: 5_000, writable_profiles: [], network_profile: null, credential_profiles: [],
    },
    approval: { kind: "one_run" },
  };
  const encryptedRequest = await encryptWithAesGcmCombined(canonicalPortableRemoteCommandRequest(portable), projectKey);
  const digest = options.digest ?? await remoteCommandPortableRequestDigest(projectKey, portable);
  const server = {
    state: "WAITING_FOR_EXECUTOR",
    lastSequence: -1,
    leaseExpiresAt: Math.floor(Date.now() / 1000) + 90,
    claims: 0,
    recoveries: 0,
    revalidations: 0,
    completions: 0,
  };
  const summary = () => ({
    protocol_version: 1, execution_id: portable.execution_id, chat_id: portable.chat_id,
    project_id: portable.project_id, source_id: portable.source_id, state: server.state,
    last_sequence: server.lastSequence, lease_expires_at: server.leaseExpiresAt,
  });
  const claimed = () => ({
    ...summary(), encrypted_request: encryptedRequest, request_digest: digest,
    approval: portable.approval, key_epoch: binding.keyEpoch, lease_token: "lease-token",
    lease_generation: server.recoveries + 1, launch_allowed: server.state === "WAITING_FOR_EXECUTOR",
  });
  const wire = (ws: FakeWebSocket) => {
    ws.responder = (type, payload, socket) => {
      if (type === "remote_command_discover") socket.emit("remote_command_jobs", { jobs: server.state === "ABSENT" ? [] : [summary()] });
      else if (type === "remote_command_claim") {
        server.claims += 1;
        const response = claimed();
        server.state = "RUNNING";
        socket.emit("remote_command_request", response);
      } else if (type === "remote_command_revalidate") {
        server.revalidations += 1;
        socket.emit("remote_command_authority", {
          ...summary(), request_digest: digest, authorized: true, stop_requested: false,
        });
      } else if (type === "remote_command_event") {
        server.lastSequence = Number(payload.sequence);
        socket.emit("remote_command_event_ack", { ...summary() });
      } else if (type === "remote_command_source_completion") {
        server.lastSequence = Number(payload.sequence);
        server.state = "AWAITING_ORIGIN_COMPLETION";
        server.completions += 1;
        socket.emit("remote_command_source_completion_ack", { ...summary() });
      } else if (type === "remote_command_recover") {
        server.recoveries += 1;
        server.leaseExpiresAt = Math.floor(Date.now() / 1000) + 90;
        socket.emit("remote_command_recovered", {
          ...summary(), lease_token: "recovered-token", lease_generation: server.recoveries + 1,
          launch_allowed: false, stop_requested: false,
        });
      }
    };
    return ws;
  };
  return {
    base, project, toolchain, projectKey, binding, portable, server, summary, wire,
    cleanup: () => rmSync(base, { recursive: true, force: true }),
  };
}

const supported = () => ({
  supported: true, platform: "linux" as const, mechanism: "bubblewrap" as const, executable: "/usr/bin/bwrap",
});

async function until(predicate: () => boolean, message: string): Promise<void> {
  const deadline = Date.now() + 3_000;
  while (!predicate() && Date.now() < deadline) await new Promise((resolvePromise) => setTimeout(resolvePromise, 10));
  assert.ok(predicate(), message);
}

describe("remote command source transport", () => {
  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.explicit-approval,code-run.remote.managed-jobs
  it("authenticates, freshly revalidates, and emits encrypted ordered events with a bounded terminal excerpt", async () => {
    const item = await fixture();
    const process = new FakeProcess();
    const ws = item.wire(new FakeWebSocket());
    let launches = 0;
    let launchedRoot = "";
    const controller = createRemoteCommandSourceController({
      client: {} as never,
      sourceSessionId: "session-1",
      bindings: [item.binding],
      toolchainPaths: [item.toolchain],
      runtime: {
        capability: supported,
        launchSandbox: (launch) => { launches += 1; launchedRoot = launch.preflight.source_root; return process; },
      },
      responseTimeoutMs: 1_000,
    });
    const detach = controller.attach(ws);
    try {
      await until(() => launches === 1, "command did not launch");
      assert.equal(launchedRoot, item.project);
      assert.equal(item.server.revalidations, 2);
      process.stdout.write("hello from command\n");
      process.exit(0);
      await until(() => item.server.completions === 1, "terminal completion was not delivered");

      const wireEvents = ws.sent.filter((entry) => entry.type === "remote_command_event");
      const completion = ws.sent.find((entry) => entry.type === "remote_command_source_completion");
      assert.ok(wireEvents.length >= 3);
      assert.ok(completion);
      const sequences = [...wireEvents, completion].map((entry) => Number(entry?.payload.sequence));
      assert.deepEqual(sequences, sequences.map((_, index) => index));
      assert.equal(completion?.payload.model_text, "[stdout] hello from command\n");
      for (const entry of wireEvents) {
        assert.doesNotMatch(JSON.stringify(entry.payload), /hello from command|openmates-command-source|050505/);
      }
      assert.doesNotMatch(JSON.stringify(completion?.payload), /openmates-command-source|050505/);
      const terminalPlaintext = await decryptWithAesGcmCombined(String(completion?.payload.encrypted_event), item.projectKey);
      assert.equal(JSON.parse(terminalPlaintext ?? "null").event_kind, "terminal");
    } finally {
      detach();
      await controller.stop();
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.explicit-approval,code-run.remote.managed-jobs
  it("rejects a request whose Project-key HMAC does not match without launching", async () => {
    const item = await fixture({ digest: "invalid-digest" });
    const ws = item.wire(new FakeWebSocket());
    let launches = 0;
    const controller = createRemoteCommandSourceController({
      client: {} as never, sourceSessionId: "session-1", bindings: [item.binding],
      toolchainPaths: [item.toolchain],
      runtime: { capability: supported, launchSandbox: () => { launches += 1; return new FakeProcess(); } },
      responseTimeoutMs: 1_000,
    });
    controller.attach(ws);
    try {
      await until(() => item.server.completions === 1, "rejection was not reported");
      assert.equal(launches, 0);
      assert.equal(item.server.revalidations, 0);
      assert.equal(ws.sent.filter((entry) => entry.type === "remote_command_claim").length, 1);
    } finally {
      await controller.stop();
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.managed-jobs,code-run.remote.confinement
  it("recovers a tracked execution after reconnect without launching it twice", async () => {
    const item = await fixture();
    const process = new FakeProcess();
    let launches = 0;
    const controller = createRemoteCommandSourceController({
      client: {} as never, sourceSessionId: "session-1", bindings: [item.binding],
      toolchainPaths: [item.toolchain],
      runtime: { capability: supported, launchSandbox: () => { launches += 1; return process; } },
      responseTimeoutMs: 1_000,
    });
    const first = item.wire(new FakeWebSocket());
    const detach = controller.attach(first);
    try {
      await until(() => launches === 1 && item.server.lastSequence >= 1, "initial execution did not start");
      detach();
      item.server.state = "RUNNING";
      item.server.leaseExpiresAt = Math.floor(Date.now() / 1000) - 1;
      const second = item.wire(new FakeWebSocket());
      controller.attach(second);
      await until(() => item.server.recoveries === 1, "tracked execution lease was not recovered");
      assert.equal(launches, 1);
      assert.equal(second.sent.filter((entry) => entry.type === "remote_command_recover").length, 1);
      process.exit(0);
      await until(() => item.server.completions === 1, "recovered execution did not finish");
      assert.equal(launches, 1);
    } finally {
      await controller.stop();
      item.cleanup();
    }
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.managed-jobs
  it("does not recover or relaunch an untracked running execution", async () => {
    const item = await fixture();
    item.server.state = "RUNNING";
    item.server.leaseExpiresAt = Math.floor(Date.now() / 1000) - 1;
    const ws = item.wire(new FakeWebSocket());
    let launches = 0;
    const controller = createRemoteCommandSourceController({
      client: {} as never, sourceSessionId: "session-1", bindings: [item.binding],
      toolchainPaths: [item.toolchain],
      runtime: { capability: supported, launchSandbox: () => { launches += 1; return new FakeProcess(); } },
      responseTimeoutMs: 1_000,
    });
    controller.attach(ws);
    try {
      await until(() => ws.sent.some((entry) => entry.type === "remote_command_discover"), "discovery was not sent");
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
      assert.equal(launches, 0);
      assert.equal(item.server.claims, 0);
      assert.equal(item.server.recoveries, 0);
    } finally {
      await controller.stop();
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.managed-jobs
  it("delivers a stopped terminal event before explicit source shutdown detaches", async () => {
    const item = await fixture();
    const process = new FakeProcess();
    const ws = item.wire(new FakeWebSocket());
    let launches = 0;
    const controller = createRemoteCommandSourceController({
      client: {} as never, sourceSessionId: "session-1", bindings: [item.binding],
      toolchainPaths: [item.toolchain],
      runtime: { capability: supported, launchSandbox: () => { launches += 1; return process; } },
      responseTimeoutMs: 1_000,
    });
    controller.attach(ws);
    try {
      await until(() => launches === 1, "command did not launch");
      await controller.stop();
      assert.equal(process.terminated, true);
      assert.equal(item.server.completions, 1);
      const completion = ws.sent.find((entry) => entry.type === "remote_command_source_completion");
      assert.equal(completion?.payload.status, "stopped");
    } finally {
      await controller.stop();
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.managed-jobs,code-run.remote.resource-profiles
  it("marks retained output as an incomplete excerpt in plaintext and encrypted completion", async () => {
    const item = await fixture();
    const process = new FakeProcess();
    const ws = item.wire(new FakeWebSocket());
    let launches = 0;
    const controller = createRemoteCommandSourceController({
      client: {} as never, sourceSessionId: "session-1", bindings: [item.binding],
      toolchainPaths: [item.toolchain],
      runtime: {
        capability: supported,
        maxRetainedOutputBytes: 4,
        launchSandbox: () => { launches += 1; return process; },
      },
      responseTimeoutMs: 1_000,
    });
    controller.attach(ws);
    try {
      await until(() => launches === 1, "command did not launch");
      process.stdout.write("long output");
      process.exit(0);
      await until(() => item.server.completions === 1, "terminal completion was not delivered");
      const completion = ws.sent.find((entry) => entry.type === "remote_command_source_completion");
      assert.match(String(completion?.payload.model_text), /^\[OpenMates output excerpt is incomplete\]/);
      const plaintext = await decryptWithAesGcmCombined(String(completion?.payload.encrypted_event), item.projectKey);
      const decrypted = JSON.parse(plaintext ?? "null") as Record<string, unknown>;
      assert.deepEqual(decrypted.output_selection, {
        coverage: "selected_excerpt", upstream_truncated: true, source_excerpt_truncated: false,
      });
    } finally {
      await controller.stop();
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.managed-jobs,code-run.remote.explicit-approval
  it("honors a stop received before claim registration and never launches", async () => {
    const item = await fixture();
    const ws = item.wire(new FakeWebSocket());
    let launches = 0;
    const controller = createRemoteCommandSourceController({
      client: {} as never, sourceSessionId: "session-1", bindings: [item.binding],
      toolchainPaths: [item.toolchain],
      runtime: { capability: supported, launchSandbox: () => { launches += 1; return new FakeProcess(); } },
      responseTimeoutMs: 1_000,
    });
    controller.attach(ws);
    ws.emit("remote_command_stop_requested", item.summary());
    try {
      await until(() => item.server.completions === 1, "early stop was not completed");
      assert.equal(launches, 0);
      const completion = ws.sent.find((entry) => entry.type === "remote_command_source_completion");
      assert.equal(completion?.payload.status, "stopped");
    } finally {
      await controller.stop();
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.resource-profiles
  it("rejects a source root that would expose private OpenMates state", async () => {
    const item = await fixture();
    const previous = process.env.OPENMATES_STATE_DIR;
    process.env.OPENMATES_STATE_DIR = join(item.project, ".openmates-private");
    try {
      assert.throws(() => createRemoteCommandSourceController({
        client: {} as never, sourceSessionId: "session-1", bindings: [item.binding],
        toolchainPaths: [item.toolchain], runtime: { capability: supported },
      }), /cannot contain OpenMates private state/);
    } finally {
      if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previous;
      item.cleanup();
    }
  });
});
