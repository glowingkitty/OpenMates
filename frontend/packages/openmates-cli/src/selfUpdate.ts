/*
 * OpenMates CLI self-update helper.
 *
 * Purpose: update the globally installed openmates npm package from the CLI.
 * Architecture: no network logic here; delegates to the user's package manager.
 * Safety: tests use --dry-run so they never mutate the local installation.
 * Tests: frontend/packages/openmates-cli/tests/cli.test.ts
 */

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

export type SelfUpdatePlan = {
  packageManager: SupportedPackageManager;
  command: string;
  args: string[];
  packageSpec: string;
  currentVersion: string;
  dryRun: boolean;
};

type SupportedPackageManager = "npm" | "pnpm" | "yarn" | "bun";

const PACKAGE_NAME = "openmates";
const DEFAULT_TARGET = "latest";
const SAFE_TARGET_RE = /^[a-zA-Z0-9._@+~:-]+$/;

export function getCliPackageVersion(): string {
  try {
    const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf-8")) as { version?: string };
    return packageJson.version ?? "unknown";
  } catch {
    return "unknown";
  }
}

export function buildSelfUpdatePlan(flags: Record<string, string | boolean>): SelfUpdatePlan {
  const packageManager = parsePackageManager(flags["package-manager"]);
  const target = parseTarget(flags.version);
  const packageSpec = `${PACKAGE_NAME}@${target}`;
  const { command, args } = commandForPackageManager(packageManager, packageSpec);
  return {
    packageManager,
    command,
    args,
    packageSpec,
    currentVersion: getCliPackageVersion(),
    dryRun: flags["dry-run"] === true,
  };
}

export function runSelfUpdate(plan: SelfUpdatePlan): void {
  if (plan.dryRun) return;
  const result = spawnSync(plan.command, plan.args, {
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.stdout) process.stderr.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error) {
    throw new Error(`Unable to run ${plan.command}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`${plan.command} ${plan.args.join(" ")} failed with exit code ${result.status ?? "unknown"}`);
  }
}

function parsePackageManager(value: string | boolean | undefined): SupportedPackageManager {
  if (value === undefined) return detectPackageManager();
  if (value === "npm" || value === "pnpm" || value === "yarn" || value === "bun") return value;
  throw new Error("--package-manager must be one of npm, pnpm, yarn, or bun");
}

function parseTarget(value: string | boolean | undefined): string {
  if (value === undefined) return DEFAULT_TARGET;
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("--version requires a version or npm dist-tag");
  }
  if (!SAFE_TARGET_RE.test(value)) {
    throw new Error("--version contains unsupported characters");
  }
  return value;
}

function detectPackageManager(): SupportedPackageManager {
  const userAgent = process.env.npm_config_user_agent ?? "";
  if (userAgent.startsWith("pnpm/")) return "pnpm";
  if (userAgent.startsWith("yarn/")) return "yarn";
  if (userAgent.startsWith("bun/")) return "bun";
  return "npm";
}

function commandForPackageManager(
  packageManager: SupportedPackageManager,
  packageSpec: string,
): { command: string; args: string[] } {
  if (packageManager === "pnpm") return { command: commandName("pnpm"), args: ["add", "-g", packageSpec] };
  if (packageManager === "yarn") return { command: commandName("yarn"), args: ["global", "add", packageSpec] };
  if (packageManager === "bun") return { command: commandName("bun"), args: ["install", "-g", packageSpec] };
  return { command: commandName("npm"), args: ["install", "-g", packageSpec] };
}

function commandName(name: SupportedPackageManager): string {
  return process.platform === "win32" ? `${name}.cmd` : name;
}
