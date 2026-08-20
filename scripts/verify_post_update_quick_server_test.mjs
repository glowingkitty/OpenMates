#!/usr/bin/env node
/**
 * Real authenticated CLI proof for post-update quick server tests.
 *
 * The script delegates every product action to the compiled OpenMates CLI,
 * requires explicit credit consent, and validates only sanitized check output.
 * It never reads, prints, or persists session credentials or chat content.
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";

const root = resolve(import.meta.dirname, "..");
const cli = resolve(root, "frontend/packages/openmates-cli/dist/cli.js");
const args = process.argv.slice(2);
const apiIndex = args.indexOf("--api-url");
const apiUrl = apiIndex >= 0 ? args[apiIndex + 1] : "https://api.dev.openmates.org";

if (apiIndex >= 0 && (!apiUrl || apiUrl.startsWith("--"))) {
  throw new Error("Usage: --api-url <https://api.example.org>.");
}
if (!args.includes("--confirm-spend-credits")) {
  throw new Error("Live quick-server proof requires --confirm-spend-credits.");
}
if (!existsSync(cli)) {
  throw new Error("Compiled CLI not found. Run npm --prefix frontend/packages/openmates-cli run build first.");
}

const build = spawnSync(
  "npm",
  ["--prefix", "frontend/packages/openmates-cli", "run", "build"],
  { cwd: root, encoding: "utf-8", timeout: 180_000 },
);
if (build.status !== 0) throw new Error("Current-source CLI build failed before quick server proof.");

const result = spawnSync(
  process.execPath,
  [cli, "--api-url", apiUrl, "server", "test", "--quick", "--confirm-spend-credits", "--json"],
  { cwd: root, encoding: "utf-8", timeout: 240_000 },
);
if (result.status !== 0) {
  throw new Error(`Quick server CLI proof failed with exit ${result.status ?? "unknown"}.`);
}

const output = JSON.parse(result.stdout);
const quickTest = output.quickTest;
const expectedIds = [
  "account.session",
  "chat.create",
  "chat.reload",
  "app.math.calculate",
  "app.web.search",
  "chat.cleanup",
];
if (quickTest?.status !== "passed") throw new Error("Quick server CLI proof did not pass.");
if (!Array.isArray(quickTest.checks)) throw new Error("Quick server CLI proof returned no checks.");
for (const id of expectedIds) {
  const check = quickTest.checks.find((item) => item?.id === id);
  if (check?.status !== "passed") throw new Error(`Quick server CLI proof check failed: ${id}`);
}

process.stdout.write(`${JSON.stringify({ status: "passed", checks: expectedIds }, null, 2)}\n`);
