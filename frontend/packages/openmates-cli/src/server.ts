/*
 * OpenMates CLI server management commands.
 *
 * Purpose: install, start, stop, restart, update, reset, and monitor a
 *          self-hosted OpenMates instance via Docker Compose.
 * Architecture: shells out to git/docker — no OpenMatesClient or login required.
 * Architecture doc: docs/architecture/apps/cli-remote-access.md
 * Tests: frontend/packages/openmates-cli/tests/server.test.ts
 */

import { execSync, spawn as nodeSpawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

const SOURCE_COMPOSE_FILE = join("backend", "core", "docker-compose.yml");
const IMAGE_COMPOSE_FILE = join("backend", "core", "docker-compose.selfhost.yml");
const COMPOSE_OVERRIDE = join("backend", "core", "docker-compose.override.yml");
const DEFAULT_INSTALL_PATH = join(homedir(), "openmates");
const REPO_URL = "https://github.com/glowingkitty/OpenMates.git";
const DEV_BRANCH = "dev";
const DEFAULT_IMAGE_REGISTRY = "ghcr.io/glowingkitty";
const MINIMAL_ENV_TEMPLATE = `# OpenMates self-host image-mode environment
SECRET__MISTRAL_AI__API_KEY=
SECRET__CEREBRAS__API_KEY=
SECRET__GROQ__API_KEY=
SECRET__OPENAI__API_KEY=
SECRET__ANTHROPIC__API_KEY=
SECRET__GOOGLE_AI_STUDIO__API_KEY=
SECRET__OPENROUTER__API_KEY=
SECRET__TOGETHER__API_KEY=
SECRET__BRAVE__API_KEY=
SECRET__FIRECRAWL__API_KEY=
SECRET__CONTEXT7__API_KEY=
DATABASE_ADMIN_EMAIL=admin@example.com
DATABASE_ADMIN_PASSWORD=
DATABASE_NAME=directus
DATABASE_USERNAME=directus
DATABASE_PASSWORD=
DIRECTUS_TOKEN=
DIRECTUS_SECRET=
DRAGONFLY_PASSWORD=
OPENOBSERVE_ROOT_EMAIL=admin@openmates.internal
OPENOBSERVE_ROOT_PASSWORD=
INTERNAL_API_SHARED_TOKEN=
TUNNEL_TRIGGER_SECRET=<PLACEHOLDER>
SERVER_ENVIRONMENT=production
FRONTEND_URLS="http://localhost:5173"
PRODUCTION_URL="http://localhost:5173"
TRUSTED_PROXY_IPS="172.16.0.0/12"
CORE_SIDECAR_URL=http://admin-sidecar:8001
CLEAR_CACHE_ON_UPDATE=true
SIGNUP_LIMIT=20
SELF_HOST_SIGNUP_MODE=invite_only
SELF_HOST_SIGNUP_ALLOWED_DOMAINS=
SELF_HOST_FIRST_INVITE_CODE=
APPLICATION_PREVIEW_ORIGIN=
OPENMATES_IMAGE_REGISTRY=${DEFAULT_IMAGE_REGISTRY}
OPENMATES_IMAGE_TAG=
GIT_WORK_DIR=
DOCKER_GID=999
`;
const VAULT_CONFIG_TEMPLATE = `# Minimal Vault configuration
listener "tcp" {
  address = "0.0.0.0:8200"
  tls_disable = true
}

storage "file" {
  path = "/vault/file"
}

api_addr = "http://0.0.0.0:8200"
ui = false
disable_mlock = true
log_level = "info"
`;
const LLM_PROVIDER_ENV_KEYS = new Set([
  "SECRET__MISTRAL_AI__API_KEY",
  "SECRET__CEREBRAS__API_KEY",
  "SECRET__GROQ__API_KEY",
  "SECRET__OPENAI__API_KEY",
  "SECRET__ANTHROPIC__API_KEY",
  "SECRET__GOOGLE_AI_STUDIO__API_KEY",
  "SECRET__OPENROUTER__API_KEY",
  "SECRET__TOGETHER__API_KEY",
]);

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

function loadConfigForInstallPath(installPath: string): ServerConfig | null {
  const config = loadServerConfig();
  return config?.installPath === installPath ? config : null;
}

function getInstallMode(
  installPath: string,
  config: ServerConfig | null = loadConfigForInstallPath(installPath),
): NonNullable<ServerConfig["installMode"]> {
  if (config?.installMode) return config.installMode;
  if (existsSync(join(installPath, IMAGE_COMPOSE_FILE))) return "image";
  return "source";
}

function shouldPullImages(): boolean {
  return process.env.OPENMATES_SKIP_IMAGE_PULL !== "1";
}

/** Build the docker compose argument array. */
export function composeArgs(
  installPath: string,
  withOverrides: boolean,
  installMode: ServerConfig["installMode"] = getInstallMode(installPath),
): string[] {
  const composeFile = installMode === "image" ? IMAGE_COMPOSE_FILE : SOURCE_COMPOSE_FILE;
  const args = ["compose", "--env-file", ".env", "-f", composeFile];
  if (withOverrides && existsSync(join(installPath, COMPOSE_OVERRIDE))) {
    args.push("-f", COMPOSE_OVERRIDE);
  }
  return args;
}

/** Ensure compose interpolation has an absolute project mount path. */
function ensureGitWorkDirEnv(installPath: string): void {
  const envPath = join(installPath, ".env");
  if (!existsSync(envPath)) return;

  const content = readFileSync(envPath, "utf-8");
  const lineRegex = /^GIT_WORK_DIR=.*$/m;
  const value = `GIT_WORK_DIR=${installPath}`;

  if (lineRegex.test(content)) {
    const next = content.replace(lineRegex, value);
    if (next !== content) writeFileSync(envPath, next);
    return;
  }

  const separator = content.endsWith("\n") ? "" : "\n";
  writeFileSync(envPath, `${content}${separator}${value}\n`);
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

function getPackageVersion(): string {
  try {
    const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf-8")) as { version?: string };
    return packageJson.version ?? "";
  } catch {
    return "";
  }
}

function getDefaultImageTag(): string {
  const version = getPackageVersion();
  return version ? `v${version}` : "dev";
}

function defaultTemplateRefForVersion(version: string): string {
  return /-(alpha|beta|rc)(\.|\d|$)/.test(version) ? DEV_BRANCH : `v${version}`;
}

function randomHex(bytes: number): string {
  return randomBytes(bytes).toString("hex");
}

function generateInviteCode(): string {
  const digits = Array.from(randomBytes(12), (byte) => String(byte % 10)).join("");
  return `${digits.slice(0, 4)}-${digits.slice(4, 8)}-${digits.slice(8, 12)}`;
}

function getEnvVar(content: string, name: string): string {
  const match = content.match(new RegExp(`^${name}=(.*)$`, "m"));
  return match?.[1]?.replace(/^"|"$/g, "") ?? "";
}

function setEnvVar(content: string, name: string, value: string): string {
  const line = `${name}=${value}`;
  const pattern = new RegExp(`^${name}=.*$`, "m");
  if (pattern.test(content)) {
    return content.replace(pattern, line);
  }
  const separator = content.endsWith("\n") ? "" : "\n";
  return `${content}${separator}${line}\n`;
}

function setEnvIfEmpty(content: string, name: string, value: string): string {
  return getEnvVar(content, name) ? content : setEnvVar(content, name, value);
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to download ${url}: HTTP ${response.status}`);
  }
  return response.text();
}

async function loadSelfHostComposeTemplate(version: string): Promise<string> {
  const templateDir = process.env.OPENMATES_SELFHOST_TEMPLATE_DIR;
  if (templateDir) {
    return readFileSync(join(resolve(templateDir), IMAGE_COMPOSE_FILE), "utf-8");
  }

  const overrideUrl = process.env.OPENMATES_SELFHOST_COMPOSE_URL;
  if (overrideUrl) {
    return fetchText(overrideUrl);
  }

  const ref = defaultTemplateRefForVersion(version);
  return fetchText(
    `https://raw.githubusercontent.com/glowingkitty/OpenMates/${ref}/backend/core/docker-compose.selfhost.yml`,
  );
}

async function writeImageModeRuntimeFiles(installPath: string, imageTag: string): Promise<void> {
  const coreDir = join(installPath, "backend", "core");
  const vaultConfigDir = join(coreDir, "vault", "config");
  mkdirSync(vaultConfigDir, { recursive: true });
  writeFileSync(join(coreDir, "docker-compose.selfhost.yml"), await loadSelfHostComposeTemplate(getPackageVersion()));
  writeFileSync(join(vaultConfigDir, "vault.hcl"), VAULT_CONFIG_TEMPLATE);

  const envPath = join(installPath, ".env");
  let envContent = existsSync(envPath) ? readFileSync(envPath, "utf-8") : MINIMAL_ENV_TEMPLATE;
  envContent = setEnvIfEmpty(envContent, "DATABASE_ADMIN_PASSWORD", randomHex(12));
  envContent = setEnvIfEmpty(envContent, "DATABASE_PASSWORD", randomHex(12));
  envContent = setEnvIfEmpty(envContent, "DIRECTUS_TOKEN", randomHex(32));
  envContent = setEnvIfEmpty(envContent, "DIRECTUS_SECRET", randomHex(32));
  envContent = setEnvIfEmpty(envContent, "DRAGONFLY_PASSWORD", randomHex(12));
  envContent = setEnvIfEmpty(envContent, "OPENOBSERVE_ROOT_PASSWORD", randomHex(32));
  envContent = setEnvIfEmpty(envContent, "INTERNAL_API_SHARED_TOKEN", randomHex(32));
  envContent = setEnvIfEmpty(envContent, "SELF_HOST_FIRST_INVITE_CODE", generateInviteCode());
  envContent = setEnvVar(envContent, "OPENMATES_IMAGE_TAG", imageTag);
  envContent = setEnvVar(envContent, "OPENMATES_IMAGE_REGISTRY", DEFAULT_IMAGE_REGISTRY);
  envContent = setEnvVar(envContent, "GIT_WORK_DIR", installPath);
  writeFileSync(envPath, envContent.endsWith("\n") ? envContent : `${envContent}\n`);
}

export function defaultCloneBranchForVersion(version: string): string | null {
  return /-(alpha|beta|rc)(\.|\d|$)/.test(version) ? DEV_BRANCH : null;
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
      LLM_PROVIDER_ENV_KEYS.has(key) &&
      value &&
      value !== "IMPORTED_TO_VAULT"
    ) {
      return true;
    }
  }
  return false;
}

function warnIfMissingLlmCredentials(installPath: string): void {
  const envPath = join(installPath, ".env");
  if (!existsSync(envPath)) {
    console.error(
      "No .env file found. Run 'openmates server install' first, or create .env from .env.example.",
    );
    return;
  }
  if (!hasLlmCredentials(envPath)) {
    console.error(
      "No LLM provider API key found in .env.\n" +
      "OpenMates will start, but AI chat/model processing will stay unavailable until you add one.\n\n" +
      "Add at least one of these to your .env file:\n" +
      "  SECRET__OPENAI__API_KEY=sk-...\n" +
      "  SECRET__ANTHROPIC__API_KEY=sk-ant-...\n" +
      "  SECRET__GOOGLE_AI_STUDIO__API_KEY=...\n\n" +
      "After updating .env, run 'openmates server restart'.",
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
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config)), "ps"];

  if (flags.json === true) {
    args.push("--format", "json");
  }

  const code = await runInteractive("docker", args, installPath);
  if (code !== 0) process.exit(code);
}

async function serverStart(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  ensureGitWorkDirEnv(installPath);
  warnIfMissingLlmCredentials(installPath);

  const withOverrides = flags["with-overrides"] === true;
  const config = loadConfigForInstallPath(installPath);
  const installMode = getInstallMode(installPath, config);
  const pullArgs = [...composeArgs(installPath, withOverrides, installMode), "pull"];
  const args = [...composeArgs(installPath, withOverrides, installMode), "up", "-d"];

  // Update saved profile if starting with overrides
  if (config && withOverrides && config.composeProfile !== "full") {
    saveServerConfig({ ...config, composeProfile: "full" });
  }

  console.error("Starting OpenMates server...");
  let code = 0;
  if (installMode === "image" && shouldPullImages()) {
    code = await runInteractive("docker", pullArgs, installPath);
    if (code !== 0) process.exit(code);
  }
  code = await runInteractive("docker", args, installPath);
  if (code !== 0) process.exit(code);

  if (flags.json === true) {
    printJson({ command: "start", status: "success", path: installPath });
  } else {
    console.log("\nServer started.");
    console.log("Web app: http://localhost:5173");
    console.log("API:     http://localhost:8000");
    if (withOverrides) {
      console.log("Directus CMS: http://localhost:8055");
      console.log("Grafana:      http://localhost:3000");
    }
  }
}

async function serverStop(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config)), "down"];

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
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const withOverrides = config?.composeProfile === "full";
  const installMode = getInstallMode(installPath, config);

  if (flags.rebuild === true) {
    if (installMode === "image") {
      throw new Error(
        "Image-mode installs use prebuilt images and cannot rebuild locally. " +
        "Run 'openmates server update' to pull newer images, or reinstall with --from-source to build from source.",
      );
    }
    // Full rebuild: down → rm cache → build → up
    console.error("Rebuilding OpenMates server (this may take a few minutes)...");
    const downArgs = [...composeArgs(installPath, withOverrides, installMode), "down"];
    let code = await runInteractive("docker", downArgs, installPath);
    if (code !== 0) process.exit(code);

    // Remove cache volume (non-fatal if it doesn't exist)
    try {
      exec("docker volume rm openmates-cache-data", installPath);
    } catch {
      // Volume may not exist — that's fine
    }

    const buildArgs = [...composeArgs(installPath, withOverrides, installMode), "build"];
    code = await runInteractive("docker", buildArgs, installPath);
    if (code !== 0) process.exit(code);

    const upArgs = [...composeArgs(installPath, withOverrides, installMode), "up", "-d"];
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);
  } else {
    // Graceful restart (no rebuild)
    console.error("Restarting OpenMates server...");
    const args = [...composeArgs(installPath, withOverrides, installMode), "restart"];
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
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config)), "logs"];

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
  const installPath = typeof flags.path === "string" ? resolve(flags.path) : DEFAULT_INSTALL_PATH;
  const sourcePath = typeof flags["source-path"] === "string" ? resolve(flags["source-path"]) : null;
  const fromSource = flags["from-source"] === true || sourcePath !== null;

  // Check if already installed
  if (existsSync(join(installPath, SOURCE_COMPOSE_FILE)) || existsSync(join(installPath, IMAGE_COMPOSE_FILE))) {
    console.error(`OpenMates already exists at ${installPath}.`);
    console.error("Use 'openmates server update' to update, or choose a different --path.");
    process.exit(1);
  }

  if (!fromSource) {
    requireDocker();
    mkdirSync(installPath, { recursive: true });

    // Copy custom .env if provided before generated defaults are filled in.
    if (typeof flags["env-path"] === "string") {
      const envSource = resolve(flags["env-path"]);
      if (!existsSync(envSource)) {
        throw new Error(`Env file not found: ${envSource}`);
      }
      copyFileSync(envSource, join(installPath, ".env"));
      console.error(`Copied ${envSource} to ${installPath}/.env`);
    }

    const imageTag = typeof flags["image-tag"] === "string" ? flags["image-tag"] : getDefaultImageTag();
    console.error(`Preparing OpenMates image-mode install at ${installPath}...`);
    await writeImageModeRuntimeFiles(installPath, imageTag);
    try {
      exec("docker network create openmates", installPath);
    } catch {
      // Network already exists.
    }

    saveServerConfig({
      installPath,
      installedAt: Date.now(),
      composeProfile: "core",
      installMode: "image",
      imageTag,
    });

    if (flags.json === true) {
      printJson({ command: "install", status: "success", path: installPath, mode: "image", imageTag });
    } else {
      const firstInvite = getEnvVar(readFileSync(join(installPath, ".env"), "utf-8"), "SELF_HOST_FIRST_INVITE_CODE");
      console.log(`\nOpenMates installed at ${installPath}`);
      console.log(`Mode: image (${DEFAULT_IMAGE_REGISTRY}, tag ${imageTag})`);
      console.log("\nNext steps:");
      console.log("  1. Run: openmates server start");
      console.log("  2. Open http://localhost:5173");
      if (firstInvite) console.log(`  3. Sign up with invite code: ${firstInvite}`);
      console.log("  4. After signup, make yourself admin: openmates server make-admin your@email.com");
      console.log("\nOptional: edit .env first to add LLM provider API keys. Source builds are available with --from-source.");
    }
    return;
  }

  requireGit();

  // Clone the repository. CI can pass --source-path to test the checked-out branch
  // instead of whatever is currently published on the default remote branch.
  const cloneSource = sourcePath ?? REPO_URL;
  const cloneBranch = sourcePath ? null : defaultCloneBranchForVersion(getPackageVersion());
  const cloneArgs = ["clone"];
  if (cloneBranch) {
    cloneArgs.push("--branch", cloneBranch);
  }
  cloneArgs.push(cloneSource, installPath);
  console.error(`Cloning OpenMates from ${cloneSource} to ${installPath}...`);
  if (cloneBranch) {
    console.error(`Using ${cloneBranch} branch for this prerelease CLI.`);
  }
  const cloneCode = await runInteractive(
    "git",
    cloneArgs,
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
    installMode: "source",
  });

  if (flags.json === true) {
    printJson({ command: "install", status: "success", path: installPath, mode: "source" });
  } else {
    console.log(`\nOpenMates installed at ${installPath}`);
    console.log("\nNext steps:");
    console.log("  1. Run: openmates server start");
    console.log("  2. Open http://localhost:5173");
    console.log("  3. After signup, make yourself admin: openmates server make-admin your@email.com");
    console.log("\nOptional: edit .env first to add LLM provider API keys. Without keys, the web app and backend still start, but AI model processing is unavailable.");
  }
}

async function serverUpdate(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  ensureGitWorkDirEnv(installPath);

  console.error("Updating OpenMates...");

  const config = loadConfigForInstallPath(installPath);
  const withOverrides = config?.composeProfile === "full";
  const installMode = getInstallMode(installPath, config);

  if (installMode === "image") {
    const pullArgs = [...composeArgs(installPath, withOverrides, installMode), "pull"];
    console.error("Pulling prebuilt images...");
    let code = await runInteractive("docker", pullArgs, installPath);
    if (code !== 0) process.exit(code);

    const upArgs = [...composeArgs(installPath, withOverrides, installMode), "up", "-d"];
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);

    if (flags.json === true) {
      printJson({ command: "update", status: "success", path: installPath, mode: "image" });
    } else {
      console.log("Server images pulled and containers restarted.");
    }
    return;
  }

  requireGit();

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
  const buildArgs = [...composeArgs(installPath, withOverrides, installMode), "build"];
  console.error("Rebuilding containers...");
  let code = await runInteractive("docker", buildArgs, installPath);
  if (code !== 0) process.exit(code);

  const upArgs = [...composeArgs(installPath, withOverrides, installMode), "up", "-d"];
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
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const withOverrides = config?.composeProfile === "full";
  const installMode = getInstallMode(installPath, config);

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
    const downArgs = [...composeArgs(installPath, withOverrides, installMode), "down"];
    let code = await runInteractive("docker", downArgs, installPath);
    if (code !== 0) process.exit(code);

    // Remove data volumes. Keep the legacy database volume name for older installs.
    for (const vol of ["openmates-cache-data", "openmates-postgres-data", "openmates-cms-database-data"]) {
      try {
        exec(`docker volume rm ${vol}`, installPath);
        console.error(`  Removed volume: ${vol}`);
      } catch {
        // Volume may not exist
      }
    }

    // Source installs rebuild after clearing data. Image installs restart from pulled images.
    if (installMode === "source") {
      const buildArgs = [...composeArgs(installPath, withOverrides, installMode), "build"];
      code = await runInteractive("docker", buildArgs, installPath);
      if (code !== 0) process.exit(code);
    }

    const upArgs = [...composeArgs(installPath, withOverrides, installMode), "up", "-d"];
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);
  } else {
    // Full reset: remove everything
    const args = [...composeArgs(installPath, withOverrides, installMode), "down", "-v"];
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
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
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
  const downArgs = [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config)), "down", "--rmi", "local"];
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
  install         Install OpenMates server (prebuilt GHCR images by default)
  start           Start the server
  stop            Stop the server
  restart         Restart the server
  status          Show server status (container health)
  logs            Display server logs
  update          Update to latest version (pull images, or git pull + rebuild for source installs)
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
    --image-tag <tag>   Prebuilt image tag (default: CLI version tag)
    --from-source       Clone/build from source instead of using prebuilt GHCR images
    --source-path <dir> Clone from a local checkout instead of GitHub (implies --from-source)

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
