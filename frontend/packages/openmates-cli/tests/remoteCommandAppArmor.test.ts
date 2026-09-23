import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  canonicalRemoteCommandAppArmorPolicy,
  prepareRemoteCommandAppArmorConfinement,
  type RemoteCommandAppArmorBrokerRequest,
  type RemoteCommandAppArmorPolicyInput,
} from "../src/remoteCommandAppArmor.ts";

function fixture(): {
  base: string;
  input: RemoteCommandAppArmorPolicyInput;
  toolchain: string;
  aaExec: string;
  gitConfigMask: string;
  cleanup(): void;
} {
  const base = mkdtempSync(join(tmpdir(), "openmates-apparmor-adapter-"));
  const project = join(base, "project");
  const toolchain = join(base, "toolchain");
  const aaExec = join(toolchain, "bin", "aa-exec");
  const gitConfigMask = join(toolchain, "libexec", "openmates-git-config-mask.so");
  mkdirSync(project);
  mkdirSync(join(toolchain, "bin"), { recursive: true });
  mkdirSync(join(toolchain, "libexec"), { recursive: true });
  writeFileSync(aaExec, "#!/bin/sh\nexit 1\n");
  chmodSync(aaExec, 0o755);
  writeFileSync(gitConfigMask, "test shim\n");
  chmodSync(gitConfigMask, 0o755);
  return {
    base,
    toolchain,
    aaExec,
    gitConfigMask,
    input: {
      execution_id: "execution-1",
      source_root: project,
      private_policy_digest: "b".repeat(64),
      private_globs: ["**/.env", "private/**"],
      exact_private_aliases: [{ path: "private-link", kind: "file" }],
      exact_readonly_paths: [{ path: "AGENTS.md", kind: "file" }],
    },
    cleanup: () => rmSync(base, { recursive: true, force: true }),
  };
}

describe("remote command AppArmor adapter", () => {
  // contract-test: direct surface=cli assertions=code-run.remote.private-path-deny,code-run.remote.confinement
  it("sends only canonical semantic policy and retains the immutable broker profile on release", async () => {
    const item = fixture();
    const requests: RemoteCommandAppArmorBrokerRequest[] = [];
    const digest = "c".repeat(64);
    const uid = process.getuid?.();
    assert.ok(uid && uid > 0);
    try {
      const confinement = await prepareRemoteCommandAppArmorConfinement(item.input, [item.toolchain], {
        aaExecPath: item.aaExec,
        gitConfigMaskPath: item.gitConfigMask,
        runBroker: async (request) => {
          requests.push(request);
          if (request.action === "prepare") {
            return {
              profile_name: `openmates-command.${uid}.${digest}`,
              lease_id: "1".repeat(32),
              definition_digest: digest,
              private_policy_digest: item.input.private_policy_digest,
            };
          }
          return { released: false, retained: true, definition_digest: digest };
        },
      });

      assert.deepEqual(confinement.sandbox_command, {
        executable: item.aaExec,
        args: ["--profile", `openmates-command.${uid}.${digest}`],
      });
      assert.deepEqual(confinement.sandbox_environment, { LD_PRELOAD: item.gitConfigMask });
      assert.equal(requests[0]?.action, "prepare");
      assert.equal("definition_digest" in (requests[0] as Record<string, unknown>), false);
      assert.deepEqual((requests[0] as Extract<RemoteCommandAppArmorBrokerRequest, { action: "prepare" }>).private_globs, ["**/.env", "private/**"]);
      await confinement.dispose();
      await confinement.dispose();
      assert.equal(requests.length, 2);
      assert.deepEqual(requests[1], {
        protocol_version: 1,
        action: "release",
        lease_id: "1".repeat(32),
        definition_digest: digest,
      });
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.private-path-deny,code-run.remote.confinement
  it("sorts policy inputs and rejects paths the broker cannot represent safely", () => {
    const item = fixture();
    try {
      const canonical = canonicalRemoteCommandAppArmorPolicy({
        ...item.input,
        private_globs: ["z/**", "a?.txt"],
        exact_private_aliases: [{ path: "z", kind: "file" }, { path: "a", kind: "directory" }],
      });
      assert.deepEqual(canonical.private_globs, ["a?.txt", "z/**"]);
      assert.deepEqual(canonical.exact_private_aliases.map((entry) => entry.path), ["a", "z"]);
      assert.throws(() => canonicalRemoteCommandAppArmorPolicy({ ...item.input, private_globs: ["safe//secret"] }), /Invalid AppArmor private glob/);
      assert.throws(() => canonicalRemoteCommandAppArmorPolicy({ ...item.input, exact_private_aliases: [{ path: "../secret", kind: "file" }] }), /Invalid AppArmor private alias path/);
      assert.throws(() => canonicalRemoteCommandAppArmorPolicy({ ...item.input, private_globs: ["dup", "dup"] }), /Duplicate AppArmor private glob/);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: direct surface=cli assertions=code-run.remote.private-path-deny,code-run.remote.confinement
  it("rejects a broker response outside the caller UID and requested private policy", async () => {
    const item = fixture();
    try {
      await assert.rejects(
        prepareRemoteCommandAppArmorConfinement(item.input, [item.toolchain], {
          aaExecPath: item.aaExec,
          gitConfigMaskPath: item.gitConfigMask,
          runBroker: async () => ({
            profile_name: `openmates-command.0.${"d".repeat(64)}`,
            lease_id: "2".repeat(32),
            definition_digest: "d".repeat(64),
            private_policy_digest: "e".repeat(64),
          }),
        }),
        /different command policy/,
      );
    } finally {
      item.cleanup();
    }
  });
});
