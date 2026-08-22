#!/usr/bin/env node
// contract-test-file: tooling
// Deterministic tests for npm CLI publish version arithmetic.
// Purpose: keep dev alpha and main stable versions aligned with product lines.
// Scope: exercises scripts/prepare_cli_publish_version.mjs without network calls.
// Architecture: package files stay at stableBase; CI rewrites publish versions.
// Security: only child-processes the local script with explicit version inputs.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const scriptPath = resolve(repoRoot, "scripts/prepare_cli_publish_version.mjs");
const productConfig = JSON.parse(readFileSync(resolve(repoRoot, "shared/config/product_version.json"), "utf8"));
const stableBase = productConfig.cli.stableBase;
const prereleaseLabel = productConfig.cli.prereleaseLabel || "alpha";
const [major, minor, patch] = stableBase.split(".").map((value) => Number.parseInt(value, 10));
const otherMinorBase = `${major}.${minor + 1}.${patch}`;
const otherPatchBase = `${major}.${minor}.${patch + 1}`;

function alpha(index, base = stableBase) {
  return `${base}-${prereleaseLabel}.${index}`;
}

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
    assert.equal(version("dev", [otherMinorBase, alpha(9, otherMinorBase)]), alpha(0));
  });

  it("increments alpha indexes within the configured base", () => {
    assert.equal(version("dev", [alpha(0), alpha(3)]), alpha(4));
  });

  it("keeps dev on the configured base after stable has shipped", () => {
    assert.equal(version("dev", [stableBase, otherPatchBase, alpha(3, otherPatchBase)]), alpha(0));
  });

  it("publishes the configured stable base on main", () => {
    assert.equal(version("main", [alpha(4), otherPatchBase]), stableBase);
  });

  it("ignores other release lines when finding alpha indexes", () => {
    assert.equal(version("dev", [alpha(9, otherMinorBase), alpha(7, otherPatchBase)]), alpha(0));
  });

  it("maps current npm state to the first fixed release-line alpha", () => {
    assert.equal(version("dev", [alpha(0, otherPatchBase), otherPatchBase]), alpha(0));
  });
});
