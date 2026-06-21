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
import { createHash, randomBytes } from "node:crypto";
import { chmodSync, copyFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { createInterface as createPromptInterface } from "node:readline/promises";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";

import {
  type ServerConfig,
  loadServerConfig,
  removeServerConfig,
  resolveServerPath,
  saveServerConfig,
} from "./serverConfig.js";
import {
  type CaddyAction,
  type CoreProfile,
  type ServerRole,
  parseServerRole,
  planBackup,
  planCaddyCommand,
  planContinuousUpdateService,
  planRestore,
  planServerRuntime,
  planUpdate as planServerUpdate,
  resolveServiceSelection,
} from "./serverPlanning.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SOURCE_COMPOSE_FILE = join("backend", "core", "docker-compose.yml");
const ROLE_IMAGE_COMPOSE_FILES: Record<ServerRole, string> = {
  core: join("backend", "core", "docker-compose.selfhost.yml"),
  upload: join("backend", "upload", "docker-compose.yml"),
  preview: join("backend", "preview", "docker-compose.preview.yml"),
};
const ROLE_TEMPLATE_FILES: Record<ServerRole, string> = {
  core: join("core", "docker-compose.selfhost.yml"),
  upload: join("upload", "docker-compose.yml"),
  preview: join("preview", "docker-compose.preview.yml"),
};
const COMPOSE_OVERRIDE = join("backend", "core", "docker-compose.override.yml");
const DEFAULT_INSTALL_PATH = join(homedir(), "openmates");
const REPO_URL = "https://github.com/glowingkitty/OpenMates.git";
const DEV_BRANCH = "dev";
const MAIN_BRANCH = "main";
const DEFAULT_IMAGE_REGISTRY = "ghcr.io/glowingkitty";
const UPDATE_HEALTH_TIMEOUT_MS = 120_000;
const UPDATE_HEALTH_INTERVAL_MS = 5_000;
const HEALTH_REQUEST_TIMEOUT_MS = 5_000;
const IMAGE_CHANNEL_TAGS = {
  stable: MAIN_BRANCH,
  main: MAIN_BRANCH,
  dev: DEV_BRANCH,
} as const;
const BACKEND_CONFIG_FILE = join("backend", "config", "backend_config.yml");
const IMAGE_RUNTIME_CONFIG_FILE = join("config", "backend_config.yml");
const LOCAL_AI_MODELS_FILE = "local-ai-models.yml";
const OFF_BY_DEFAULT_FEATURES = new Map<string, string>([
  ["embed:code:application", "Application previews are still unstable"],
  ["platform:projects", "Projects workspace is not ready by default"],
  ["platform:workflows", "Workflows workspace is not implemented yet"],
  ["platform:tasks", "Tasks workspace is not implemented yet"],
]);
const LOCAL_MODEL_RUNTIME_DEFAULTS = {
  ollama: {
    label: "Ollama",
    serverId: "ollama",
    baseUrl: "http://host.docker.internal:11434/v1",
    apiKey: "ollama",
  },
  "lm-studio": {
    label: "LM Studio",
    serverId: "lm_studio",
    baseUrl: "http://host.docker.internal:1234/v1",
    apiKey: "lm-studio",
  },
  custom: {
    label: "Custom OpenAI-compatible API",
    serverId: "custom_openai_compatible",
    baseUrl: "",
    apiKey: "local",
  },
} as const;
const MODEL_CREATOR_OPTIONS = [
  { id: "alibaba", name: "Alibaba / Qwen", match: /(^|[-_:/])qwen/i },
  { id: "google", name: "Google / Gemma", match: /(^|[-_:/])gemma/i },
  { id: "mistral", name: "Mistral", match: /(^|[-_:/])(mistral|mixtral|ministral)/i },
  { id: "openai", name: "OpenAI", match: /(^|[-_:/])gpt-oss/i },
  { id: "deepseek", name: "DeepSeek", match: /(^|[-_:/])deepseek/i },
  { id: "custom", name: "Custom", match: null },
];
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
PROD_CORE_API_URL=
PROD_INTERNAL_API_SHARED_TOKEN=
DEV_CORE_API_URL=
DEV_INTERNAL_API_SHARED_TOKEN=
PREVIEW_CORS_ORIGINS=https://openmates.org
PREVIEW_ALLOWED_REFERERS=https://openmates.org/*
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
  if (Object.values(ROLE_IMAGE_COMPOSE_FILES).some((composeFile) => existsSync(join(installPath, composeFile)))) return "image";
  return "source";
}

function getServerRole(flags: Record<string, string | boolean>, config: ServerConfig | null): ServerRole {
  return parseServerRole(typeof flags.role === "string" ? flags.role : config?.serverRole);
}

function getCoreProfile(flags: Record<string, string | boolean>, config: ServerConfig | null): CoreProfile {
  const value = typeof flags.profile === "string" ? flags.profile : config?.serverProfile;
  if (value === "minimal" || value === "standard" || value === "production") return value;
  return "production";
}

function hasServiceFilter(flags: Record<string, string | boolean>): boolean {
  return typeof flags.services === "string" || typeof flags.exclude === "string";
}

function selectedComposeServices(role: ServerRole, flags: Record<string, string | boolean>): string[] {
  return resolveServiceSelection(role, {
    services: typeof flags.services === "string" ? flags.services : undefined,
    exclude: typeof flags.exclude === "string" ? flags.exclude : undefined,
  });
}

function shouldPullImages(): boolean {
  return process.env.OPENMATES_SKIP_IMAGE_PULL !== "1";
}

type FeatureOverrides = {
  enabled: string[];
  disabled: string[];
};

function normalizeFeatureList(items: string[]): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const item of items) {
    const value = item.trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

function parseListBlock(content: string, key: string): string[] {
  const match = content.match(new RegExp(`^${key}:\\n((?:[ \\t]+.*\\n?)*)`, "m"));
  if (!match) return [];
  const block = match[1] ?? "";
  return normalizeFeatureList(
    [...block.matchAll(/^\s*-\s*["']?([^"'\n#]+)["']?/gm)].map((item) => item[1] ?? ""),
  );
}

function parseFeatureOverrides(content: string): FeatureOverrides {
  const overridesMatch = content.match(/^feature_overrides:\n((?:[ \t]+.*\n?)*)/m);
  const overridesBlock = overridesMatch?.[1] ?? "";
  const enabled = parseListBlock(overridesBlock.replace(/^ {2}/gm, ""), "enabled");
  const disabled = parseListBlock(overridesBlock.replace(/^ {2}/gm, ""), "disabled");
  const legacyDisabledApps = parseListBlock(content, "disabled_apps").map((appId) =>
    appId.startsWith("app:") ? appId : `app:${appId}`,
  );
  return {
    enabled: normalizeFeatureList(enabled),
    disabled: normalizeFeatureList([...disabled, ...legacyDisabledApps]),
  };
}

function renderFeatureOverrides(overrides: FeatureOverrides): string {
  const renderList = (key: string, items: string[]) => {
    if (!items.length) return `  ${key}: []`;
    return [`  ${key}:`, ...items.map((item) => `    - "${item}"`)].join("\n");
  };
  return [
    "# Admin feature overrides. Changes require a server restart.",
    "feature_overrides:",
    renderList("enabled", overrides.enabled),
    renderList("disabled", overrides.disabled),
    "",
  ].join("\n");
}

function removeConfigBlock(content: string, key: string): string {
  return content.replace(new RegExp(`(?:^|\\n)#.*\\n${key}:\\n(?:[ \\t]+.*\\n?)*`, "m"), "\n")
    .replace(new RegExp(`^${key}:\\n(?:[ \\t]+.*\\n?)*`, "m"), "");
}

function updateFeatureOverridesContent(content: string, overrides: FeatureOverrides): string {
  let next = removeConfigBlock(content, "feature_overrides");
  next = removeConfigBlock(next, "disabled_apps");
  next = next.trimEnd();
  return `${next}\n\n${renderFeatureOverrides(overrides)}`;
}

function featureKind(featureId: string): string {
  return featureId.split(":", 1)[0] || "unknown";
}

/** Build the docker compose argument array. */
export function composeArgs(
  installPath: string,
  withOverrides: boolean,
  installMode: ServerConfig["installMode"] = getInstallMode(installPath),
  role: ServerRole = "core",
): string[] {
  const composeFile = installMode === "image" ? ROLE_IMAGE_COMPOSE_FILES[role] : SOURCE_COMPOSE_FILE;
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

export function getDefaultImageTagForVersion(version: string): string {
  return version ? `v${version}` : DEV_BRANCH;
}

function getDefaultImageTag(): string {
  const version = getPackageVersion();
  return getDefaultImageTagForVersion(version);
}

function defaultTemplateRefForVersion(version: string): string {
  return /-(alpha|beta|rc)(\.|\d|$)/.test(version) ? DEV_BRANCH : `v${version}`;
}

export function templateRefForImageTag(imageTag: string, packageVersion = ""): string {
  const channelTag = IMAGE_CHANNEL_TAGS[imageTag as keyof typeof IMAGE_CHANNEL_TAGS];
  if (channelTag) return channelTag;
  if (imageTag.startsWith("v")) return defaultTemplateRefForVersion(imageTag.slice(1));
  if (!imageTag && packageVersion) return defaultTemplateRefForVersion(packageVersion);
  return DEV_BRANCH;
}

export function resolveTargetImageTag(
  flags: Record<string, string | boolean>,
  currentTag: string,
  packageVersion: string,
): { tag: string; channel?: "dev" | "main" } {
  const imageTag = flags["image-tag"];
  const channel = flags.channel;
  if (imageTag === true) {
    throw new Error("Provide an image tag value: --image-tag <tag>.");
  }
  if (channel === true) {
    throw new Error("Provide an update channel value: --channel stable, --channel main, or --channel dev.");
  }
  if (typeof imageTag === "string" && typeof channel === "string") {
    throw new Error("Use either --image-tag or --channel, not both.");
  }

  if (typeof imageTag === "string") {
    const trimmed = imageTag.trim();
    if (!trimmed) throw new Error("--image-tag cannot be empty.");
    return { tag: trimmed };
  }

  if (typeof channel === "string") {
    const normalized = channel.trim().toLowerCase();
    const tag = IMAGE_CHANNEL_TAGS[normalized as keyof typeof IMAGE_CHANNEL_TAGS];
    if (!tag) {
      throw new Error("Unsupported update channel. Use --channel stable, --channel main, or --channel dev.");
    }
    return { tag, channel: tag };
  }

  const installedChannel = IMAGE_CHANNEL_TAGS[currentTag as keyof typeof IMAGE_CHANNEL_TAGS];
  if (installedChannel) return { tag: installedChannel, channel: installedChannel };
  return { tag: getDefaultImageTagForVersion(packageVersion) };
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

function firstCsvValue(value: string): string {
  return value.split(",").map((item) => item.trim()).find(Boolean) ?? "";
}

function deriveSelfHostCliUrls(envContent: string): { apiUrl: string; appUrl: string } {
  return {
    apiUrl: firstCsvValue(getEnvVar(envContent, "VITE_API_URL")) || "http://localhost:8000",
    appUrl: firstCsvValue(getEnvVar(envContent, "PRODUCTION_URL")) || "http://localhost:5173",
  };
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to download ${url}: HTTP ${response.status}`);
  }
  return response.text();
}

function packagedTemplatePath(role: ServerRole): string {
  return join(dirname(new URL(import.meta.url).pathname), "..", "templates", ROLE_TEMPLATE_FILES[role]);
}

function packagedCaddyTemplatePath(role: ServerRole): string {
  return join(dirname(new URL(import.meta.url).pathname), "..", "templates", "caddy", role, "Caddyfile");
}

function fileHash(path: string): string | null {
  if (!existsSync(path)) return null;
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

async function loadSelfHostComposeTemplate(templateRef: string, role: ServerRole): Promise<string> {
  const templateDir = process.env.OPENMATES_SELFHOST_TEMPLATE_DIR;
  if (templateDir) {
    return readFileSync(join(resolve(templateDir), ROLE_TEMPLATE_FILES[role]), "utf-8");
  }

  const overrideUrl = process.env.OPENMATES_SELFHOST_COMPOSE_URL;
  if (overrideUrl) {
    return fetchText(overrideUrl);
  }

  const packaged = packagedTemplatePath(role);
  if (existsSync(packaged)) return readFileSync(packaged, "utf-8");

  return fetchText(`https://raw.githubusercontent.com/glowingkitty/OpenMates/${templateRef}/${ROLE_IMAGE_COMPOSE_FILES[role]}`);
}

async function writeImageModeRuntimeFiles(installPath: string, imageTag: string, role: ServerRole): Promise<void> {
  const roleDir = join(installPath, "backend", role === "core" ? "core" : role);
  const vaultConfigDir = join(roleDir, "vault", "config");
  mkdirSync(vaultConfigDir, { recursive: true });
  mkdirSync(join(installPath, "config", "providers"), { recursive: true });
  writeFileSync(join(installPath, ROLE_IMAGE_COMPOSE_FILES[role]), await loadSelfHostComposeTemplate(templateRefForImageTag(imageTag, getPackageVersion()), role));
  writeFileSync(join(vaultConfigDir, "vault.hcl"), VAULT_CONFIG_TEMPLATE);
  ensureImageRuntimeConfig(installPath);

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

function getImageTagFromEnv(installPath: string, config: ServerConfig | null): string {
  const envPath = join(installPath, ".env");
  if (existsSync(envPath)) {
    const envTag = getEnvVar(readFileSync(envPath, "utf-8"), "OPENMATES_IMAGE_TAG");
    if (envTag) return envTag;
  }
  return config?.imageTag ?? "";
}

function trailingSlashTrimmed(value: string): string {
  return value.replace(/\/+$/, "");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

async function checkUrl(url: string): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HEALTH_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function waitForServerHealth(installPath: string, role: ServerRole = "core"): Promise<void> {
  if (role === "upload" || role === "preview") {
    const healthUrl = role === "upload" ? "http://localhost:8000/health" : "http://localhost:8080/health";
    const deadline = Date.now() + UPDATE_HEALTH_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (await checkUrl(healthUrl)) return;
      await sleep(UPDATE_HEALTH_INTERVAL_MS);
    }
    throw new Error(`Updated ${role} server did not pass health checks in time. Tried ${healthUrl}.`);
  }

  const envPath = join(installPath, ".env");
  const envContent = existsSync(envPath) ? readFileSync(envPath, "utf-8") : "";
  const urls = deriveSelfHostCliUrls(envContent);
  const apiHealthUrl = `${trailingSlashTrimmed(urls.apiUrl)}/health`;
  const appUrl = trailingSlashTrimmed(urls.appUrl);
  const deadline = Date.now() + UPDATE_HEALTH_TIMEOUT_MS;

  while (Date.now() < deadline) {
    const [apiOk, appOk] = await Promise.all([checkUrl(apiHealthUrl), checkUrl(appUrl)]);
    if (apiOk && appOk) return;
    await sleep(UPDATE_HEALTH_INTERVAL_MS);
  }

  throw new Error(
    "Updated containers started, but health checks did not pass in time. " +
    `Check 'openmates server status' and 'openmates server logs --tail 200'. Tried ${apiHealthUrl} and ${appUrl}.`,
  );
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
  if (hasLocalAiModels(dirname(envPath))) return true;
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
      "Run 'openmates server ai models add' to add a local Ollama/LM Studio model, or add at least one of these to your .env file:\n" +
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

type LocalModelOverlay = {
  providers: Array<{
    provider_id: string;
    name?: string;
    description?: string;
    models: Array<Record<string, unknown>>;
  }>;
};

type LocalRuntimeKey = keyof typeof LOCAL_MODEL_RUNTIME_DEFAULTS;

function localModelsOverlayPath(installPath: string, installMode = getInstallMode(installPath)): string {
  if (installMode === "source") return join(installPath, "backend", "providers", LOCAL_AI_MODELS_FILE);
  return join(installPath, "config", "providers", LOCAL_AI_MODELS_FILE);
}

function imageBackendConfigPath(installPath: string): string {
  return join(installPath, IMAGE_RUNTIME_CONFIG_FILE);
}

function ensureImageRuntimeConfig(installPath: string): void {
  const configPath = imageBackendConfigPath(installPath);
  if (existsSync(configPath)) return;
  mkdirSync(dirname(configPath), { recursive: true });
  writeFileSync(configPath, renderFeatureOverrides({ enabled: [], disabled: [] }));
}

function readLocalModelOverlay(path: string): LocalModelOverlay {
  if (!existsSync(path)) return { providers: [] };
  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8")) as LocalModelOverlay;
    return { providers: Array.isArray(parsed.providers) ? parsed.providers : [] };
  } catch (error) {
    throw new Error(
      `Could not parse ${path}. This file is managed by the OpenMates CLI and must remain JSON-compatible YAML. ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

function writeLocalModelOverlay(path: string, overlay: LocalModelOverlay): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(overlay, null, 2)}\n`);
}

function hasLocalAiModels(installPath: string): boolean {
  const imagePath = join(installPath, "config", "providers", LOCAL_AI_MODELS_FILE);
  const sourcePath = join(installPath, "backend", "providers", LOCAL_AI_MODELS_FILE);
  return [imagePath, sourcePath].some((path) => {
    if (!existsSync(path)) return false;
    try {
      return readLocalModelOverlay(path).providers.some((provider) => provider.models.length > 0);
    } catch {
      return false;
    }
  });
}

function sanitizeModelId(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "local-model";
}

function inferCreatorId(modelId: string): string {
  return MODEL_CREATOR_OPTIONS.find((option) => option.match?.test(modelId))?.id ?? "custom";
}

function creatorDisplayName(creatorId: string): string {
  return MODEL_CREATOR_OPTIONS.find((option) => option.id === creatorId)?.name ?? creatorId;
}

function normalizeCreatorId(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  return normalized || "custom_local";
}

function normalizeRuntimeKey(value: string): LocalRuntimeKey {
  const normalized = value.trim().toLowerCase().replace(/_/g, "-");
  if (normalized === "lmstudio" || normalized === "lm-studio") return "lm-studio";
  if (normalized === "ollama") return "ollama";
  return "custom";
}

function boolFromFlag(value: string | boolean | undefined, defaultValue = false): boolean {
  if (value === undefined) return defaultValue;
  if (value === true) return true;
  if (value === false) return false;
  const normalized = value.toLowerCase();
  return ["1", "true", "yes", "y", "on"].includes(normalized);
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

function nowStamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function backupRoot(installPath: string): string {
  return join(installPath, "backups");
}

function roleBackupDir(installPath: string, role: ServerRole): string {
  return join(backupRoot(installPath), role);
}

function updateStatusFile(installPath: string, role: ServerRole): string {
  return join(installPath, ".openmates", `${role}-update-status.json`);
}

function writeUpdateStatus(installPath: string, role: ServerRole, status: Record<string, unknown>): void {
  const filePath = updateStatusFile(installPath, role);
  mkdirSync(dirname(filePath), { recursive: true, mode: 0o700 });
  writeFileSync(filePath, `${JSON.stringify({ role, updated_at: new Date().toISOString(), ...status }, null, 2)}\n`, { mode: 0o600 });
}

function copyIfExists(source: string, destination: string): void {
  if (!existsSync(source)) return;
  mkdirSync(dirname(destination), { recursive: true });
  cpSync(source, destination, { recursive: true, force: true });
}

function readEnvMap(installPath: string): Record<string, string> {
  const envPath = join(installPath, ".env");
  if (!existsSync(envPath)) return {};
  const values: Record<string, string> = {};
  for (const line of readFileSync(envPath, "utf-8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;
    values[trimmed.slice(0, eqIdx)] = trimmed.slice(eqIdx + 1).replace(/^"|"$/g, "");
  }
  return values;
}

function requiredRuntimeEnvKeys(role: ServerRole): string[] {
  if (role === "core") {
    return [
      "DATABASE_ADMIN_EMAIL",
      "DATABASE_ADMIN_PASSWORD",
      "DATABASE_NAME",
      "DATABASE_USERNAME",
      "DATABASE_PASSWORD",
      "DIRECTUS_TOKEN",
      "DIRECTUS_SECRET",
      "DRAGONFLY_PASSWORD",
      "INTERNAL_API_SHARED_TOKEN",
    ];
  }
  if (role === "upload") {
    return ["PROD_CORE_API_URL", "PROD_INTERNAL_API_SHARED_TOKEN", "DEV_CORE_API_URL", "DEV_INTERNAL_API_SHARED_TOKEN"];
  }
  return ["PREVIEW_CORS_ORIGINS", "PREVIEW_ALLOWED_REFERERS"];
}

function missingRequiredEnvKeys(installPath: string, role: ServerRole): string[] {
  const env = readEnvMap(installPath);
  return requiredRuntimeEnvKeys(role).filter((key) => !env[key]);
}

function writeChecksums(rootDir: string): void {
  const lines: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(path);
        continue;
      }
      if (entry.name === "checksums.sha256") continue;
      const relative = path.slice(rootDir.length + 1);
      const hash = createHash("sha256").update(readFileSync(path)).digest("hex");
      lines.push(`${hash}  ${relative}`);
    }
  };
  walk(rootDir);
  writeFileSync(join(rootDir, "checksums.sha256"), `${lines.sort().join("\n")}\n`);
}

function verifyChecksums(rootDir: string): void {
  const checksumsPath = join(rootDir, "checksums.sha256");
  if (!existsSync(checksumsPath)) throw new Error("Backup archive is missing checksums.sha256.");

  for (const line of readFileSync(checksumsPath, "utf-8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const match = trimmed.match(/^([a-f0-9]{64}) {2}(.+)$/);
    if (!match) throw new Error(`Invalid checksum entry: ${trimmed}`);
    const relative = match[2];
    if (relative.startsWith("/") || relative.split(/[\\/]/).includes("..")) {
      throw new Error(`Unsafe checksum path in backup archive: ${relative}`);
    }
    const filePath = join(rootDir, relative);
    if (!existsSync(filePath)) throw new Error(`Backup archive is missing checksummed file: ${relative}`);
    const actual = createHash("sha256").update(readFileSync(filePath)).digest("hex");
    if (actual !== match[1]) throw new Error(`Backup checksum mismatch for ${relative}.`);
  }
}

function createServerBackup(installPath: string, role: ServerRole, options: { output?: string; includeObservability?: boolean; preUpdate?: boolean } = {}): string {
  const plan = planBackup({ role, includeObservability: options.includeObservability });
  const backupDir = roleBackupDir(installPath, role);
  mkdirSync(backupDir, { recursive: true, mode: 0o700 });
  const archivePath = options.output
    ? resolve(options.output)
    : join(backupDir, options.preUpdate ? `latest-pre-update-${role}.tar.gz` : `openmates-${role}-${nowStamp()}.tar.gz`);
  const tempDir = mkdtempSync(join(backupDir, ".tmp-"));
  const env = readEnvMap(installPath);
  const manifest = {
    role,
    created_at: new Date().toISOString(),
    cli_version: getPackageVersion(),
    image_tag: getEnvVar(existsSync(join(installPath, ".env")) ? readFileSync(join(installPath, ".env"), "utf-8") : "", "OPENMATES_IMAGE_TAG"),
    include_observability: options.includeObservability === true,
    contents: plan.contents,
  };

  try {
    writeFileSync(join(tempDir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
    copyIfExists(join(installPath, ".env"), join(tempDir, "runtime", ".env"));
    copyIfExists(join(installPath, "config"), join(tempDir, "runtime", "config"));

    if (role === "core") {
      const databaseUser = env.DATABASE_USERNAME || "directus";
      const databaseName = env.DATABASE_NAME || "directus";
      try {
        const dump = execSync(
          `docker exec cms-database pg_dump --clean --if-exists --no-owner --no-privileges -U ${shellQuote(databaseUser)} ${shellQuote(databaseName)}`,
          { encoding: "utf-8" },
        );
        writeFileSync(join(tempDir, "postgres.sql"), dump);
      } catch (error) {
        throw new Error(`Postgres backup failed. Is cms-database running? ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    for (const item of [
      [join(installPath, "backend", "core", "uploads"), join(tempDir, "directus-uploads")],
      [join(installPath, "backend", "core", "extensions"), join(tempDir, "directus-extensions")],
      [join(installPath, "backend", role, "vault"), join(tempDir, `${role}-vault-config`)],
    ] as Array<[string, string]>) {
      copyIfExists(item[0], item[1]);
    }

    writeChecksums(tempDir);
    execSync(`tar -czf ${shellQuote(archivePath)} -C ${shellQuote(tempDir)} .`, { stdio: "pipe" });
    chmodSync(archivePath, plan.fileMode);
    return archivePath;
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

function restoreServerBackup(installPath: string, role: ServerRole, file: string): void {
  const archivePath = resolve(file);
  if (!existsSync(archivePath)) throw new Error(`Backup file not found: ${archivePath}`);
  mkdirSync(roleBackupDir(installPath, role), { recursive: true, mode: 0o700 });
  const tempDir = mkdtempSync(join(roleBackupDir(installPath, role), ".restore-"));
  const env = readEnvMap(installPath);
  try {
    execSync(`tar -xzf ${shellQuote(archivePath)} -C ${shellQuote(tempDir)}`, { stdio: "pipe" });
    verifyChecksums(tempDir);
    const manifestPath = join(tempDir, "manifest.json");
    if (!existsSync(manifestPath)) throw new Error("Backup archive is missing manifest.json.");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf-8")) as { role?: string };
    if (manifest.role !== role) throw new Error(`Backup role '${manifest.role}' does not match requested role '${role}'.`);

    copyIfExists(join(tempDir, "runtime", ".env"), join(installPath, ".env"));
    copyIfExists(join(tempDir, "runtime", "config"), join(installPath, "config"));

    const postgresDump = join(tempDir, "postgres.sql");
    if (role === "core" && existsSync(postgresDump)) {
      const databaseUser = env.DATABASE_USERNAME || "directus";
      const databaseName = env.DATABASE_NAME || "directus";
      execSync(`docker exec -i cms-database psql -v ON_ERROR_STOP=1 -U ${shellQuote(databaseUser)} ${shellQuote(databaseName)}`, {
        input: readFileSync(postgresDump),
        stdio: ["pipe", "pipe", "pipe"],
      });
    }
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

function restoreStopServices(role: ServerRole): string[] {
  if (role !== "core") return [];
  return resolveServiceSelection("core", { exclude: "cms-database" });
}

async function promptText(question: string, defaultValue = ""): Promise<string> {
  const rl = createPromptInterface({ input: process.stdin, output: process.stderr });
  try {
    const suffix = defaultValue ? ` (${defaultValue})` : "";
    const answer = await rl.question(`${question}${suffix}: `);
    return answer.trim() || defaultValue;
  } finally {
    rl.close();
  }
}

async function promptChoice(question: string, choices: Array<{ value: string; label: string }>, defaultValue: string): Promise<string> {
  console.error(question);
  choices.forEach((choice, index) => {
    const marker = choice.value === defaultValue ? " [default]" : "";
    console.error(`  ${index + 1}. ${choice.label}${marker}`);
  });
  const answer = await promptText("Choose number or value", defaultValue);
  const numeric = Number.parseInt(answer, 10);
  if (Number.isInteger(numeric) && numeric >= 1 && numeric <= choices.length) {
    return choices[numeric - 1].value;
  }
  const direct = choices.find((choice) => choice.value === answer || choice.label.toLowerCase() === answer.toLowerCase());
  return direct?.value ?? answer;
}

async function fetchLocalModelIds(baseUrl: string, apiKey: string): Promise<string[]> {
  const response = await fetch(`${baseUrl.replace(/\/+$/, "")}/models`, {
    headers: { Authorization: `Bearer ${apiKey || "local"}` },
  });
  if (!response.ok) throw new Error(`Failed to fetch local models: HTTP ${response.status}`);
  const body = await response.json() as { data?: Array<{ id?: string }> };
  return (body.data ?? []).map((model) => model.id).filter((id): id is string => Boolean(id));
}

async function testLocalModel(baseUrl: string, apiKey: string, modelId: string): Promise<string> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await fetch(`${baseUrl.replace(/\/+$/, "")}/chat/completions`, {
      method: "POST",
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${apiKey || "local"}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: modelId,
        messages: [
          { role: "system", content: "Answer with only the number." },
          { role: "user", content: "1+2?" },
        ],
        stream: false,
        temperature: 0,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    const body = await response.json() as { choices?: Array<{ message?: { content?: string } }> };
    return body.choices?.[0]?.message?.content?.trim() ?? "";
  } finally {
    clearTimeout(timeout);
  }
}

function upsertLocalModel(path: string, providerId: string, providerName: string, model: Record<string, unknown>): void {
  const overlay = readLocalModelOverlay(path);
  let provider = overlay.providers.find((item) => item.provider_id === providerId);
  if (!provider) {
    provider = {
      provider_id: providerId,
      name: providerName,
      description: `Local self-hosted models for ${providerName}.`,
      models: [],
    };
    overlay.providers.push(provider);
  }
  const modelId = model.id;
  provider.models = provider.models.filter((existing) => existing.id !== modelId);
  provider.models.push(model);
  writeLocalModelOverlay(path, overlay);
}

function removeLocalModel(path: string, fullModelId: string): boolean {
  const [providerId, modelId] = fullModelId.split("/", 2);
  if (!providerId || !modelId) throw new Error("Use provider/model-id format.");
  const overlay = readLocalModelOverlay(path);
  const provider = overlay.providers.find((item) => item.provider_id === providerId);
  if (!provider) return false;
  const before = provider.models.length;
  provider.models = provider.models.filter((model) => model.id !== modelId);
  writeLocalModelOverlay(path, overlay);
  return provider.models.length !== before;
}

function localModelsFromOverlay(overlay: LocalModelOverlay): Array<{ providerId: string; model: Record<string, unknown> }> {
  return overlay.providers.flatMap((provider) => provider.models.map((model) => ({ providerId: provider.provider_id, model })));
}

// ---------------------------------------------------------------------------
// Subcommands
// ---------------------------------------------------------------------------

async function serverStatus(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const role = getServerRole(flags, config);
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config), role), "ps"];

  if (flags.json === true) {
    args.push("--format", "json");
  }
  if (hasServiceFilter(flags)) args.push(...selectedComposeServices(role, flags));

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
  const role = getServerRole(flags, config);
  const installMode = getInstallMode(installPath, config);
  const pullArgs = [...composeArgs(installPath, withOverrides, installMode, role), "pull"];
  const args = [...composeArgs(installPath, withOverrides, installMode, role), "up", "-d"];
  if (hasServiceFilter(flags)) {
    const services = selectedComposeServices(role, flags);
    pullArgs.push(...services);
    args.push(...services);
  }

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
  const role = getServerRole(flags, config);
  const withOverrides = config?.composeProfile === "full";
  const args = hasServiceFilter(flags)
    ? [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config), role), "stop", ...selectedComposeServices(role, flags)]
    : [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config), role), "down"];

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
  const role = getServerRole(flags, config);
  const withOverrides = config?.composeProfile === "full";
  const installMode = getInstallMode(installPath, config);

  if (flags.rebuild === true) {
    if (hasServiceFilter(flags)) {
      throw new Error("--services/--exclude cannot be combined with --rebuild. Use graceful restart for service-scoped restarts.");
    }
    if (installMode === "image") {
      throw new Error(
        "Image-mode installs use prebuilt images and cannot rebuild locally. " +
        "Run 'openmates server update' to pull newer images, or reinstall with --from-source to build from source.",
      );
    }
    // Full rebuild: down → rm cache → build → up
    console.error("Rebuilding OpenMates server (this may take a few minutes)...");
    const downArgs = [...composeArgs(installPath, withOverrides, installMode, role), "down"];
    let code = await runInteractive("docker", downArgs, installPath);
    if (code !== 0) process.exit(code);

    // Remove cache volume (non-fatal if it doesn't exist)
    try {
      exec("docker volume rm openmates-cache-data", installPath);
    } catch {
      // Volume may not exist — that's fine
    }

    const buildArgs = [...composeArgs(installPath, withOverrides, installMode, role), "build"];
    code = await runInteractive("docker", buildArgs, installPath);
    if (code !== 0) process.exit(code);

    const upArgs = [...composeArgs(installPath, withOverrides, installMode, role), "up", "-d"];
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);
  } else {
    // Graceful restart (no rebuild)
    console.error("Restarting OpenMates server...");
    const args = [...composeArgs(installPath, withOverrides, installMode, role), "restart"];
    if (hasServiceFilter(flags)) args.push(...selectedComposeServices(role, flags));
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
  const role = getServerRole(flags, config);
  const withOverrides = config?.composeProfile === "full";
  const args = [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config), role), "logs"];

  if (flags.follow === true || flags.f === true) {
    args.push("--follow");
  }

  const tail = flags.tail;
  if (typeof tail === "string") {
    args.push("--tail", tail);
  } else {
    args.push("--tail", "100");
  }

  if (hasServiceFilter(flags)) {
    args.push(...selectedComposeServices(role, flags));
  } else {
    const container = flags.container;
    if (typeof container === "string") {
      args.push(container);
    }
  }

  const code = await runInteractive("docker", args, installPath);
  if (code !== 0) process.exit(code);
}

async function serverInstall(flags: Record<string, string | boolean>): Promise<void> {
  const installPath = typeof flags.path === "string" ? resolve(flags.path) : DEFAULT_INSTALL_PATH;
  const sourcePath = typeof flags["source-path"] === "string" ? resolve(flags["source-path"]) : null;
  const fromSource = flags["from-source"] === true || sourcePath !== null;
  const role = getServerRole(flags, null);
  const profile = getCoreProfile(flags, null);
  const runtimePlan = planServerRuntime({ role, profile, withAlerts: flags["with-alerts"] === true });

  // Check if already installed
  if (existsSync(join(installPath, SOURCE_COMPOSE_FILE)) || Object.values(ROLE_IMAGE_COMPOSE_FILES).some((composeFile) => existsSync(join(installPath, composeFile)))) {
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
    await writeImageModeRuntimeFiles(installPath, imageTag, role);
    const cliUrls = deriveSelfHostCliUrls(readFileSync(join(installPath, ".env"), "utf-8"));
    try {
      exec("docker network create openmates", installPath);
    } catch {
      // Network already exists.
    }

    saveServerConfig({
      installPath,
      installedAt: Date.now(),
      composeProfile: role === "core" ? "core" : "core",
      serverRole: role,
      serverProfile: profile,
      defaultServices: runtimePlan.defaultServices,
      composeFiles: runtimePlan.composeFiles,
      installMode: "image",
      imageTag,
      ...cliUrls,
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
      console.log(`\nCLI default API: ${cliUrls.apiUrl}`);
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
  const envPath = join(installPath, ".env");
  const cliUrls = deriveSelfHostCliUrls(existsSync(envPath) ? readFileSync(envPath, "utf-8") : "");
  saveServerConfig({
    installPath,
    installedAt: Date.now(),
    composeProfile: "core",
    serverRole: role,
    serverProfile: profile,
    defaultServices: runtimePlan.defaultServices,
    composeFiles: runtimePlan.composeFiles,
    installMode: "source",
    ...cliUrls,
  });

  if (flags.json === true) {
    printJson({ command: "install", status: "success", path: installPath, mode: "source" });
  } else {
    console.log(`\nOpenMates installed at ${installPath}`);
    console.log("\nNext steps:");
    console.log("  1. Run: openmates server start");
    console.log("  2. Open http://localhost:5173");
    console.log("  3. After signup, make yourself admin: openmates server make-admin your@email.com");
    console.log(`\nCLI default API: ${cliUrls.apiUrl}`);
    console.log("\nOptional: edit .env first to add LLM provider API keys. Without keys, the web app and backend still start, but AI model processing is unavailable.");
  }
}

async function installContinuousUpdateService(flags: Record<string, string | boolean>): Promise<void> {
  const config = loadServerConfig();
  const role = getServerRole(flags, config);
  const channel = typeof flags.channel === "string" ? flags.channel : config?.imageChannel ?? "main";
  const window = typeof flags.window === "string" ? flags.window : "02:00-04:00 UTC";
  const plan = planContinuousUpdateService({ role, channel, window });
  const servicePath = join("/etc", "systemd", "system", plan.serviceName);
  const timerPath = join("/etc", "systemd", "system", plan.timerName);

  if (flags["dry-run"] === true || flags.json === true) {
    printJson({ command: "update install-service", status: "planned", role, servicePath, timerPath, unit: plan.unit, timer: plan.timer });
    return;
  }

  try {
    writeFileSync(servicePath, plan.unit, { mode: 0o644 });
    writeFileSync(timerPath, plan.timer, { mode: 0o644 });
    execSync("systemctl daemon-reload", { stdio: "pipe" });
    execSync(`systemctl enable --now ${shellQuote(plan.timerName)}`, { stdio: "pipe" });
  } catch (error) {
    throw new Error(
      `Could not install systemd updater. Run with sudo or use --dry-run to inspect generated units. ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  console.log(`Installed ${plan.timerName}.`);
}

async function serverUpdate(rest: string[], flags: Record<string, string | boolean>): Promise<void> {
  if (rest[0] === "status") {
    const installPath = resolveServerPath(flags);
    const config = loadConfigForInstallPath(installPath);
    const role = getServerRole(flags, config);
    const filePath = updateStatusFile(installPath, role);
    if (flags.json === true) {
      printJson(existsSync(filePath) ? JSON.parse(readFileSync(filePath, "utf-8")) : { role, status: "unknown" });
      return;
    }
    if (!existsSync(filePath)) {
      console.log(`No update status recorded for ${role}.`);
      return;
    }
    console.log(readFileSync(filePath, "utf-8").trim());
    return;
  }

  if (rest[0] === "install-service") {
    if (flags.continuous !== true) throw new Error("Usage: openmates server update install-service --continuous [--channel main|dev|stable]");
    await installContinuousUpdateService(flags);
    return;
  }

  if (flags.continuous === true) {
    const intervalMinutes = typeof flags.interval === "string" ? Number.parseInt(flags.interval, 10) : 30;
    if (!Number.isFinite(intervalMinutes) || intervalMinutes < 5) throw new Error("--interval must be at least 5 minutes.");
    console.error(`Running continuous updater every ${intervalMinutes} minutes. Use Ctrl+C to stop.`);
    while (true) {
      await serverUpdate([], { ...flags, continuous: false });
      await sleep(intervalMinutes * 60_000);
    }
  }

  const installPath = resolveServerPath(flags);
  const dryRun = flags["dry-run"] === true;
  if (!dryRun) ensureGitWorkDirEnv(installPath);

  const config = loadConfigForInstallPath(installPath);
  const role = getServerRole(flags, config);
  const withOverrides = config?.composeProfile === "full";
  const installMode = getInstallMode(installPath, config);
  const filterRequested = hasServiceFilter(flags);
  const selectedServices = filterRequested ? selectedComposeServices(role, flags) : [];
  const missingEnvKeys = missingRequiredEnvKeys(installPath, role);

  if (installMode === "source" && (flags["image-tag"] !== undefined || flags.channel !== undefined)) {
    throw new Error("--image-tag and --channel only apply to image-mode installs. Source-mode installs update from Git.");
  }

  if (!dryRun) requireDocker();

  console.error("Updating OpenMates...");

  if (installMode === "image") {
    const currentTag = getImageTagFromEnv(installPath, config);
    const target = resolveTargetImageTag(flags, currentTag, getPackageVersion());
    const templateRef = templateRefForImageTag(target.tag, getPackageVersion());
    const safetyPlan = planServerUpdate({ role, selectedServices, dryRun, skipBackup: flags["skip-backup"] === true, continuous: false, missingRequiredSecrets: missingEnvKeys });
    const plan = {
      command: "update",
      role,
      path: installPath,
      mode: "image",
      currentImageTag: currentTag || null,
      targetImageTag: target.tag,
      channel: target.channel ?? null,
      templateRef,
      selectedServices: filterRequested ? selectedServices : "all",
      steps: safetyPlan.steps,
      backupName: safetyPlan.backupName,
      missingRequiredEnvKeys: missingEnvKeys,
      blocked: safetyPlan.blocked,
      blockReason: safetyPlan.blockReason,
      dryRun,
    };

    if (dryRun) {
      if (flags.json === true) {
        printJson({ ...plan, status: "planned" });
      } else {
        console.log("Update plan:");
        console.log(`  Mode:          image`);
        console.log(`  Current tag:   ${currentTag || "unknown"}`);
        console.log(`  Target tag:    ${target.tag}`);
        console.log(`  Template ref:  ${templateRef}`);
        console.log(`  Role:          ${role}`);
        console.log(`  Services:      ${filterRequested ? selectedServices.join(", ") : "all"}`);
        console.log(`  Backup:        ${safetyPlan.backupName ?? "none"}`);
        console.log(`  Steps:         ${safetyPlan.steps.join(" -> ")}`);
        console.log(`  Env preflight: ${missingEnvKeys.length ? `missing ${missingEnvKeys.join(", ")}` : "ok"}`);
        console.log("  Commands:      refresh compose, docker compose pull, docker compose up -d, health checks");
      }
      return;
    }

    if (safetyPlan.blocked) throw new Error(safetyPlan.blockReason ?? "Update blocked by preflight.");
    if (missingEnvKeys.length && flags.yes !== true) {
      throw new Error(`Required environment keys are missing: ${missingEnvKeys.join(", ")}. Add them to .env or rerun with --yes after reviewing.`);
    }

    console.error(`Mode: image`);
    console.error(`Current image tag: ${currentTag || "unknown"}`);
    console.error(`Target image tag: ${target.tag}`);
    writeUpdateStatus(installPath, role, { status: "in_progress", targetImageTag: target.tag, step: "backup" });
    if (safetyPlan.backupName) {
      console.error(`Creating rotating pre-update backup: ${safetyPlan.backupName}`);
      createServerBackup(installPath, role, { preUpdate: true });
    } else {
      console.error("Skipping pre-update backup for this role or because --skip-backup was passed.");
    }
    console.error(`Refreshing self-host runtime files from ${templateRef}...`);
    await writeImageModeRuntimeFiles(installPath, target.tag, role);

    const pullArgs = [...composeArgs(installPath, withOverrides, installMode, role), "pull"];
    if (filterRequested) pullArgs.push(...selectedServices);
    let code = 0;
    if (shouldPullImages()) {
      writeUpdateStatus(installPath, role, { status: "in_progress", targetImageTag: target.tag, step: "pull" });
      console.error("Pulling prebuilt images...");
      code = await runInteractive("docker", pullArgs, installPath);
      if (code !== 0) process.exit(code);
    } else {
      console.error("Skipping image pull because OPENMATES_SKIP_IMAGE_PULL=1.");
    }

    writeUpdateStatus(installPath, role, { status: "in_progress", targetImageTag: target.tag, step: "up" });
    const upArgs = [...composeArgs(installPath, withOverrides, installMode, role), "up", "-d"];
    if (filterRequested) upArgs.push(...selectedServices);
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);

    console.error("Waiting for role health checks...");
    try {
      writeUpdateStatus(installPath, role, { status: "in_progress", targetImageTag: target.tag, step: "health-check" });
      await waitForServerHealth(installPath, role);
    } catch (error) {
      await runInteractive("docker", [...composeArgs(installPath, withOverrides, installMode, role), "ps"], installPath);
      throw error;
    }

    if (config) {
      saveServerConfig({ ...config, imageTag: target.tag, imageChannel: target.channel });
    }
    writeUpdateStatus(installPath, role, { status: "success", targetImageTag: target.tag, step: "complete" });

    if (flags.json === true) {
      printJson({ ...plan, status: "success", dryRun: false });
    } else {
      console.log("Server images updated, containers restarted, and health checks passed.");
    }
    return;
  }

  if (dryRun) {
    if (flags.json === true) {
      printJson({ command: "update", status: "planned", path: installPath, mode: "source", dryRun: true });
    } else {
      console.log("Update plan:");
      console.log("  Mode:     source");
      console.log("  Commands: git pull --ff-only, docker compose build, docker compose up -d, health checks");
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
  } catch {
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
  const buildArgs = [...composeArgs(installPath, withOverrides, installMode, role), "build"];
  console.error("Rebuilding containers...");
  let code = await runInteractive("docker", buildArgs, installPath);
  if (code !== 0) process.exit(code);

  const upArgs = [...composeArgs(installPath, withOverrides, installMode, role), "up", "-d"];
  code = await runInteractive("docker", upArgs, installPath);
  if (code !== 0) process.exit(code);

  console.error("Waiting for API and web health checks...");
  try {
    await waitForServerHealth(installPath, role);
  } catch (error) {
    await runInteractive("docker", [...composeArgs(installPath, withOverrides, installMode, role), "ps"], installPath);
    throw error;
  }

  if (flags.json === true) {
    printJson({ command: "update", status: "success", path: installPath, mode: "source" });
  } else {
    console.log("Server updated, restarted, and health checks passed.");
  }
}

async function serverReset(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const role = getServerRole(flags, config);
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
    const downArgs = [...composeArgs(installPath, withOverrides, installMode, role), "down"];
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
      const buildArgs = [...composeArgs(installPath, withOverrides, installMode, role), "build"];
      code = await runInteractive("docker", buildArgs, installPath);
      if (code !== 0) process.exit(code);
    }

    const upArgs = [...composeArgs(installPath, withOverrides, installMode, role), "up", "-d"];
    code = await runInteractive("docker", upArgs, installPath);
    if (code !== 0) process.exit(code);
  } else {
    // Full reset: remove everything
    const args = [...composeArgs(installPath, withOverrides, installMode, role), "down", "-v"];
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

async function serverFeatures(rest: string[], flags: Record<string, string | boolean>): Promise<void> {
  const action = rest[0] ?? "list";
  const featureId = rest[1];
  const installPath = resolveServerPath(flags);
  const installMode = getInstallMode(installPath);
  if (installMode === "image") ensureImageRuntimeConfig(installPath);
  const configPath = installMode === "image" ? imageBackendConfigPath(installPath) : join(installPath, BACKEND_CONFIG_FILE);
  if (!existsSync(configPath)) {
    throw new Error(`Backend config not found at ${configPath}. Run 'openmates server install' first or pass --path <dir>.`);
  }

  const content = readFileSync(configPath, "utf-8");
  const overrides = parseFeatureOverrides(content);
  const writeOverrides = (nextOverrides: FeatureOverrides) => {
    writeFileSync(configPath, updateFeatureOverridesContent(content, nextOverrides));
    console.log(`Updated ${configPath}`);
    console.log("Restart the server for feature changes to take effect: openmates server restart");
  };

  if (action === "list") {
    console.log("Feature overrides:");
    console.log(`  enabled: ${overrides.enabled.length ? overrides.enabled.join(", ") : "none"}`);
    console.log(`  disabled: ${overrides.disabled.length ? overrides.disabled.join(", ") : "none"}`);
    console.log("\nKnown off-by-default features:");
    for (const [id, reason] of OFF_BY_DEFAULT_FEATURES.entries()) {
      const override = overrides.enabled.includes(id) ? "enabled override" : overrides.disabled.includes(id) ? "disabled override" : "default off";
      console.log(`  ${id} (${featureKind(id)}): ${override} - ${reason}`);
    }
    return;
  }

  if (!featureId) {
    throw new Error(`Usage: openmates server features ${action} <feature-id>`);
  }

  if (action === "enable") {
    writeOverrides({
      enabled: normalizeFeatureList([...overrides.enabled, featureId]),
      disabled: overrides.disabled.filter((id) => id !== featureId),
    });
    return;
  }

  if (action === "disable") {
    writeOverrides({
      enabled: overrides.enabled.filter((id) => id !== featureId),
      disabled: normalizeFeatureList([...overrides.disabled, featureId]),
    });
    return;
  }

  if (action === "reset") {
    writeOverrides({
      enabled: overrides.enabled.filter((id) => id !== featureId),
      disabled: overrides.disabled.filter((id) => id !== featureId),
    });
    return;
  }

  if (action === "explain") {
    const defaultReason = OFF_BY_DEFAULT_FEATURES.get(featureId);
    const override = overrides.enabled.includes(featureId) ? "enabled" : overrides.disabled.includes(featureId) ? "disabled" : "none";
    const defaultState = defaultReason ? "off" : "on";
    const effective = override === "enabled" ? "enabled" : override === "disabled" ? "disabled" : defaultState === "on" ? "enabled" : "disabled";
    console.log(`Feature: ${featureId}`);
    console.log(`Kind: ${featureKind(featureId)}`);
    console.log(`Default: ${defaultState}${defaultReason ? ` (${defaultReason})` : ""}`);
    console.log(`Override: ${override}`);
    console.log(`Effective after restart: ${effective}`);
    return;
  }

  throw new Error(`Unknown server features command '${action}'. Use list, enable, disable, reset, or explain.`);
}

async function serverAiModelsAdd(flags: Record<string, string | boolean>): Promise<void> {
  const installPath = resolveServerPath(flags);
  const installMode = getInstallMode(installPath);
  const overlayPath = localModelsOverlayPath(installPath, installMode);

  const runtimeInput = typeof flags.runtime === "string"
    ? flags.runtime
    : await promptChoice(
        "Which local runtime should OpenMates use?",
        [
          { value: "ollama", label: "Ollama" },
          { value: "lm-studio", label: "LM Studio" },
          { value: "custom", label: "Custom OpenAI-compatible API" },
        ],
        "ollama",
      );
  const runtimeKey = normalizeRuntimeKey(runtimeInput);
  const runtime = LOCAL_MODEL_RUNTIME_DEFAULTS[runtimeKey];
  const baseUrl = typeof flags["base-url"] === "string"
    ? flags["base-url"]
    : await promptText("OpenAI-compatible base URL", runtime.baseUrl);
  const apiKey = typeof flags["api-key"] === "string"
    ? flags["api-key"]
    : runtimeKey === "custom"
      ? await promptText("API key", runtime.apiKey)
      : runtime.apiKey;

  let availableModels: string[] = [];
  try {
    availableModels = await fetchLocalModelIds(baseUrl, apiKey);
  } catch (error) {
    console.error(`Could not fetch /v1/models: ${error instanceof Error ? error.message : String(error)}`);
  }

  const rawModelId = typeof flags.model === "string"
    ? flags.model
    : availableModels.length
      ? await promptChoice(
          "Which installed model should OpenMates add?",
          [...availableModels.map((id) => ({ value: id, label: id })), { value: "manual", label: "Enter manually" }],
          availableModels[0],
        )
      : await promptText("Local model ID");
  const serverModelId = rawModelId === "manual" ? await promptText("Local model ID") : rawModelId;
  if (!serverModelId) throw new Error("Model ID is required.");

  const inferredCreator = inferCreatorId(serverModelId);
  const creatorInput = typeof flags.creator === "string"
    ? flags.creator
    : await promptChoice(
        "Who created the model?",
        MODEL_CREATOR_OPTIONS.map((option) => ({ value: option.id, label: option.name })),
        inferredCreator,
      );
  const providerId = creatorInput === "custom"
    ? normalizeCreatorId(await promptText("Custom creator/provider ID", "custom_local"))
    : normalizeCreatorId(creatorInput);
  const providerName = providerId === creatorInput ? creatorDisplayName(providerId) : providerId;
  const internalModelId = typeof flags.id === "string" ? sanitizeModelId(flags.id) : `${sanitizeModelId(serverModelId)}-local`;
  const displayName = typeof flags.name === "string" ? flags.name : await promptText("Display name", serverModelId);
  const supportsImages = boolFromFlag(flags.images ?? flags.image ?? flags.vision, false);
  const supportsTools = boolFromFlag(flags.tools ?? flags["tool-use"], false);
  const contextWindowInput = typeof flags["context-window"] === "string"
    ? flags["context-window"]
    : await promptText("Context window tokens", "32768");
  const contextWindow = Number.parseInt(contextWindowInput, 10) || 32768;

  if (flags["skip-test"] !== true) {
    console.error(`Testing ${runtime.label} model '${serverModelId}'...`);
    const testOutput = await testLocalModel(baseUrl, apiKey, serverModelId);
    if (!testOutput) throw new Error("Local model test returned no content. Not saving model.");
    console.error(`Test response: ${testOutput}`);
  }

  const model = {
    id: internalModelId,
    name: displayName,
    description: `${displayName} served locally through ${runtime.label}.`,
    country_origin: "local",
    for_app_skill: "ai.ask",
    allow_auto_select: false,
    local: true,
    self_hosted: true,
    input_types: supportsImages ? ["text", "image"] : ["text"],
    output_types: ["text"],
    default_server: runtime.serverId,
    servers: [
      {
        id: runtime.serverId,
        name: runtime.label,
        model_id: serverModelId,
        region: "local",
        base_url: baseUrl.replace(/\/+$/, ""),
        api_key: apiKey,
        supports_tools: supportsTools,
      },
    ],
    pricing: { fixed: { credits: 0 } },
    costs: {
      input_per_million_token: { price: 0, currency: "USD", max_context: contextWindow },
      output_per_million_token: { price: 0, currency: "USD", max_context: contextWindow },
    },
    features: {
      streaming: true,
      tool_use: supportsTools,
      max_context: contextWindow,
    },
  };

  upsertLocalModel(overlayPath, providerId, providerName, model);
  if (installMode === "image") ensureImageRuntimeConfig(installPath);

  if (flags.json === true) {
    printJson({ command: "server ai models add", status: "success", model: `${providerId}/${internalModelId}`, overlayPath });
  } else {
    console.log(`Added local model: ${providerId}/${internalModelId}`);
    console.log(`Updated ${overlayPath}`);
    console.log("Restart the server for model changes to take effect: openmates server restart");
    console.log("Self-hosted local models charge 0 credits; token usage may still be recorded in usage history.");
  }
}

async function serverAiModelsList(flags: Record<string, string | boolean>): Promise<void> {
  const installPath = resolveServerPath(flags);
  const overlayPath = localModelsOverlayPath(installPath);
  const overlay = readLocalModelOverlay(overlayPath);
  const models = localModelsFromOverlay(overlay).map(({ providerId, model }) => ({
    id: `${providerId}/${String(model.id ?? "")}`,
    name: model.name ?? model.id,
    server: Array.isArray(model.servers) ? (model.servers[0] as Record<string, unknown> | undefined)?.id : undefined,
    serverModelId: Array.isArray(model.servers) ? (model.servers[0] as Record<string, unknown> | undefined)?.model_id : undefined,
  }));
  if (flags.json === true) {
    printJson({ overlayPath, models });
    return;
  }
  if (!models.length) {
    console.log("No local AI models configured. Add one with: openmates server ai models add");
    return;
  }
  console.log("Local AI models:");
  for (const model of models) {
    console.log(`  ${model.id} (${model.server}: ${model.serverModelId})`);
  }
}

async function serverAiModelsTest(rest: string[], flags: Record<string, string | boolean>): Promise<void> {
  const installPath = resolveServerPath(flags);
  const overlayPath = localModelsOverlayPath(installPath);
  const fullModelId = rest[0];
  if (!fullModelId || !fullModelId.includes("/")) throw new Error("Usage: openmates server ai models test <provider/model-id>");
  const [providerId, modelId] = fullModelId.split("/", 2);
  const overlay = readLocalModelOverlay(overlayPath);
  const provider = overlay.providers.find((item) => item.provider_id === providerId);
  const model = provider?.models.find((item) => item.id === modelId);
  const server = Array.isArray(model?.servers) ? model.servers[0] as Record<string, unknown> | undefined : undefined;
  if (!server) throw new Error(`Local model not found in ${overlayPath}: ${fullModelId}`);
  const baseUrl = String(server.base_url ?? "");
  const apiKey = String(server.api_key ?? "local");
  const serverModelId = String(server.model_id ?? "");
  const output = await testLocalModel(baseUrl, apiKey, serverModelId);
  if (flags.json === true) {
    printJson({ model: fullModelId, status: "success", output });
  } else {
    console.log(`Model test succeeded: ${fullModelId}`);
    console.log(`Response: ${output}`);
  }
}

async function serverAiModelsRemove(rest: string[], flags: Record<string, string | boolean>): Promise<void> {
  const installPath = resolveServerPath(flags);
  const overlayPath = localModelsOverlayPath(installPath);
  const fullModelId = rest[0];
  if (!fullModelId) throw new Error("Usage: openmates server ai models remove <provider/model-id>");
  const removed = removeLocalModel(overlayPath, fullModelId);
  if (flags.json === true) {
    printJson({ command: "server ai models remove", status: removed ? "success" : "not_found", model: fullModelId });
  } else if (removed) {
    console.log(`Removed local model: ${fullModelId}`);
    console.log("Restart the server for model changes to take effect: openmates server restart");
  } else {
    console.log(`Local model not found: ${fullModelId}`);
  }
}

async function serverAi(rest: string[], flags: Record<string, string | boolean>): Promise<void> {
  const area = rest[0];
  const action = rest[1] ?? "list";
  const args = rest.slice(2);
  if (area !== "models") throw new Error("Usage: openmates server ai models <add|list|test|remove>");
  switch (action) {
    case "add":    return serverAiModelsAdd(flags);
    case "list":   return serverAiModelsList(flags);
    case "test":   return serverAiModelsTest(args, flags);
    case "remove": return serverAiModelsRemove(args, flags);
    default:
      throw new Error(`Unknown server ai models command '${action}'. Use add, list, test, or remove.`);
  }
}

async function serverBackup(rest: string[], flags: Record<string, string | boolean>): Promise<void> {
  const action = rest[0];
  const installPath = resolveServerPath(flags);
  const config = loadConfigForInstallPath(installPath);
  const role = getServerRole(flags, config);

  if (action === "list") {
    const dir = roleBackupDir(installPath, role);
    const files = existsSync(dir) ? readdirSync(dir).filter((item) => item.endsWith(".tar.gz")).sort() : [];
    if (flags.json === true) {
      printJson({ role, backupDir: dir, files });
      return;
    }
    console.log(`Backups for ${role}:`);
    if (!files.length) {
      console.log("  none");
      return;
    }
    for (const file of files) console.log(`  ${join(dir, file)}`);
    return;
  }

  requireDocker();
  const output = typeof flags.output === "string" ? flags.output : undefined;
  const archivePath = createServerBackup(installPath, role, {
    output,
    includeObservability: flags["include-observability"] === true,
  });

  if (flags.json === true) {
    printJson({ command: "backup", status: "success", role, file: archivePath });
  } else {
    console.log(`Backup created: ${archivePath}`);
  }
}

async function serverRestore(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  const config = loadConfigForInstallPath(installPath);
  const role = getServerRole(flags, config);
  const file = typeof flags.file === "string" ? flags.file : "";
  if (!file) throw new Error("Usage: openmates server restore --file <backup.tar.gz> [--role core|upload|preview] [--yes]");
  const restorePlan = planRestore({ role, file, yes: flags.yes === true });

  if (restorePlan.requiresConfirmation) {
    console.error(`\nWARNING: This will restore ${role} data from ${file}.`);
    const confirmed = await confirmDestructive("RESTORE OPENMATES BACKUP");
    if (!confirmed) {
      console.error("Restore cancelled.");
      return;
    }
  }

  const withOverrides = config?.composeProfile === "full";
  const installMode = getInstallMode(installPath, config);
  const stopArgs = [...composeArgs(installPath, withOverrides, installMode, role), "stop", ...restoreStopServices(role)];
  let code = await runInteractive("docker", stopArgs, installPath);
  if (code !== 0) process.exit(code);
  restoreServerBackup(installPath, role, file);
  code = await runInteractive("docker", [...composeArgs(installPath, withOverrides, installMode, role), "up", "-d"], installPath);
  if (code !== 0) process.exit(code);
  await waitForServerHealth(installPath, role);

  if (flags.json === true) {
    printJson({ command: "restore", status: "success", role, file });
  } else {
    console.log(`Restore completed for ${role}.`);
  }
}

async function serverUninstall(flags: Record<string, string | boolean>): Promise<void> {
  requireDocker();
  const installPath = resolveServerPath(flags);
  ensureGitWorkDirEnv(installPath);
  const config = loadConfigForInstallPath(installPath);
  const role = getServerRole(flags, config);
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
  const downArgs = [...composeArgs(installPath, withOverrides, getInstallMode(installPath, config), role), "down", "--rmi", "local"];
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

async function serverPreflight(flags: Record<string, string | boolean>): Promise<void> {
  const installPath = resolveServerPath(flags);
  const config = loadConfigForInstallPath(installPath);
  const role = getServerRole(flags, config);
  const services = hasServiceFilter(flags) ? selectedComposeServices(role, flags) : [];
  const updatePlan = planServerUpdate({ role, selectedServices: services, dryRun: true });
  const missingEnvKeys = missingRequiredEnvKeys(installPath, role);
  const runtimePlan = planServerRuntime({
    role,
    profile: getCoreProfile(flags, config),
    withAlerts: flags["with-alerts"] === true,
  });
  const caddyPlan = planCaddyCommand({ role, action: "status" });
  const preflight = {
    command: "preflight",
    status: updatePlan.blocked ? "blocked" : "ok",
    path: installPath,
    role,
    profile: runtimePlan.profile,
    services: hasServiceFilter(flags) ? services : "all",
    healthChecks: runtimePlan.healthChecks,
    updateSteps: updatePlan.steps,
    backupName: updatePlan.backupName,
    missingRequiredEnvKeys: missingEnvKeys,
    caddy: caddyPlan,
  };

  if (flags.json === true) {
    printJson(preflight);
    return;
  }

  console.log("Server preflight plan:");
  console.log(`  Role:          ${role}`);
  console.log(`  Profile:       ${runtimePlan.profile ?? "n/a"}`);
  console.log(`  Services:      ${hasServiceFilter(flags) ? services.join(", ") : "all"}`);
  console.log(`  Backup:        ${updatePlan.backupName ?? "none"}`);
  console.log(`  Env preflight: ${missingEnvKeys.length ? `missing ${missingEnvKeys.join(", ")}` : "ok"}`);
  console.log(`  Health checks: ${runtimePlan.healthChecks.join(", ")}`);
  console.log(`  Caddy steps:   ${caddyPlan.steps.join(" -> ")}`);
}

async function serverCaddy(rest: string[], flags: Record<string, string | boolean>): Promise<void> {
  const action = (rest[0] ?? "status") as CaddyAction;
  if (!["check", "status", "diff", "apply"].includes(action)) {
    throw new Error("Usage: openmates server caddy check|status|diff|apply [--role core|upload|preview]");
  }
  const config = loadServerConfig();
  const role = getServerRole(flags, config);
  const appliedPath = typeof flags.config === "string" ? flags.config : "/etc/caddy/Caddyfile";
  const templatePath = packagedCaddyTemplatePath(role);
  if (!existsSync(templatePath)) throw new Error(`Packaged Caddy template not found: ${templatePath}`);
  const plan = planCaddyCommand({ role, action, appliedPath });
  const payload = {
    ...plan,
    templatePath,
    templateHash: fileHash(templatePath),
    appliedHash: fileHash(appliedPath),
    drift: fileHash(templatePath) !== fileHash(appliedPath),
  };

  if (flags.json === true) {
    printJson(payload);
    return;
  }

  if (action === "check") {
    execSync(`caddy validate --config ${shellQuote(templatePath)}`, { stdio: "inherit" });
    console.log(`Caddy template is valid for ${role}.`);
    return;
  }

  if (action === "diff") {
    if (!existsSync(appliedPath)) throw new Error(`Applied Caddyfile not found: ${appliedPath}`);
    try {
      execSync(`diff -u ${shellQuote(appliedPath)} ${shellQuote(templatePath)}`, { stdio: "inherit" });
    } catch (error) {
      const status = typeof error === "object" && error !== null && "status" in error ? (error as { status?: number }).status : undefined;
      if (status !== 1) throw error;
    }
    return;
  }

  if (action === "apply") {
    execSync(`caddy validate --config ${shellQuote(templatePath)}`, { stdio: "inherit" });
    if (flags.yes !== true) {
      console.error(`\nWARNING: This will replace ${appliedPath} with the packaged ${role} Caddyfile.`);
      const confirmed = await confirmDestructive("APPLY CADDYFILE");
      if (!confirmed) {
        console.error("Caddy apply cancelled.");
        return;
      }
    }
    const backupPath = `${appliedPath}.openmates-backup-${nowStamp()}`;
    try {
      if (existsSync(appliedPath)) copyFileSync(appliedPath, backupPath);
      copyFileSync(templatePath, appliedPath);
      execSync("systemctl reload caddy", { stdio: "inherit" });
    } catch (error) {
      throw new Error(`Could not apply Caddyfile. Run with sudo or use --config <writable path>. ${error instanceof Error ? error.message : String(error)}`);
    }
    console.log(`Applied Caddyfile for ${role}. Backup: ${backupPath}`);
    return;
  }

  console.log(`Caddy ${action} plan:`);
  console.log(`  Role:          ${payload.role}`);
  console.log(`  Template:      ${payload.templatePath}`);
  console.log(`  Applied:       ${payload.appliedPath}`);
  console.log(`  Template hash: ${payload.templateHash ?? "missing"}`);
  console.log(`  Applied hash:  ${payload.appliedHash ?? "missing"}`);
  console.log(`  Drift:         ${payload.drift ? "yes" : "no"}`);
  console.log(`  Steps:         ${payload.steps.join(" -> ")}`);
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
  preflight       Show role/update/Caddy preflight plan
  caddy           Plan host-level Caddyfile check/status/diff/apply operations
  backup          Create or list backups
  restore         Restore a backup archive
  make-admin      Grant admin privileges to a user
  ai              Manage self-hosted local AI models
  reset           Reset server data (requires confirmation)
  uninstall       Completely remove OpenMates (requires confirmation)

Global Options:
  --path <dir>    Override the server installation directory
  --json          Output machine-readable JSON
  --role <role>   Server role: core, upload, or preview (default: core)
  --help          Show this help message

Command Options:
  install:
    --path <dir>        Install directory (default: ~/openmates)
    --env-path <file>   Copy a pre-existing .env file during install
    --profile <name>    Core profile: minimal, standard, or production
    --with-alerts       Include alertmanager in production profile planning
    --image-tag <tag>   Prebuilt image tag (default: CLI version tag)
    --from-source       Clone/build from source instead of using prebuilt GHCR images
    --source-path <dir> Clone from a local checkout instead of GitHub (implies --from-source)

  start:
    --with-overrides    Include admin UIs (Directus CMS, Grafana)
    --services <csv>    Start only selected role services
    --exclude <csv>     Start all role services except selected services

  restart:
    --rebuild           Full rebuild (down + build + up) instead of graceful restart
    --services <csv>    Restart only selected role services
    --exclude <csv>     Restart all role services except selected services

  logs:
    --container <name>  Filter logs to a specific service (e.g. api, cms)
    --services <csv>    Filter logs to selected role services
    --exclude <csv>     Filter logs to all role services except selected services
    --follow, -f        Stream logs in real time
    --tail <n>          Number of lines to show (default: 100)

  update:
    --dry-run           Show update plan without changing files or containers
    --services <csv>    Update only selected role services
    --exclude <csv>     Update all role services except selected services
    --image-tag <tag>   Image mode: update to a specific prebuilt image tag
    --channel <name>    Image mode: update using stable/main or dev channel tags
    --continuous        Run continuously in foreground, or use with install-service
    --interval <min>    Foreground continuous update interval (default: 30)
    install-service --continuous --channel <name> --window <window>
    --force             Source mode: stash local changes before pulling

  backup:
    openmates server backup [--role core|upload|preview] [--output <file>] [--include-observability]
    openmates server backup list [--role core|upload|preview]

  restore:
    openmates server restore --file <backup.tar.gz> [--role core|upload|preview] [--yes]

  caddy:
    openmates server caddy check|status|diff|apply [--role core|upload|preview] [--config /etc/caddy/Caddyfile]

  reset:
    --delete-user-data-only   Only delete database and cache (preserve config)
    --yes                     Skip confirmation prompt

  uninstall:
    --keep-data         Preserve Docker volumes (data can be restored later)
    --yes               Skip confirmation prompt

  make-admin:
    openmates server make-admin <email>

  features:
    openmates server features list
    openmates server features enable <feature-id>
    openmates server features disable <feature-id>
    openmates server features reset <feature-id>
    openmates server features explain <feature-id>

  ai models:
    openmates server ai models add
    openmates server ai models list
    openmates server ai models test <provider/model-id>
    openmates server ai models remove <provider/model-id>

Examples:
  openmates server install
  openmates server start --with-overrides
  openmates server logs --container api --follow
  openmates server make-admin user@example.com
  openmates server features disable app:videos
  openmates server ai models add
  openmates server features enable embed:code:application
  openmates server update
  openmates server update --dry-run
  openmates server update --image-tag v0.12.0-alpha.1
  openmates server update --channel dev
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
    case "update":     return serverUpdate(rest, flags);
    case "preflight":  return serverPreflight(flags);
    case "caddy":      return serverCaddy(rest, flags);
    case "backup":     return serverBackup(rest, flags);
    case "restore":    return serverRestore(flags);
    case "reset":      return serverReset(flags);
    case "make-admin": return serverMakeAdmin(rest, flags);
    case "ai":         return serverAi(rest, flags);
    case "features":   return serverFeatures(rest, flags);
    case "uninstall":  return serverUninstall(flags);
    default:
      throw new Error(`Unknown server command '${subcommand}'. Run 'openmates server --help'.`);
  }
}
