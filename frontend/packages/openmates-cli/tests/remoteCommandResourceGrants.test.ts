import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { parseRemoteCommandPermissions } from "../src/remoteCommandPermissions.ts";
import {
  enableRemoteCommandCredentialGrant,
  enableRemoteCommandNetworkGrant,
  enableRemoteCommandWritableGrant,
  resolveRemoteCommandResourceGrants,
} from "../src/remoteCommandResourceGrants.ts";

const source = `schema_version: 1
presets: []
resource_profiles:
  writable: [{id: cache, purpose: cache}]
  network: [{id: packages, destinations: [registry.example:443]}]
  credentials: [{id: staging, environment: [TEST_TOKEN]}]
`;

describe("remote command private resource grants", () => {
  // contract-test: direct surface=cli assertions=code-run.remote.resource-profiles,code-run.remote.confinement
  it("binds enabled local resources to Project, source, and exact reviewed definitions", () => {
    const base = mkdtempSync(join(tmpdir(), "openmates-command-resources-"));
    const state = join(base, "state");
    const projectRoot = join(base, "project");
    const projectCache = join(projectRoot, "cache");
    const cache = join(base, "cache");
    mkdirSync(projectRoot); mkdirSync(projectCache); mkdirSync(cache); mkdirSync(state);
    const previousState = process.env.OPENMATES_STATE_DIR;
    const previousToken = process.env.LOCAL_STAGING_TOKEN;
    process.env.OPENMATES_STATE_DIR = state;
    process.env.LOCAL_STAGING_TOKEN = "private-value";
    try {
      const permissions = parseRemoteCommandPermissions(source);
      const identity = { projectId: "project-1", sourceId: "source-1" };
      assert.throws(
        () => enableRemoteCommandWritableGrant({ ...identity, projectRoot, permissions, profileId: "cache", hostPath: projectCache }),
        /overlap the Project source/,
      );
      assert.throws(
        () => enableRemoteCommandWritableGrant({ ...identity, projectRoot, permissions, profileId: "cache", hostPath: state }),
        /overlap OpenMates private state/,
      );
      enableRemoteCommandWritableGrant({ ...identity, projectRoot, permissions, profileId: "cache", hostPath: cache });
      enableRemoteCommandNetworkGrant({ ...identity, permissions, profileId: "packages" });
      enableRemoteCommandCredentialGrant({ ...identity, permissions, profileId: "staging", environmentSources: { TEST_TOKEN: "LOCAL_STAGING_TOKEN" } });
      const binding = { source: { projectId: "project-1", sourceId: "source-1", rootPath: projectRoot } } as never;
      const policy = {
        argv: ["npm", "test"], cwd: ".", mode: "foreground", source_access: "read_only", deadline_ms: 1_000,
        writable_profiles: ["cache"], network_profile: "packages", credential_profiles: ["staging"],
      } as const;
      assert.deepEqual(resolveRemoteCommandResourceGrants({ binding, permissions, policy }), {
        writable_targets: [{ profile_id: "cache", host_path: cache }],
        network_profiles: [{ profile_id: "packages", destinations: ["registry.example:443"] }],
        credential_profiles: [{ profile_id: "staging", environment: { TEST_TOKEN: "private-value" } }],
      });

      const changed = parseRemoteCommandPermissions(source.replace("registry.example:443", "changed.example:443"));
      assert.deepEqual(resolveRemoteCommandResourceGrants({ binding, permissions: changed, policy }).network_profiles, []);

      const storePath = join(state, "remote-command-resource-grants.json");
      const stored = JSON.parse(readFileSync(storePath, "utf8")) as { grants: Array<Record<string, unknown>> };
      const writable = stored.grants.find((grant) => grant.kind === "writable");
      assert.ok(writable);
      writable.host_path = projectCache;
      writeFileSync(storePath, `${JSON.stringify(stored)}\n`, { mode: 0o600 });
      assert.deepEqual(resolveRemoteCommandResourceGrants({ binding, permissions, policy }).writable_targets, []);
    } finally {
      if (previousState === undefined) delete process.env.OPENMATES_STATE_DIR; else process.env.OPENMATES_STATE_DIR = previousState;
      if (previousToken === undefined) delete process.env.LOCAL_STAGING_TOKEN; else process.env.LOCAL_STAGING_TOKEN = previousToken;
      rmSync(base, { recursive: true, force: true });
    }
  });
});
