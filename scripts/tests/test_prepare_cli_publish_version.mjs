#!/usr/bin/env node
// Deterministic tests for npm CLI publish version arithmetic.
// Purpose: keep dev alpha and main stable versions aligned with product lines.
// Scope: exercises scripts/prepare_cli_publish_version.mjs without network calls.
// Architecture: package files stay at stableBase; CI rewrites publish versions.
// Security: only child-processes the local script with explicit version inputs.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { describe, it } from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const scriptPath = resolve(repoRoot, "scripts/prepare_cli_publish_version.mjs");

function version(channel, publishedVersions, options = {}) {
  const args = [
    scriptPath,
    `--channel=${channel}`,
    "--dry-run",
    `--published-versions=${publishedVersions.join(",")}`,
  ];
  if (options.stableFloor) args.push(`--stable-floor=${options.stableFloor}`);
  return execFileSync("node", args, { cwd: repoRoot, encoding: "utf8" }).trim();
}

describe("prepare_cli_publish_version", () => {
  it("starts dev prereleases at the configured base before any stable release exists", () => {
    assert.equal(version("dev", ["0.13.9", "0.13.9-alpha.9"], { stableFloor: "none" }), "0.14.0-alpha.0");
  });

  it("increments alpha indexes within the next stable patch", () => {
    assert.equal(version("dev", ["0.14.0", "0.14.1-alpha.0", "0.14.1-alpha.3"], { stableFloor: "none" }), "0.14.1-alpha.4");
  });

  it("moves dev to the next patch after the target stable has shipped", () => {
    assert.equal(version("dev", ["0.14.0", "0.14.1"], { stableFloor: "none" }), "0.14.2-alpha.0");
  });

  it("promotes the latest alpha patch on main", () => {
    assert.equal(version("main", ["0.14.0", "0.14.1-alpha.4"], { stableFloor: "none" }), "0.14.1");
  });

  it("patch bumps stable after the current target has shipped", () => {
    assert.equal(version("main", ["0.14.0", "0.14.1"], { stableFloor: "none" }), "0.14.2");
  });

  it("maps current npm state to the next release-line alpha", () => {
    assert.equal(version("dev", ["0.14.5-alpha.0", "0.14.5"]), "0.14.6-alpha.0");
  });

  it("uses the stable floor when a registry has not published the latest product patch", () => {
    assert.equal(version("dev", ["0.14.2", "0.14.3"], { stableFloor: "0.14.5" }), "0.14.6-alpha.0");
  });
});
