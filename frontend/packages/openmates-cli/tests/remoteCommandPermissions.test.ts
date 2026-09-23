import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  loadRemoteCommandPermissions,
  matchEnabledRemoteCommandPreset,
  parseRemoteCommandPermissions,
  remoteCommandPresetDigest,
  RemoteCommandPermissionsError,
} from "../src/remoteCommandPermissions.ts";

const YAML = `
schema_version: 1
file_access:
  private_paths: [.secrets/**, /config/private.json]
resource_profiles:
  writable:
    - id: test-cache
      purpose: cache
  network:
    - id: packages
      destinations: [registry.npmjs.org:443]
  credentials:
    - id: staging
      environment: [TEST_API_TOKEN]
presets:
  - id: checks
    label: Checks
    commands:
      - argv: [npm, test]
        cwd: .
        mode: foreground
        source_access: read_only
        deadline_ms: 60000
        writable_profiles: [test-cache]
        network_profile: null
        credential_profiles: []
`;

describe("remote command permission definitions", () => {
  // contract-test: supporting surface=cli assertions=code-run.remote.command-lists,code-run.remote.explicit-approval
  it("requires a trusted active grant bound to the exact repository definition", () => {
    const config = parseRemoteCommandPermissions(YAML);
    assert.deepEqual(config.file_access.private_paths, [".secrets/**", "/config/private.json"]);
    const policy = config.presets[0]?.commands[0];
    assert.ok(policy);
    const digest = remoteCommandPresetDigest(config, "checks");
    assert.equal(matchEnabledRemoteCommandPreset({ config, projectId: "project-1", policy, activeGrants: [] }), null);
    assert.deepEqual(matchEnabledRemoteCommandPreset({
      config,
      projectId: "project-1",
      policy,
      activeGrants: [{ project_id: "project-1", preset_id: "checks", definition_digest: digest, enabled: true }],
    }), { presetId: "checks", definitionDigest: digest });

    const changed = parseRemoteCommandPermissions(YAML.replace("[npm, test]", "[npm, test, --, changed]"));
    assert.equal(matchEnabledRemoteCommandPreset({
      config: changed,
      projectId: "project-1",
      policy: changed.presets[0]!.commands[0]!,
      activeGrants: [{ project_id: "project-1", preset_id: "checks", definition_digest: digest, enabled: true }],
    }), null);
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.command-lists,code-run.remote.resource-profiles
  it("rejects broad shapes, unknown resources, unsafe cwd, and background source writes", () => {
    assert.throws(() => parseRemoteCommandPermissions(YAML.replace("label: Checks", "label: Checks\n    active: true")), RemoteCommandPermissionsError);
    assert.throws(() => parseRemoteCommandPermissions(YAML.replace("[test-cache]", "[missing]")), /Unknown writable profile/);
    assert.throws(() => parseRemoteCommandPermissions(YAML.replace("cwd: .", "cwd: ../outside")), /Project-relative/);
    assert.throws(() => parseRemoteCommandPermissions(YAML.replace("mode: foreground", "mode: background").replace("source_access: read_only", "source_access: read_write")), /background commands/);
    assert.throws(() => parseRemoteCommandPermissions(YAML.replace("registry.npmjs.org:443", "https://registry.npmjs.org")), /exact hostname/);
    assert.throws(() => parseRemoteCommandPermissions(YAML.replace(".secrets/**", "'!public.txt'")), /additive/);
    assert.throws(() => parseRemoteCommandPermissions(YAML.replace(".secrets/**", "../outside")), /parent path/);
  });

  // contract-test: direct surface=cli assertions=code-run.remote.private-path-deny
  it("keeps file_access optional for existing repositories and normalizes private path globs", () => {
    const legacy = parseRemoteCommandPermissions(YAML.replace(/file_access:\n {2}private_paths: \[[^\n]+\]\n/, ""));
    assert.deepEqual(legacy.file_access.private_paths, []);
    const normalized = parseRemoteCommandPermissions(YAML.replace(".secrets/**", "./.secrets/**"));
    assert.deepEqual(normalized.file_access.private_paths, [".secrets/**", "/config/private.json"]);
  });

  // contract-test: supporting surface=cli assertions=code-run.remote.command-lists
  it("loads only a bounded regular .openmates/permissions.yml file", () => {
    const base = mkdtempSync(join(tmpdir(), "openmates-command-permissions-"));
    const root = join(base, "project");
    const external = join(base, "outside.yml");
    try {
      mkdirSync(join(root, ".openmates"), { recursive: true });
      writeFileSync(join(root, ".openmates", "permissions.yml"), YAML);
      assert.equal(loadRemoteCommandPermissions(root)?.presets[0]?.id, "checks");
      writeFileSync(external, YAML);
      rmSync(join(root, ".openmates", "permissions.yml"));
      symlinkSync(external, join(root, ".openmates", "permissions.yml"));
      assert.throws(() => loadRemoteCommandPermissions(root), /regular file/);
    } finally {
      rmSync(base, { recursive: true, force: true });
    }
  });
});
