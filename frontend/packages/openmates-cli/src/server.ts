/*
 * OpenMates CLI server management commands.
 *
 * Purpose: install, start, stop, restart, update, reset, and monitor a
 *          self-hosted OpenMates instance via Docker Compose.
 * Architecture: shells out to git/docker — no OpenMatesClient or login required.
 * Architecture doc: docs/planned/cli-remote-access.md
 * Tests: frontend/packages/openmates-cli/tests/server.test.ts
 */

import { execSync, spawn as nodeSpawn } from "node:child_process";
import { copyFileSync, existsSync, readFileSync, rmSync } from "node:fs";
import { createInterface } from "node:readline";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

import {
  type ServerConfig,
  loadServerConfig,
  removeServerConfig,
  resolveServerPath,
  saveServerConfig,
} from "./serverConfig.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COMPOSE_FILE = join("backend", "core", "docker-compose.yml");
const COMPOSE_OVERRIDE = join("backend", "core", "docker-compose.override.yml");
const DEFAULT_INSTALL_PATH = join(homedir(), "openmates");
const REPO_URL = "https://github.com/glowingkitty/OpenMates.git";

// ---------------------------------------------------------------------------
// Shell helpers
// ---------------------------------------------------------------------------

/** Run a command synchronously, returning stdout. Throws on non-zero exit. */
function exec(cmd: string, cwd: string): string {
  return execSync(cmd, { cwd, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] }).trim();
}

/** Run a command with inherited stdio so the user sees output live. Returns the exit code. */
function runInteractive(cmd: string, args: string[], cwd: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = nodeSpawn(cmd, args, { cwd, stdio: "inherit", shell: false });
    child.on("close", (code) => resolve(code ?? 1));
    child.on("error", reject);
  });
}

/** Build the docker compose argument array. */
export function composeArgs(installPath: string, withOverrides: boolean): string[] {
  const args = ["compose", "--env-file", ".env", "-f", COMPOSE_FILE];
  if (withOverrides && existsSync(join(installPath, COMPOSE_OVERRIDE))) {
    args.push("-f", COMPOSE_OVERRIDE);
  }
  return args;
}

/** Check that docker is installed and the daemon is running. */
function requireDocker(): void {
  try {
    execSync("docker version", { stdio: "pipe" });
  } catch {
    throw new Error(
      "Docker is not installed or the Docker daemon is not running.\n" +
      "Install Docker: https://docs.docker.com/get-docker/\n" +
      "Start the daemon: sudo systemctl start docker",
    );
  }
}

/** Check that git is installed. */
function requireGit(): void {
  try {
    execSync("git --version", { stdio: "pipe" });
  } catch {
    throw new Error("git is not installed. Install it first: https://git-scm.com/downloads");
  }
}

// ---------------------------------------------------------------------------
// LLM credential check
// ---------------------------------------------------------------------------

/**
 * Scan a .env file for at least one SECRET__*__API_KEY with a real value.
 * Returns true if at least one LLM provider key is configured.
 */
export function hasLlmCredentials(envPath: string): boolean {
  if (!existsSync(envPath)) return false;
  const content = readFileSync(envPath, "utf-8");
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("#") || !trimmed) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;
    const key = trimmed.slice(0, eqIdx);
    const value = trimmed.slice(eqIdx + 1).trim();
    if (
      /^SECRET__\w+__API_KEY$/.test(key) &&
      value &&
      value !== "IMPORTED_TO_VAULT"
    ) {
      return true;
    }
  }
  return false;
}

function requireLlmCredentials(installPath: string): void {
  const envPath = join(installPath, ".env");
  if (!existsSync(envPath)) {
    throw new Error(
      "No .env file found. Run 'openmates server install' first, or create .env from .env.example.",
    );
  }
  if (!hasLlmCredentials(envPath)) {
    throw new Error(
      "No LLM provider API key found in .env.\n" +
      "At least one AI provider API key is required to start the server.\n\n" +
      "Add at least one of these to your .env file:\n" +
      "  SECRET__OPENAI__API_KEY=sk-...\n" +
      "  SECRET__ANTHROPIC__API_KEY=sk-ant-...\n" +
      "  SECRET__GOOGLE__API_KEY=...\n\n" +
      "Then run 'openmates server start' again.",
    );
  }
}

// ---------------------------------------------------------------------------
// Destructive operation confirmation
// ---------------------------------------------------------------------------

export async function confirmDestructive(phrase: string): Promise<boolean> {
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  return new Promise((resolve) => {
    rl.question(`Type "${phrase}" to confirm: `, (answer) => {
      rl.close();
      resolve(answer.trim() === phrase);
    });
  });
}

// ---------------------------------------------------------------------------
// JSON output helper
// ---------------------------------------------------------------------------

function printJson(data: unknown): void {
  console.log(JSON.stringify(data, null, 2));
}

// ---------------------------------------------------------------------------
// Subcommands
// ---------------------------------------------------------------------------

async function serverStatus(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  const config = loadServerConfig();
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides), "ps"];

  if (flags.json === true) {
    args.push("--format", "json");
  }

  const code = await runInteractive("docker", args, installPath);
  if (code !== 0) process.exit(code);
}

async function serverStart(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  requireLlmCredentials(installPath);

  const withOverrides = flags["with-overrides"] === true;
  const args = [...composeArgs(installPath, withOverrides), "up", "-d"];

  // Update saved profile if starting with overrides
  const config = loadServerConfig();
  if (config && withOverrides && config.composeProfile !== "full") {
    saveServerConfig({ ...config, composeProfile: "full" });
  }

  console.error("Starting OpenMates server...");
  const code = await runInteractive("docker", args, installPath);
  if (code !== 0) process.exit(code);

  if (flags.json === true) {
    printJson({ command: "start", status: "success", path: installPath });
  } else {
    console.log("\nServer started. API available at http://localhost:8000");
    if (withOverrides) {
      console.log("Directus CMS: http://localhost:8055");
      console.log("Grafana:      http://localhost:3000");
    }
  }
}

async function serverStop(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  const config = loadServerConfig();
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides), "down"];

  console.error("Stopping OpenMates server...");
  const code = await runInteractive("docker", args, installPath);
  if (code !== 0) process.exit(code);

  if (flags.json === true) {
    printJson({ command: "stop", status: "success", path: installPath });
  } else {
    console.log("Server stopped.");
  }
}

async function serverRestart(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  const config = loadServerConfig();
  const withOverrides = config?.composeProfile === "full";

  if (flags.rebuild === true) {
    // Full rebuild: down → rm cache → build → up
    console.error("Rebuilding OpenMates server (this may take a few minutes)...");
    const downArgs = [...composeArgs(installPath, withOverrides), "down"];
    let code = await runInteractive("docker", downArgs, installPath);
    if (code !== 0) process.exit(code);

    // Remove cache volume (non-fatal if it doesn't exist)
    try {
      exec("docker volume rm openmates-cache-data", installPath);
    } catch {
      // Volume may not exist — that's fine
    }

    const buildArgs = [...composeArgs(installPath, withOverrides), "build"];
    code = await runInteractive("docker", buildArgs, installPath);
    if (code !== 0) process.exit(code);

    const upArgs = [...composeArgs(installPath, withOverrides), "up", "-d"];
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);
  } else {
    // Graceful restart (no rebuild)
    console.error("Restarting OpenMates server...");
    const args = [...composeArgs(installPath, withOverrides), "restart"];
    const code = await runInteractive("docker", args, installPath);
    if (code !== 0) process.exit(code);
  }

  if (flags.json === true) {
    printJson({ command: "restart", status: "success", path: installPath, rebuild: flags.rebuild === true });
  } else {
    console.log("Server restarted.");
  }
}

async function serverLogs(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  const config = loadServerConfig();
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides), "logs"];

  if (flags.follow === true || flags.f === true) {
    args.push("--follow");
  }

  const tail = flags.tail;
  if (typeof tail === "string") {
    args.push("--tail", tail);
  } else {
    args.push("--tail", "100");
  }

  const container = flags.container;
  if (typeof container === "string") {
    args.push(container);
  }

  const code = await runInteractive("docker", args, installPath);
  if (code !== 0) process.exit(code);
}

async function serverInstall(flags: Record<string, string | boolean>): Promise<void> {
  requireGit();

  const installPath = typeof flags.path === "string" ? resolve(flags.path) : DEFAULT_INSTALL_PATH;

  // Check if already installed
  if (existsSync(join(installPath, "setup.sh"))) {
    console.error(`OpenMates already exists at ${installPath}.`);
    console.error("Use 'openmates server update' to update, or choose a different --path.");
    process.exit(1);
  }

  // Clone the repository
  console.error(`Cloning OpenMates to ${installPath}...`);
  const cloneCode = await runInteractive(
    "git",
    ["clone", REPO_URL, installPath],
    process.cwd(),
  );
  if (cloneCode !== 0) {
    throw new Error("Failed to clone the OpenMates repository.");
  }

  // Copy custom .env if provided
  if (typeof flags["env-path"] === "string") {
    const envSource = resolve(flags["env-path"]);
    if (!existsSync(envSource)) {
      throw new Error(`Env file not found: ${envSource}`);
    }
    copyFileSync(envSource, join(installPath, ".env"));
    console.error(`Copied ${envSource} to ${installPath}/.env`);
  }

  // Run setup.sh
  console.error("\nRunning setup script...");
  const setupCode = await runInteractive(
    "bash",
    ["setup.sh"],
    installPath,
  );
  if (setupCode !== 0) {
    console.error("Setup script failed. Check the output above for details.");
    process.exit(setupCode);
  }

  // Save config
  saveServerConfig({
    installPath,
    installedAt: Date.now(),
    composeProfile: "core",
  });

  if (flags.json === true) {
    printJson({ command: "install", status: "success", path: installPath });
  } else {
    console.log(`\nOpenMates installed at ${installPath}`);
    console.log("\nNext steps:");
    console.log("  1. Edit .env to add your LLM provider API key(s)");
    console.log("  2. Run: openmates server start");
    console.log("  3. Find your invite code: openmates server logs --container cms-setup --tail 50");
    console.log("  4. Open http://localhost:5173 and sign up");
    console.log("  5. Make yourself admin: openmates server make-admin your@email.com");
  }
}

async function serverUpdate(flags: Record<string, string | boolean>): Promise<void> {
  requireGit();
  requireDocker();
  const installPath = resolveServerPath(flags);

  console.error("Updating OpenMates...");

  // Pull latest code
  if (flags.force === true) {
    console.error("Stashing local changes...");
    try { exec("git stash", installPath); } catch { /* nothing to stash */ }
  }

  try {
    const pullOutput = exec("git pull --ff-only", installPath);
    console.error(pullOutput || "Already up to date.");
  } catch (e: unknown) {
    if (flags.force === true) {
      // Restore stash before throwing
      try { exec("git stash pop", installPath); } catch { /* no stash */ }
    }
    throw new Error(
      "Failed to pull updates. Your local branch may have diverged.\n" +
      "Use --force to stash local changes and retry, or resolve manually with git.",
    );
  }

  if (flags.force === true) {
    try { exec("git stash pop", installPath); } catch { /* no stash to pop */ }
  }

  // Rebuild and restart
  const config = loadServerConfig();
  const withOverrides = config?.composeProfile === "full";
  const buildArgs = [...composeArgs(installPath, withOverrides), "build"];
  console.error("Rebuilding containers...");
  let code = await runInteractive("docker", buildArgs, installPath);
  if (code !== 0) process.exit(code);

  const upArgs = [...composeArgs(installPath, withOverrides), "up", "-d"];
  code = await runInteractive("docker", upArgs, installPath);
  if (code !== 0) process.exit(code);

  if (flags.json === true) {
    printJson({ command: "update", status: "success", path: installPath });
  } else {
    console.log("Server updated and restarted.");
  }
}

async function serverReset(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  const config = loadServerConfig();
  const withOverrides = config?.composeProfile === "full";

  const userDataOnly = flags["delete-user-data-only"] === true;

  if (userDataOnly) {
    console.error("\nWARNING: This will delete all user data (database and cache).");
    console.error("Server configuration and code will be preserved.\n");
  } else {
    console.error("\nWARNING: This will stop the server and delete ALL data including:");
    console.error("  - Database (all user accounts, chats, settings)");
    console.error("  - Cache");
    console.error("  - All Docker volumes\n");
  }

  if (flags.yes !== true) {
    const confirmed = await confirmDestructive("DELETE ALL DATA");
    if (!confirmed) {
      console.error("Reset cancelled.");
      return;
    }
  }

  console.error("Resetting server...");

  if (userDataOnly) {
    // Stop, remove specific volumes, restart
    const downArgs = [...composeArgs(installPath, withOverrides), "down"];
    let code = await runInteractive("docker", downArgs, installPath);
    if (code !== 0) process.exit(code);

    // Remove data volumes
    for (const vol of ["openmates-cache-data", "openmates-cms-database-data"]) {
      try {
        exec(`docker volume rm ${vol}`, installPath);
        console.error(`  Removed volume: ${vol}`);
      } catch {
        // Volume may not exist
      }
    }

    // Rebuild and restart
    const buildArgs = [...composeArgs(installPath, withOverrides), "build"];
    code = await runInteractive("docker", buildArgs, installPath);
    if (code !== 0) process.exit(code);

    const upArgs = [...composeArgs(installPath, withOverrides), "up", "-d"];
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);
  } else {
    // Full reset: remove everything
    const args = [...composeArgs(installPath, withOverrides), "down", "-v"];
    const code = await runInteractive("docker", args, installPath);
    if (code !== 0) process.exit(code);
  }

  if (flags.json === true) {
    printJson({ command: "reset", status: "success", path: installPath, userDataOnly });
  } else {
    console.log("Server reset complete.");
    if (!userDataOnly) {
      console.log("Run 'openmates server start' to start fresh.");
    }
  }
}

async function serverMakeAdmin(
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);

  const email = rest[0];
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw new Error(
      "Usage: openmates server make-admin <email>\n" +
      "Provide a valid email address of the user to grant admin privileges.",
    );
  }

  console.error(`Granting admin privileges to ${email}...`);
  const code = await runInteractive(
    "docker",
    ["exec", "api", "python", "/app/backend/scripts/create_admin.py", email],
    installPath,
  );
  if (code !== 0) {
    throw new Error(
      "Failed to grant admin privileges. Make sure:\n" +
      "  - The server is running ('openmates server status')\n" +
      "  - The user has signed up with this email address",
    );
  }

  if (flags.json === true) {
    printJson({ command: "make-admin", status: "success", email });
  } else {
    console.log(`Admin privileges granted to ${email}.`);
  }
}

async function serverUninstall(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  const config = loadServerConfig();
  const withOverrides = config?.composeProfile === "full";
  const keepData = flags["keep-data"] === true;

  console.error("\nWARNING: This will completely uninstall OpenMates:");
  console.error(`  - Stop and remove all containers`);
  if (!keepData) {
    console.error("  - Delete all Docker volumes (database, cache — ALL DATA LOST)");
  } else {
    console.error("  - Docker volumes will be PRESERVED (data can be restored)");
  }
  console.error("  - Remove locally built Docker images");
  console.error("  - Remove the Docker network");
  console.error(`  - Delete the installation directory: ${installPath}`);
  console.error("");

  if (flags.yes !== true) {
    const confirmed = await confirmDestructive("UNINSTALL OPENMATES");
    if (!confirmed) {
      console.error("Uninstall cancelled.");
      return;
    }
  }

  console.error("Uninstalling OpenMates...");

  // 1. Stop containers and remove volumes + locally built images
  const downArgs = [...composeArgs(installPath, withOverrides), "down", "--rmi", "local"];
  if (!keepData) {
    downArgs.push("-v");
  }
  await runInteractive("docker", downArgs, installPath);

  // 2. Remove Docker network
  try {
    exec("docker network rm openmates", installPath);
    console.error("  Removed Docker network: openmates");
  } catch {
    // Network may not exist or may be in use
  }

  // 3. Remove installation directory
  try {
    rmSync(installPath, { recursive: true, force: true });
    console.error(`  Removed installation directory: ${installPath}`);
  } catch (e: unknown) {
    console.error(`  Could not remove ${installPath}: ${e instanceof Error ? e.message : e}`);
  }

  // 4. Remove server config
  removeServerConfig();

  if (flags.json === true) {
    printJson({ command: "uninstall", status: "success", path: installPath, keepData });
  } else {
    console.log("\nOpenMates has been uninstalled.");
    if (keepData) {
      console.log("Docker volumes were preserved. Reinstall and restart to recover data.");
    }
  }
}

// ---------------------------------------------------------------------------
// Help
// ---------------------------------------------------------------------------

export function printServerHelp(): void {
  console.log(`
OpenMates Server Management

Usage: openmates server <command> [options]

Commands:
  install         Install OpenMates server (clone repo + run setup)
  start           Start the server
  stop            Stop the server
  restart         Restart the server
  status          Show server status (container health)
  logs            Display server logs
  update          Update to latest version (git pull + rebuild)
  make-admin      Grant admin privileges to a user
  reset           Reset server data (requires confirmation)
  uninstall       Completely remove OpenMates (requires confirmation)

Global Options:
  --path <dir>    Override the server installation directory
  --json          Output machine-readable JSON
  --help          Show this help message

Command Options:
  install:
    --path <dir>        Install directory (default: ~/openmates)
    --env-path <file>   Copy a pre-existing .env file during install

  start:
    --with-overrides    Include admin UIs (Directus CMS, Grafana)

  restart:
    --rebuild           Full rebuild (down + build + up) instead of graceful restart

  logs:
    --container <name>  Filter logs to a specific service (e.g. api, cms)
    --follow, -f        Stream logs in real time
    --tail <n>          Number of lines to show (default: 100)

  update:
    --force             Stash local changes before pulling

  reset:
    --delete-user-data-only   Only delete database and cache (preserve config)
    --yes                     Skip confirmation prompt

  uninstall:
    --keep-data         Preserve Docker volumes (data can be restored later)
    --yes               Skip confirmation prompt

  make-admin:
    openmates server make-admin <email>

Examples:
  openmates server install
  openmates server start --with-overrides
  openmates server logs --container api --follow
  openmates server make-admin user@example.com
  openmates server update
  openmates server restart --rebuild
`.trim());
}

// ---------------------------------------------------------------------------
// Dispatcher
// ---------------------------------------------------------------------------

export async function handleServer(
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printServerHelp();
    return;
  }

  switch (subcommand) {
    case "status":     return serverStatus(flags);
    case "start":      return serverStart(flags);
    case "stop":       return serverStop(flags);
    case "restart":    return serverRestart(flags);
    case "logs":       return serverLogs(flags);
    case "install":    return serverInstall(flags);
    case "update":     return serverUpdate(flags);
    case "reset":      return serverReset(flags);
    case "make-admin": return serverMakeAdmin(rest, flags);
    case "uninstall":  return serverUninstall(flags);
    default:
      throw new Error(`Unknown server command '${subcommand}'. Run 'openmates server --help'.`);
  }
}
