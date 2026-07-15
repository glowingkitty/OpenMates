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

function version(channel, publishedVersions) {
  const args = [
    scriptPath,
    `--channel=${channel}`,
    "--dry-run",
    `--published-versions=${publishedVersions.join(",")}`,
  ];
  return execFileSync("node", args, { cwd: repoRoot, encoding: "utf8" }).trim();
}

describe("prepare_cli_publish_version", () => {
  it("starts dev prereleases at the configured base", () => {
    assert.equal(version("dev", ["0.14.9", "0.14.9-alpha.9"]), "0.15.0-alpha.0");
  });

  it("increments alpha indexes within the configured base", () => {
    assert.equal(version("dev", ["0.15.0-alpha.0", "0.15.0-alpha.3"]), "0.15.0-alpha.4");
  });

  it("keeps dev on the configured base after stable has shipped", () => {
    assert.equal(version("dev", ["0.15.0", "0.15.1", "0.15.1-alpha.3"]), "0.15.0-alpha.0");
  });

  it("publishes the configured stable base on main", () => {
    assert.equal(version("main", ["0.15.0-alpha.4", "0.15.1"]), "0.15.0");
  });

  it("ignores other release lines when finding alpha indexes", () => {
    assert.equal(version("dev", ["0.14.0-alpha.9", "0.15.1-alpha.7", "0.16.0-alpha.2"]), "0.15.0-alpha.0");
  });

  it("maps current npm state to the first fixed release-line alpha", () => {
    assert.equal(version("dev", ["0.14.8-alpha.0", "0.14.8"]), "0.15.0-alpha.0");
  });
});
