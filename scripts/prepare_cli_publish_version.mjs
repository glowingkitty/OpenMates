#!/usr/bin/env node
// Keeps npm CLI package versions aligned with the user-facing product version.
// Dev publishes use the configured prerelease base, e.g. 0.12.0-alpha.N.
// Stable publishes use the configured stable base as a release line. If the
// base already exists on npm, CI publishes the next patch in that line.

import { execFileSync } from "node:child_process";
import { readFileSync, appendFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const configPath = resolve(repoRoot, "shared/config/product_version.json");
const cliPackagePath = resolve(repoRoot, "frontend/packages/openmates-cli/package.json");
const cliPackageDir = dirname(cliPackagePath);
const signupSourcePath = resolve(repoRoot, "frontend/packages/ui/src/i18n/sources/signup/main.yml");

const args = new Map();
for (const arg of process.argv.slice(2)) {
  const [key, value = "true"] = arg.replace(/^--/, "").split("=", 2);
  args.set(key, value);
}

const channel = args.get("channel") || "check";
const dryRun = args.has("dry-run");
const config = JSON.parse(readFileSync(configPath, "utf8"));
const cliPackage = JSON.parse(readFileSync(cliPackagePath, "utf8"));

function fail(message) {
  console.error(message);
  process.exit(1);
}

function assertSemver(value, label) {
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(value)) {
    fail(`${label} must be a valid npm semver string, got ${value}`);
  }
}

function npmView(spec, fallback) {
  const override = args.get(spec === "openmates@alpha" ? "published-alpha" : "latest-stable");
  if (override !== undefined) {
    return override;
  }

  try {
    return execFileSync("npm", ["view", spec, "version"], { encoding: "utf8" }).trim();
  } catch {
    return fallback;
  }
}

function npmVersions(fallback) {
  const override = args.get("published-versions");
  if (override !== undefined) {
    return override.split(",").map((version) => version.trim()).filter(Boolean);
  }

  try {
    const output = execFileSync("npm", ["view", "openmates", "versions", "--json"], { encoding: "utf8" }).trim();
    const parsed = JSON.parse(output || "[]");
    return Array.isArray(parsed) ? parsed.filter((version) => typeof version === "string") : fallback;
  } catch {
    return fallback;
  }
}

function parseStableVersion(version) {
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) return null;
  return { major: Number(match[1]), minor: Number(match[2]), patch: Number(match[3]) };
}

function nextPrereleaseVersion(publishedAlpha) {
  const base = config.cli.prereleaseBase;
  const match = publishedAlpha.match(new RegExp(`^${base.replaceAll(".", "\\.")}\\.(\\d+)$`));
  if (!match) {
    return config.cli.prereleaseSeed;
  }
  return `${base}.${Number(match[1]) + 1}`;
}

function nextStableVersion(publishedVersions) {
  const base = parseStableVersion(config.cli.stableBase);
  if (!base) {
    fail(`cli.stableBase must be a stable npm semver string, got ${config.cli.stableBase}`);
  }

  const patches = publishedVersions
    .map(parseStableVersion)
    .filter((version) => version && version.major === base.major && version.minor === base.minor && version.patch >= base.patch)
    .map((version) => version.patch);

  if (!patches.length) return config.cli.stableBase;
  return `${base.major}.${base.minor}.${Math.max(...patches) + 1}`;
}

function setPackageVersion(version) {
  if (dryRun) {
    return;
  }

  execFileSync("npm", ["version", version, "--no-git-tag-version", "--allow-same-version"], {
    cwd: cliPackageDir,
    stdio: "inherit",
  });
}

function writeOutput(version) {
  console.log(version);
  if (process.env.GITHUB_OUTPUT) {
    appendFileSync(process.env.GITHUB_OUTPUT, `version=${version}\n`);
  }
}

assertSemver(config.cli.stableBase, "cli.stableBase");
assertSemver(config.cli.prereleaseSeed, "cli.prereleaseSeed");
if (!config.cli.prereleaseSeed.startsWith(`${config.cli.prereleaseBase}.`)) {
  fail("cli.prereleaseSeed must start with cli.prereleaseBase plus a numeric suffix");
}

if (channel === "check") {
  const signupSource = readFileSync(signupSourcePath, "utf8");
  if (!signupSource.includes(config.userFacing)) {
    fail(`signup version_title must include ${config.userFacing}`);
  }
  if (cliPackage.version !== config.cli.stableBase) {
    fail(`CLI package.json version must be ${config.cli.stableBase}, got ${cliPackage.version}`);
  }
  writeOutput(config.cli.stableBase);
} else if (channel === "dev") {
  const version = nextPrereleaseVersion(npmView("openmates@alpha", ""));
  setPackageVersion(version);
  writeOutput(version);
} else if (channel === "main") {
  const version = nextStableVersion(npmVersions([]));
  setPackageVersion(version);
  writeOutput(version);
} else {
  fail(`Unknown channel: ${channel}`);
}
