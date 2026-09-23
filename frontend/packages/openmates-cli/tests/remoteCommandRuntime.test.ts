import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import { describe, it } from "node:test";

import {
  createRemoteCommandPreflight,
  RemoteCommandError,
  RemoteCommandRuntime,
  sanitizeRemoteCommandOutput,
  type RemoteCommandAuthority,
  type RemoteCommandRequest,
  type RemoteCommandSandboxLaunch,
  type RemoteCommandSandboxProcess,
} from "../src/remoteCommandRuntime.ts";
import { parseRemoteCommandPermissions, remoteCommandPresetDigest } from "../src/remoteCommandPermissions.ts";

class FakeProcess implements RemoteCommandSandboxProcess {
  readonly stdout = new PassThrough();
  readonly stderr = new PassThrough();
  readonly #events = new EventEmitter();
  terminated = false;
  result: { code: number | null; signal: NodeJS.Signals | null } | null = null;

  wait(): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
    if (this.result) return Promise.resolve(this.result);
    return new Promise((resolvePromise) => this.#events.once("exit", resolvePromise));
  }

  async terminate(): Promise<void> {
    this.terminated = true;
    this.exit(null, "SIGTERM");
  }

  exit(code: number | null, signal: NodeJS.Signals | null = null): void {
    this.result = { code, signal };
    this.stdout.end();
    this.stderr.end();
    this.#events.emit("exit", { code, signal });
  }
}

function fixture(options: { mode?: "foreground" | "background"; sourceAccess?: "read_only" | "read_write"; deadline?: number; protectedFiles?: boolean } = {}) {
  const base = mkdtempSync(join(tmpdir(), "openmates-command-runtime-"));
  const root = join(base, "project");
  const toolchain = join(base, "toolchain");
  const cache = join(base, "cache");
  mkdirSync(root);
  mkdirSync(toolchain);
  mkdirSync(cache);
  if (options.protectedFiles) {
    writeFileSync(join(root, ".env"), "SECRET=value\n");
    writeFileSync(join(root, "private.key"), "private\n");
    symlinkSync(".env", join(root, "env-alias"));
  }
  const request: RemoteCommandRequest = {
    execution_id: "execution-1",
    project_id: "project-1",
    source_root: root,
    policy: {
      argv: ["tool", "check"],
      cwd: ".",
      mode: options.mode ?? "foreground",
      source_access: options.sourceAccess ?? "read_only",
      deadline_ms: options.deadline ?? 5_000,
      writable_profiles: ["cache"],
      network_profile: null,
      credential_profiles: [],
    },
    toolchain_paths: [toolchain],
    writable_targets: [{ profile_id: "cache", purpose: "cache", host_path: cache }],
    network: null,
    credentials: [],
  };
  const preflight = createRemoteCommandPreflight(request);
  const authority: RemoteCommandAuthority = {
    authorized: true,
    project_id: request.project_id,
    source_root: root,
    request_digest: preflight.request_digest,
    toolchain_paths: [toolchain],
    writable_targets: [{ profile_id: "cache", host_path: cache }],
    network_profiles: [],
    credential_profiles: [],
  };
  return { base, request, preflight, authority, cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

const supported = () => ({ supported: true, platform: "linux" as const, mechanism: "bubblewrap" as const, executable: "/usr/bin/bwrap" });

describe("remote command runtime", () => {
  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.explicit-approval,code-run.remote.resource-profiles
  it("binds an immutable one-run approval, rechecks authority, and builds a confined minimal launch", async () => {
    const item = fixture();
    const process = new FakeProcess();
    let launch: RemoteCommandSandboxLaunch | undefined;
    let rechecks = 0;
    process.exit(0);
    const runtime = new RemoteCommandRuntime({
      capability: supported,
      approve: async (preflight) => ({ kind: "one_run", execution_id: preflight.execution_id, request_digest: preflight.request_digest }),
      revalidateAuthority: async () => { rechecks += 1; return item.authority; },
      launchSandbox: (value) => { launch = value; return process; },
    });
    try {
      const started = await runtime.start(item.request);
      assert.equal(started.status, "running");
      const completed = await runtime.wait("execution-1");
      assert.equal(completed.status, "succeeded");
      assert.equal(rechecks, 2);
      assert.ok(launch?.args.includes("--unshare-all"));
      assert.ok(launch?.args.includes("--ro-bind"));
      assert.ok(launch?.args.includes("/project"));
      assert.deepEqual(Object.keys(launch?.environment ?? {}).sort(), ["HOME", "LANG", "LC_ALL", "NO_COLOR", "OPENMATES_WRITABLE_CACHE", "PATH", "TMPDIR"]);
      assert.equal(launch?.environment.HOST_SECRET, undefined);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.resource-profiles
  it("masks known Project credentials and aliases inside the sandbox mount", async () => {
    const item = fixture({ protectedFiles: true });
    const process = new FakeProcess();
    process.exit(0);
    let launch: RemoteCommandSandboxLaunch | undefined;
    const runtime = new RemoteCommandRuntime({
      capability: supported,
      approve: async (preflight) => ({ kind: "one_run", execution_id: preflight.execution_id, request_digest: preflight.request_digest }),
      revalidateAuthority: async () => item.authority,
      launchSandbox: (value) => { launch = value; return process; },
    });
    try {
      assert.deepEqual(item.preflight.masked_project_paths.map((entry) => entry.path), [".env", "env-alias", "private.key"]);
      await runtime.start(item.request);
      await runtime.wait("execution-1");
      assert.ok(launch?.args.includes("/project/.env"));
      assert.ok(launch?.args.includes("/project/env-alias"));
      assert.ok(launch?.args.includes("/project/private.key"));
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.resource-profiles
  it("rejects source write aliases and mounts that expose private CLI state", () => {
    const item = fixture();
    const previousStateDir = process.env.OPENMATES_STATE_DIR;
    try {
      const nestedWritable = join(item.request.source_root, "generated");
      mkdirSync(nestedWritable);
      assert.throws(
        () => createRemoteCommandPreflight({
          ...item.request,
          writable_targets: [{ profile_id: "cache", purpose: "cache", host_path: nestedWritable }],
        }),
        (error) => error instanceof RemoteCommandError && error.code === "invalid_request",
      );

      const trustedContainer = join(item.base, "trusted");
      const privateState = join(trustedContainer, "private-state");
      mkdirSync(trustedContainer);
      mkdirSync(privateState);
      process.env.OPENMATES_STATE_DIR = privateState;

      assert.throws(
        () => createRemoteCommandPreflight({
          ...item.request,
          writable_targets: [{ profile_id: "cache", purpose: "cache", host_path: privateState }],
        }),
        (error) => error instanceof RemoteCommandError && error.code === "resource_not_granted",
      );
      assert.throws(
        () => createRemoteCommandPreflight({ ...item.request, toolchain_paths: [trustedContainer] }),
        (error) => error instanceof RemoteCommandError && error.code === "resource_not_granted",
      );

      process.env.OPENMATES_STATE_DIR = join(item.request.source_root, ".openmates-private");
      assert.throws(
        () => createRemoteCommandPreflight(item.request),
        (error) => error instanceof RemoteCommandError && error.code === "confinement_unavailable",
      );
    } finally {
      if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previousStateDir;
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.explicit-approval
  it("fails closed for a mismatched approval or revoked focus", async () => {
    const item = fixture();
    try {
      const mismatch = new RemoteCommandRuntime({
        capability: supported,
        approve: async (preflight) => ({ kind: "one_run", execution_id: preflight.execution_id, request_digest: "wrong" }),
        revalidateAuthority: async () => item.authority,
      });
      await assert.rejects(mismatch.start(item.request), (error) => error instanceof RemoteCommandError && error.code === "invalid_approval");

      const revoked = new RemoteCommandRuntime({
        capability: supported,
        approve: async (preflight) => ({ kind: "one_run", execution_id: preflight.execution_id, request_digest: preflight.request_digest }),
        revalidateAuthority: async () => ({ ...item.authority, authorized: false }),
      });
      await assert.rejects(revoked.start(item.request), (error) => error instanceof RemoteCommandError && error.code === "authority_revoked");
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.command-lists,code-run.remote.explicit-approval
  it("rechecks a preset definition and protected activation immediately before launch", async () => {
    const item = fixture();
    const yaml = (label: string) => `
schema_version: 1
resource_profiles:
  writable: [{id: cache, purpose: cache}]
  network: []
  credentials: []
presets:
  - id: checks
    label: ${label}
    commands:
      - argv: [tool, check]
        cwd: .
        mode: foreground
        source_access: read_only
        deadline_ms: 5000
        writable_profiles: [cache]
        network_profile: null
        credential_profiles: []
`;
    const approved = parseRemoteCommandPermissions(yaml("Checks"));
    const changed = parseRemoteCommandPermissions(yaml("Changed checks"));
    const digest = remoteCommandPresetDigest(approved, "checks");
    let loads = 0;
    const runtime = new RemoteCommandRuntime({
      capability: supported,
      approve: async (preflight) => ({ kind: "preset", preset_id: "checks", definition_digest: digest, request_digest: preflight.request_digest }),
      revalidateAuthority: async () => item.authority,
      resolvePresetState: async () => {
        loads += 1;
        const config = loads === 1 ? approved : changed;
        return {
          config,
          activeGrants: [{ project_id: "project-1", preset_id: "checks", definition_digest: digest, enabled: true }],
        };
      },
    });
    try {
      await assert.rejects(runtime.start(item.request), (error) => error instanceof RemoteCommandError && error.code === "invalid_approval");
      assert.equal(loads, 2);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.resource-profiles
  it("reports exact confinement and network capability gaps without unrestricted fallback", async () => {
    const item = fixture();
    try {
      const unavailable = new RemoteCommandRuntime({
        capability: () => ({ supported: false, platform: "linux", mechanism: null, reason: "user namespaces disabled" }),
        approve: async () => null,
        revalidateAuthority: async () => item.authority,
      });
      await assert.rejects(unavailable.start(item.request), (error) => error instanceof RemoteCommandError && error.code === "confinement_unavailable" && /user namespaces/.test(error.message));

      const networkRequest = {
        ...item.request,
        execution_id: "network-1",
        policy: { ...item.request.policy, network_profile: "packages" },
        network: { profile_id: "packages", destinations: ["registry.npmjs.org:443"] },
      };
      const networkPreflight = createRemoteCommandPreflight(networkRequest);
      const networkAuthority = {
        ...item.authority,
        request_digest: networkPreflight.request_digest,
        network_profiles: [{ profile_id: "packages", destinations: ["registry.npmjs.org:443"] }],
      };
      const runtime = new RemoteCommandRuntime({
        capability: supported,
        approve: async (preflight) => ({ kind: "one_run", execution_id: preflight.execution_id, request_digest: preflight.request_digest }),
        revalidateAuthority: async () => networkAuthority,
      });
      await assert.rejects(runtime.start(networkRequest), (error) => error instanceof RemoteCommandError && error.code === "network_profile_unavailable" && /registry\.npmjs\.org/.test(error.message));
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.managed-jobs
  it("tracks bounded inert output and stops the owned job", async () => {
    const item = fixture();
    const process = new FakeProcess();
    const events: string[] = [];
    const runtime = new RemoteCommandRuntime({
      capability: supported,
      maxRetainedOutputBytes: 12,
      approve: async (preflight) => ({ kind: "one_run", execution_id: preflight.execution_id, request_digest: preflight.request_digest }),
      revalidateAuthority: async () => item.authority,
      launchSandbox: () => process,
    });
    runtime.subscribe((event) => {
      if (event.type === "output") events.push(event.text);
    });
    try {
      await runtime.start(item.request);
      process.stdout.write("\u001b[31mhello\u001b[0m\u202eworld-more");
      await runtime.stop("execution-1");
      const completed = await runtime.wait("execution-1");
      assert.equal(completed.status, "stopped");
      assert.equal(completed.output_truncated, true);
      assert.equal(events.join(""), "helloworld-m");
      assert.equal(process.terminated, true);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.resource-profiles,code-run.remote.managed-jobs
  it("redacts selected credential values across output chunk boundaries", async () => {
    const item = fixture();
    const secret = "top-secret-123";
    const request = {
      ...item.request,
      execution_id: "credential-1",
      policy: { ...item.request.policy, credential_profiles: ["staging"] },
      credentials: [{ profile_id: "staging", environment: ["TEST_API_TOKEN"] }],
    };
    const preflight = createRemoteCommandPreflight(request);
    const authority = {
      ...item.authority,
      request_digest: preflight.request_digest,
      credential_profiles: [{ profile_id: "staging", environment: { TEST_API_TOKEN: secret } }],
    };
    const process = new FakeProcess();
    const output: string[] = [];
    const runtime = new RemoteCommandRuntime({
      capability: supported,
      approve: async (value) => ({ kind: "one_run", execution_id: value.execution_id, request_digest: value.request_digest }),
      revalidateAuthority: async () => authority,
      launchSandbox: () => process,
    });
    runtime.subscribe((event) => { if (event.type === "output") output.push(event.text); });
    try {
      await runtime.start(request);
      process.stdout.write("prefix top-");
      process.stdout.write("secret-123 suffix");
      process.exit(0);
      await runtime.wait("credential-1");
      await new Promise((resolvePromise) => setImmediate(resolvePromise));
      assert.equal(output.join(""), "prefix [REDACTED_CREDENTIAL] suffix");
      assert.equal(output.join("").includes(secret), false);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.explicit-approval,code-run.remote.managed-jobs
  it("cancels an authorizing job without launching after approval completes", async () => {
    const item = fixture();
    let resolveApproval!: (approval: { kind: "one_run"; execution_id: string; request_digest: string }) => void;
    const approval = new Promise<{ kind: "one_run"; execution_id: string; request_digest: string }>((resolvePromise) => { resolveApproval = resolvePromise; });
    let launched = false;
    const runtime = new RemoteCommandRuntime({
      capability: supported,
      approve: async () => approval,
      revalidateAuthority: async () => item.authority,
      launchSandbox: () => { launched = true; return new FakeProcess(); },
    });
    try {
      const starting = runtime.start(item.request);
      await new Promise((resolvePromise) => setImmediate(resolvePromise));
      const stopped = await runtime.stop("execution-1");
      assert.equal(stopped.status, "stopped");
      resolveApproval({ kind: "one_run", execution_id: item.preflight.execution_id, request_digest: item.preflight.request_digest });
      assert.equal((await starting).status, "stopped");
      assert.equal(launched, false);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.managed-jobs
  it("wraps source-writing foreground commands in the exclusive project lock", async () => {
    const item = fixture({ sourceAccess: "read_write" });
    const process = new FakeProcess();
    process.exit(0);
    let launch: RemoteCommandSandboxLaunch | undefined;
    const runtime = new RemoteCommandRuntime({
      capability: supported,
      approve: async (preflight) => ({ kind: "one_run", execution_id: preflight.execution_id, request_digest: preflight.request_digest }),
      revalidateAuthority: async () => item.authority,
      launchSandbox: (value) => { launch = value; return process; },
    });
    try {
      await runtime.start(item.request);
      await runtime.wait("execution-1");
      assert.equal(launch?.executable, "/usr/bin/setpriv");
      assert.ok(launch?.args.includes("--exclusive"));
      assert.ok(launch?.args.includes("--preserve-fds"));
    } finally {
      item.cleanup();
    }
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.managed-jobs
  it("removes terminal controls and bidi overrides from output", () => {
    assert.equal(sanitizeRemoteCommandOutput("ok\u001b]0;title\u0007\u001b[2J\u202ebad\u0000\n"), "okbad\n");
  });
});
