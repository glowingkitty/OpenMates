/*
 * OpenMates CLI server planning helpers.
 *
 * Purpose: resolve server roles, service filters, update phases, backup scope,
 *          and host-level Caddy/preflight plans before shelling out to Docker.
 * Architecture: pure functions shared by CLI commands and unit tests.
 * Tests: frontend/packages/openmates-cli/tests/server.test.ts
 */

import { dirname, join, resolve } from "node:path";

export type ServerRole = "core" | "upload" | "preview";
export type CoreProfile = "minimal" | "standard" | "production";
export type CaddyAction = "check" | "status" | "diff" | "apply";
export type ServerDeploymentMode = "self_host" | "official_cloud";
export type ServerInstallMode = "image" | "source";

export type ServiceFilter = {
  services?: string | string[];
  exclude?: string | string[];
};

type RoleDefinition = {
  dataBearing: boolean;
  requiredServices: string[];
  optionalServices: string[];
  healthChecks: string[];
  templatePath: string;
  composeFile: string;
};

export type RuntimePlan = {
  role: ServerRole;
  profile: CoreProfile | null;
  dataBearing: boolean;
  composeFiles: string[];
  requiredServices: string[];
  profileServices: string[];
  defaultServices: string[];
  healthChecks: string[];
};

export type OpenMatesCloudOverlayPlan = {
  deploymentMode: ServerDeploymentMode;
  enabled: boolean;
  overlayPath: string | null;
  composeFiles: string[];
  env: Record<string, string>;
  modeLabel: string;
};

export type OpenMatesCloudOverlayInput = {
  deploymentMode?: ServerDeploymentMode;
  openMatesPath: string;
  overlayPath?: string;
  overlayComposeFile?: string;
  overlayExists?: boolean;
};

export type DockerComposeArgsInput = {
  openMatesPath: string;
  installMode: ServerInstallMode;
  role?: ServerRole | string;
  withOverrides?: boolean;
  overrideExists?: boolean;
  deploymentMode?: ServerDeploymentMode;
  overlayPath?: string;
  overlayComposeFile?: string;
  overlayExists?: boolean;
};

export type UpdatePlan = {
  role: ServerRole;
  selectedServices: string[];
  steps: string[];
  commands: string[];
  backupName: string | null;
  blocked: boolean;
  blockReason: string | null;
};

export type BackupPlan = {
  role: ServerRole;
  contents: string[];
  fileMode: number;
};

export type RestorePlan = {
  role: ServerRole;
  file: string;
  requiresConfirmation: boolean;
  steps: string[];
};

export type TemplateSource =
  | { type: "packaged"; path: string }
  | { type: "url"; url: string }
  | { type: "github-raw"; ref: string; path: string };

export type SecretRequirement = {
  id: string;
  envKey: string;
  required: boolean;
  noApiKey?: boolean;
};

export type ParsedSecretEnvKey = {
  envKey: string;
  vaultPath: string;
  vaultKey: string;
};

export type VaultSecretPresence = "present" | "missing" | "unavailable";

export type SecretPreflightSummary = {
  inlineSecretEnvKeys: string[];
  importedSecretEnvKeys: string[];
  emptySecretEnvKeys: string[];
  importedVaultPresent: string[];
  importedVaultMissing: string[];
  importedVaultUnavailable: string[];
};

export type EnvEntry = {
  key: string;
  value: string;
  category: EnvCategory;
  secret: boolean;
  redactedValue: string;
};

export type EnvCategory = "runtime" | "providers" | "integrations" | "observability" | "advanced";

export type CaddyPlan = {
  role: ServerRole;
  action: CaddyAction;
  templatePath: string;
  appliedPath: string;
  steps: string[];
};

export type ContinuousUpdateServicePlan = {
  role: ServerRole;
  serviceName: string;
  timerName: string;
  unit: string;
  timer: string;
};

export type RuntimeCheckDefinition = {
  id: string;
  required: boolean;
  timeoutSeconds: number;
};

export type RuntimeDeploymentModeResult = {
  effectiveMode: ServerDeploymentMode;
  status: "valid" | "missing" | "malformed" | "conflicting" | "unavailable";
  reason: string;
  billingEnabled: boolean;
};

export type RuntimeMonitoringServicePlan = {
  role: ServerRole;
  serviceName: string;
  timerName: string;
  unit: string;
  timer: string;
  watchdogServiceName?: string;
  watchdogTimerName?: string;
  watchdogUnit?: string;
  watchdogTimer?: string;
};

const CORE_WORKER_SERVICES = [
  "task-worker",
  "user-init-worker",
  "core-worker",
  "user-tasks-worker",
  "reminder-worker",
  "workflow-worker",
  "task-scheduler",
  "app-ai-worker",
  "app-images-worker",
  "app-music-worker",
  "app-videos-worker",
  "app-pdf-worker",
  "app-docs-worker",
  "app-code-worker",
  "app-social-media-worker",
];
const OPENMATESCLOUD_OVERLAY_DIR = "OpenMatesCloud";
const OPENMATESCLOUD_COMPOSE_FILE = "docker-compose.openmatescloud.yml";
export const OFFICIAL_CLOUD_NO_WEBAPP_COMPOSE_FILE = "backend/core/docker-compose.no-webapp.yml";
const SOURCE_COMPOSE_FILES: Record<ServerRole, string> = {
  core: "backend/core/docker-compose.yml",
  upload: "backend/upload/docker-compose.yml",
  preview: "backend/preview/docker-compose.preview.yml",
};
const COMPOSE_OVERRIDE = "backend/core/docker-compose.override.yml";

const CORE_OBSERVABILITY_BY_PROFILE: Record<CoreProfile, string[]> = {
  minimal: [],
  standard: ["openobserve", "promtail"],
  production: ["openobserve", "promtail", "prometheus", "cadvisor", "node-exporter"],
};

const ROLE_DEFINITIONS: Record<ServerRole, RoleDefinition> = {
  core: {
    dataBearing: true,
    requiredServices: ["api", "cms", "cms-database", "cache", "vault", "vault-setup", "cms-setup"],
    optionalServices: [...CORE_WORKER_SERVICES, "admin-sidecar", "webapp", "openobserve", "promtail", "prometheus", "cadvisor", "node-exporter", "alertmanager"],
    healthChecks: ["http://localhost:8000/health"],
    templatePath: "templates/core/docker-compose.selfhost.yml",
    composeFile: "backend/core/docker-compose.selfhost.yml",
  },
  upload: {
    dataBearing: true,
    requiredServices: ["app-uploads", "clamav", "vault", "vault-setup", "admin-sidecar"],
    optionalServices: [],
    healthChecks: ["http://localhost:8000/health"],
    templatePath: "templates/upload/docker-compose.yml",
    composeFile: "backend/upload/docker-compose.yml",
  },
  preview: {
    dataBearing: false,
    requiredServices: ["preview", "admin-sidecar"],
    optionalServices: ["cache"],
    healthChecks: ["http://localhost:8080/health"],
    templatePath: "templates/preview/docker-compose.preview.yml",
    composeFile: "backend/preview/docker-compose.preview.yml",
  },
};

const OBSERVABILITY_ENV_PREFIXES = ["OPENOBSERVE_", "DISCORD_WEBHOOK_"];
const ADVANCED_ENV_KEYS = new Set([
  "GIT_WORK_DIR",
  "DOCKER_GID",
  "TUNNEL_TRIGGER_SECRET",
  "CELERY_AUTOSCALE_MAX",
  "CELERY_AUTOSCALE_MIN",
  "TASK_WORKER_CONCURRENCY",
  "USER_INIT_WORKER_CONCURRENCY",
  "APP_AI_WORKER_CONCURRENCY",
  "APP_IMAGES_WORKER_CONCURRENCY",
  "APP_MUSIC_WORKER_CONCURRENCY",
  "TASK_WORKER_MEMORY_LIMIT",
  "USER_INIT_WORKER_MEMORY_LIMIT",
  "APP_AI_WORKER_MEMORY_LIMIT",
  "APP_IMAGES_WORKER_MEMORY_LIMIT",
  "APP_MUSIC_WORKER_MEMORY_LIMIT",
  "APP_VIDEOS_WORKER_MEMORY_LIMIT",
  "APP_PDF_WORKER_MEMORY_LIMIT",
  "APP_DOCS_WORKER_MEMORY_LIMIT",
  "APP_CODE_WORKER_MEMORY_LIMIT",
  "APP_SOCIAL_MEDIA_WORKER_MEMORY_LIMIT",
  "AI_FIRST_CHUNK_TIMEOUT_SECONDS",
  "AI_REASONING_FIRST_CHUNK_TIMEOUT_SECONDS",
]);
const INTEGRATION_SECRET_PREFIXES = [
  "SECRET__GOOGLE__OAUTH_",
  "SECRET__PROTONMAIL__",
  "SECRET__ADMIN_DEBUG_CLI__",
  "SECRET__UPLOAD_SERVER__",
  "SECRET__PREVIEW_SERVER__",
  "SECRET__STRIPE__",
  "SECRET__REVOLUT_BUSINESS__",
  "SECRET__INVOICE_",
];
const CELERY_PROBE_CHECK_TIMEOUT_SECONDS = 15;

const RUNTIME_CHECKS: Record<ServerRole, RuntimeCheckDefinition[]> = {
  core: [
    { id: "compose.required_services", required: true, timeoutSeconds: 15 },
    { id: "http.role_health", required: true, timeoutSeconds: 10 },
    { id: "core.database", required: true, timeoutSeconds: 10 },
    { id: "core.cache", required: true, timeoutSeconds: 10 },
    { id: "core.vault", required: true, timeoutSeconds: 10 },
    { id: "core.worker_queue", required: true, timeoutSeconds: CELERY_PROBE_CHECK_TIMEOUT_SECONDS },
    { id: "core.scheduler_freshness", required: true, timeoutSeconds: CELERY_PROBE_CHECK_TIMEOUT_SECONDS },
    { id: "core.chat_plumbing", required: true, timeoutSeconds: 20 },
  ],
  upload: [
    { id: "compose.required_services", required: true, timeoutSeconds: 15 },
    { id: "http.role_health", required: true, timeoutSeconds: 10 },
    { id: "core.vault", required: true, timeoutSeconds: 10 },
    { id: "upload.antivirus", required: true, timeoutSeconds: 10 },
  ],
  preview: [
    { id: "compose.required_services", required: true, timeoutSeconds: 15 },
    { id: "http.role_health", required: true, timeoutSeconds: 10 },
    { id: "preview.renderer", required: true, timeoutSeconds: 15 },
  ],
};

const BILLING_RUNTIME_CHECKS: RuntimeCheckDefinition[] = [
  { id: "billing.mode_enabled", required: true, timeoutSeconds: 5 },
  { id: "billing.stripe_account_read", required: true, timeoutSeconds: 15 },
  { id: "billing.routes_registered", required: true, timeoutSeconds: 5 },
  { id: "billing.workers_registered", required: true, timeoutSeconds: 10 },
  { id: "billing.webhook_configured", required: true, timeoutSeconds: 5 },
  { id: "billing.health_freshness", required: true, timeoutSeconds: 5 },
];
const INTEGRATION_ENV_KEYS = new Set([
  "GOOGLE_CALENDAR_OAUTH_REDIRECT_URI",
  "PROD_CORE_API_URL",
  "PROD_INTERNAL_API_SHARED_TOKEN",
  "DEV_CORE_API_URL",
  "DEV_INTERNAL_API_SHARED_TOKEN",
  "PREVIEW_CORS_ORIGINS",
  "PREVIEW_ALLOWED_REFERERS",
  "REPORT_ISSUE_EMAIL",
  "ADMIN_NOTIFY_EMAIL",
  "DAILY_MEETING_NOTIFY_EMAIL",
  "OPENCODE_WEB_BASE_URL",
]);

export function envKeyCategory(key: string): EnvCategory {
  if (OBSERVABILITY_ENV_PREFIXES.some((prefix) => key.startsWith(prefix))) return "observability";
  if (ADVANCED_ENV_KEYS.has(key)) return "advanced";
  if (INTEGRATION_ENV_KEYS.has(key) || INTEGRATION_SECRET_PREFIXES.some((prefix) => key.startsWith(prefix))) return "integrations";
  if (key.startsWith("SECRET__")) return "providers";
  return "runtime";
}

export function isSecretEnvKey(key: string): boolean {
  return key.startsWith("SECRET__") || key.includes("PASSWORD") || key.includes("TOKEN") || key.includes("SECRET") || key.includes("API_KEY");
}

export function redactEnvValue(key: string, value: string): string {
  if (!value) return "";
  if (!isSecretEnvKey(key)) return value;
  return value === "IMPORTED_TO_VAULT" ? value : "<redacted>";
}

export function parseEnvEntries(content: string): EnvEntry[] {
  const entries: EnvEntry[] = [];
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx === -1) continue;
    const key = trimmed.slice(0, eqIdx).trim();
    if (!key) continue;
    const value = trimmed.slice(eqIdx + 1).replace(/^"|"$/g, "");
    entries.push({
      key,
      value,
      category: envKeyCategory(key),
      secret: isSecretEnvKey(key),
      redactedValue: redactEnvValue(key, value),
    });
  }
  return entries.sort((a, b) => a.category.localeCompare(b.category) || a.key.localeCompare(b.key));
}

export function upsertEnvValue(content: string, key: string, value: string): string {
  const lines = content.split("\n");
  let updated = false;
  const next = lines.map((line) => {
    const trimmed = line.trimStart();
    if (trimmed.startsWith("#") || !trimmed.startsWith(`${key}=`)) return line;
    updated = true;
    return `${key}=${value}`;
  });
  if (!updated) {
    if (next.length && next[next.length - 1] !== "") next.push("");
    next.push(`${key}=${value}`);
  }
  return `${next.join("\n").replace(/\n*$/, "")}\n`;
}

export function unsetEnvValue(content: string, key: string): string {
  return `${content
    .split("\n")
    .filter((line) => {
      const trimmed = line.trimStart();
      return trimmed.startsWith("#") || !trimmed.startsWith(`${key}=`);
    })
    .join("\n")
    .replace(/\n*$/, "")}\n`;
}

function unique(items: string[]): string[] {
  return [...new Set(items.map((item) => item.trim()).filter(Boolean))];
}

function csv(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  if (Array.isArray(value)) return unique(value.flatMap((item) => item.split(",")));
  return unique(value.split(","));
}

export function parseServerRole(value: string | undefined): ServerRole {
  if (!value) return "core";
  if (value === "core" || value === "upload" || value === "preview") return value;
  throw new Error(`Unsupported server role '${value}'. Use core, upload, or preview.`);
}

export function defaultOpenMatesCloudOverlayPath(openMatesPath: string): string {
  return resolve(join(dirname(resolve(openMatesPath)), OPENMATESCLOUD_OVERLAY_DIR));
}

export function defaultOpenMatesCloudComposeFile(overlayPath: string): string {
  return resolve(join(overlayPath, OPENMATESCLOUD_COMPOSE_FILE));
}

export function planOpenMatesCloudOverlay(input: OpenMatesCloudOverlayInput): OpenMatesCloudOverlayPlan {
  const deploymentMode = input.deploymentMode ?? "self_host";

  if (deploymentMode === "self_host") {
    return {
      deploymentMode,
      enabled: false,
      overlayPath: null,
      composeFiles: [],
      env: { OPENMATES_CLOUD_OVERLAY_ENABLED: "false" },
      modeLabel: "self-host core",
    };
  }

  const openMatesPath = resolve(input.openMatesPath);
  const overlayPath = resolve(input.overlayPath ?? defaultOpenMatesCloudOverlayPath(openMatesPath));
  if (input.overlayExists !== true) {
    throw new Error(`OpenMatesCloud overlay path is required for official-cloud mode: ${overlayPath}`);
  }

  const overlayComposeFile = resolve(input.overlayComposeFile ?? defaultOpenMatesCloudComposeFile(overlayPath));
  return {
    deploymentMode,
    enabled: true,
    overlayPath,
    composeFiles: [overlayComposeFile, OFFICIAL_CLOUD_NO_WEBAPP_COMPOSE_FILE],
    env: {
      OPENMATES_CLOUD_OVERLAY_ENABLED: "true",
      OPENMATES_CLOUD_OVERLAY_PATH: overlayPath,
    },
    modeLabel: "official cloud overlay",
  };
}

export function appendOpenMatesCloudComposeFiles(args: string[], plan: OpenMatesCloudOverlayPlan): string[] {
  if (!plan.enabled) return args;
  return [...args, ...plan.composeFiles.flatMap((composeFile) => ["-f", composeFile])];
}

export function planDockerComposeArgs(input: DockerComposeArgsInput): string[] {
  const role = parseServerRole(input.role);
  if (input.deploymentMode === "official_cloud" && role !== "core") {
    throw new Error("OpenMatesCloud overlay mode is only supported for the core server role.");
  }

  const composeFile = input.installMode === "image"
    ? ROLE_DEFINITIONS[role].composeFile
    : SOURCE_COMPOSE_FILES[role];
  const args = ["compose", "--env-file", ".env", "-f", composeFile];
  if (input.withOverrides === true && input.overrideExists === true) {
    args.push("-f", COMPOSE_OVERRIDE);
  }

  const overlayPlan = planOpenMatesCloudOverlay({
    deploymentMode: input.deploymentMode,
    openMatesPath: input.openMatesPath,
    overlayPath: input.overlayPath,
    overlayComposeFile: input.overlayComposeFile,
    overlayExists: input.overlayExists,
  });
  return appendOpenMatesCloudComposeFiles(args, overlayPlan);
}

export function planServerRuntime(input: { role?: ServerRole | string; profile?: CoreProfile; withAlerts?: boolean; includeWebapp?: boolean }): RuntimePlan {
  const role = parseServerRole(input.role);
  const definition = ROLE_DEFINITIONS[role];
  const coreProfile: CoreProfile = input.profile ?? "production";
  const profile = role === "core" ? coreProfile : null;
  const profileServices = role === "core" ? [...CORE_OBSERVABILITY_BY_PROFILE[coreProfile]] : [];
  if (role === "core" && input.withAlerts) profileServices.push("alertmanager");

  const webappServices = input.includeWebapp === false ? [] : ["webapp"];
  const defaultServices = role === "core"
    ? unique([...definition.requiredServices, ...CORE_WORKER_SERVICES, "admin-sidecar", ...profileServices, ...webappServices])
    : unique([...definition.requiredServices, ...definition.optionalServices]);

  return {
    role,
    profile,
    dataBearing: definition.dataBearing,
    composeFiles: [definition.composeFile],
    requiredServices: [...definition.requiredServices],
    profileServices,
    defaultServices,
    healthChecks: [...definition.healthChecks],
  };
}

export function resolveServiceSelection(roleValue: ServerRole | string | undefined, filter: ServiceFilter = {}): string[] {
  const role = parseServerRole(roleValue);
  const definition = ROLE_DEFINITIONS[role];
  const allowed = new Set([...definition.requiredServices, ...definition.optionalServices]);
  const requested = csv(filter.services);
  const excluded = new Set(csv(filter.exclude));
  const base = requested.length ? requested : [...allowed];

  for (const service of [...base, ...excluded]) {
    if (!allowed.has(service)) {
      throw new Error(`Invalid service '${service}' for ${role} role.`);
    }
  }

  return base.filter((service) => !excluded.has(service));
}

export function appendSelectedServices(args: string[], selectedServices: string[], filterRequested: boolean): string[] {
  return filterRequested ? [...args, ...selectedServices] : args;
}

export function planServerLogRangeArgs(flags: Record<string, string | boolean>): string[] {
  const args: string[] = [];
  const since = flags.since;
  const tail = flags.tail;

  if (since === true) throw new Error("Provide a since value: --since <duration|timestamp>.");
  if (tail === true) throw new Error("Provide a tail value: --tail <n>.");

  if (typeof since === "string") {
    const trimmedSince = since.trim();
    if (!trimmedSince) throw new Error("--since cannot be empty.");
    args.push("--since", trimmedSince);
  }

  if (typeof tail === "string") {
    const trimmedTail = tail.trim();
    if (!trimmedTail) throw new Error("--tail cannot be empty.");
    args.push("--tail", trimmedTail);
  } else if (typeof since !== "string") {
    args.push("--tail", "100");
  }

  return args;
}

export function shouldCheckWebHealth(input: {
  role?: ServerRole | string;
  deploymentMode?: ServerDeploymentMode;
  selectedServices?: string[];
  filterRequested?: boolean;
}): boolean {
  const role = parseServerRole(input.role);
  if (role !== "core") return false;
  if (input.deploymentMode === "official_cloud") return false;
  return input.filterRequested !== true || (input.selectedServices ?? []).includes("webapp");
}

export function planUpdate(input: {
  role?: ServerRole | string;
  selectedServices?: string[];
  dryRun?: boolean;
  continuous?: boolean;
  skipBackup?: boolean;
  missingRequiredSecrets?: string[];
}): UpdatePlan {
  const runtime = planServerRuntime({ role: input.role });
  const selectedServices = input.selectedServices?.length ? input.selectedServices : runtime.defaultServices;
  const missingRequiredSecrets = input.missingRequiredSecrets ?? [];
  const blocked = input.continuous === true && missingRequiredSecrets.length > 0;
  const steps = ["preflight"];
  const backupName = runtime.dataBearing && input.skipBackup !== true ? `latest-pre-update-${runtime.role}.tar.gz` : null;
  if (backupName) steps.push("backup:latest-pre-update");
  steps.push("pull", "up", "health-check");

  return {
    role: runtime.role,
    selectedServices,
    steps,
    commands: [
      `docker compose pull ${selectedServices.join(" ")}`,
      `docker compose up -d ${selectedServices.join(" ")}`,
    ],
    backupName,
    blocked,
    blockReason: blocked ? `Blocked by missing required secrets: ${missingRequiredSecrets.join(", ")}` : null,
  };
}

export function planBackup(input: { role?: ServerRole | string; includeObservability?: boolean }): BackupPlan {
  const role = parseServerRole(input.role);
  const contentsByRole: Record<ServerRole, string[]> = {
    core: ["postgres-dump", "runtime-env", "runtime-config", "manifest", "checksums"],
    upload: ["runtime-env", "runtime-config", "manifest", "checksums"],
    preview: ["runtime-env", "runtime-config", "manifest", "checksums"],
  };
  const contents = [...contentsByRole[role]];
  return { role, contents, fileMode: 0o600 };
}

export function planRestore(input: { role?: ServerRole | string; file: string; yes?: boolean }): RestorePlan {
  const role = parseServerRole(input.role);
  return {
    role,
    file: input.file,
    requiresConfirmation: input.yes !== true,
    steps: input.yes === true ? ["stop", "restore", "start", "health-check"] : ["confirm", "stop", "restore", "start", "health-check"],
  };
}

export function resolveTemplateSource(input: {
  role?: ServerRole | string;
  packagedTemplateExists: boolean;
  templateUrl?: string;
  templateRef?: string;
}): TemplateSource {
  const role = parseServerRole(input.role);
  const definition = ROLE_DEFINITIONS[role];
  if (input.templateUrl) return { type: "url", url: input.templateUrl };
  if (input.packagedTemplateExists) return { type: "packaged", path: definition.templatePath };
  return { type: "github-raw", ref: input.templateRef ?? "dev", path: definition.composeFile };
}

export function findMissingRequiredSecrets(input: {
  installed: SecretRequirement[];
  target: SecretRequirement[];
  configuredEnvKeys: string[];
}): string[] {
  const installedKeys = new Set(input.installed.map((item) => item.envKey));
  const configured = new Set(input.configuredEnvKeys);
  return input.target
    .filter((item) => item.required && !item.noApiKey)
    .filter((item) => !configured.has(item.envKey))
    .filter((item) => !installedKeys.has(item.envKey) || !configured.has(item.envKey))
    .map((item) => item.envKey);
}

export function parseSecretEnvKey(envKey: string): ParsedSecretEnvKey | null {
  if (!envKey.startsWith("SECRET__")) return null;
  const parts = envKey.slice("SECRET__".length).split("__", 2);
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  return {
    envKey,
    vaultPath: `kv/data/providers/${parts[0].toLowerCase()}`,
    vaultKey: parts[1].toLowerCase(),
  };
}

export function summarizeSecretPreflight(input: {
  env: Record<string, string>;
  vaultPresence?: Record<string, VaultSecretPresence>;
}): SecretPreflightSummary {
  const inlineSecretEnvKeys: string[] = [];
  const importedSecretEnvKeys: string[] = [];
  const emptySecretEnvKeys: string[] = [];
  const importedVaultPresent: string[] = [];
  const importedVaultMissing: string[] = [];
  const importedVaultUnavailable: string[] = [];

  for (const [envKey, rawValue] of Object.entries(input.env).sort(([a], [b]) => a.localeCompare(b))) {
    if (!parseSecretEnvKey(envKey)) continue;
    const value = rawValue.trim();
    if (!value) {
      emptySecretEnvKeys.push(envKey);
      continue;
    }
    if (value !== "IMPORTED_TO_VAULT") {
      inlineSecretEnvKeys.push(envKey);
      continue;
    }

    importedSecretEnvKeys.push(envKey);
    const presence = input.vaultPresence?.[envKey];
    if (presence === "present") importedVaultPresent.push(envKey);
    else if (presence === "missing") importedVaultMissing.push(envKey);
    else importedVaultUnavailable.push(envKey);
  }

  return {
    inlineSecretEnvKeys,
    importedSecretEnvKeys,
    emptySecretEnvKeys,
    importedVaultPresent,
    importedVaultMissing,
    importedVaultUnavailable,
  };
}

export function planCaddyCommand(input: { role?: ServerRole | string; action: CaddyAction; appliedPath?: string }): CaddyPlan {
  const role = parseServerRole(input.role);
  const templatePath = `templates/caddy/${role}/Caddyfile`;
  const stepsByAction: Record<CaddyAction, string[]> = {
    check: ["render-template", "validate"],
    status: ["hash-template", "hash-applied", "validate"],
    diff: ["hash-template", "hash-applied", "diff"],
    apply: ["render-template", "validate", "backup-applied", "write", "reload"],
  };
  return {
    role,
    action: input.action,
    templatePath,
    appliedPath: input.appliedPath ?? "/etc/caddy/Caddyfile",
    steps: stepsByAction[input.action],
  };
}

export function planContinuousUpdateService(input: { role?: ServerRole | string; channel?: string; window?: string }): ContinuousUpdateServicePlan {
  const role = parseServerRole(input.role);
  const channel = input.channel ?? "main";
  const window = input.window ?? "02:00-04:00 UTC";
  const serviceName = `openmates-${role}-continuous-update.service`;
  const timerName = `openmates-${role}-continuous-update.timer`;
  return {
    role,
    serviceName,
    timerName,
    unit: [
      "[Unit]",
      `Description=OpenMates ${role} continuous updater`,
      "After=docker.service network-online.target",
      "Wants=network-online.target",
      "",
      "[Service]",
      "Type=oneshot",
      `ExecStart=openmates server update --role ${role} --channel ${channel} --continuous`,
      `Environment=OPENMATES_UPDATE_WINDOW=${window}`,
      "",
    ].join("\n"),
    timer: [
      "[Unit]",
      `Description=Run OpenMates ${role} continuous updater`,
      "",
      "[Timer]",
      "OnCalendar=*:0/30",
      "Persistent=true",
      "",
      "[Install]",
      "WantedBy=timers.target",
      "",
    ].join("\n"),
  };
}

export function resolveRuntimeDeploymentMode(input: { envText: string; overlayExists: boolean }): RuntimeDeploymentModeResult {
  const { envText, overlayExists } = input;
  const modeEntries = parseEnvEntries(envText).filter((entry) => entry.key === "OPENMATES_DEPLOYMENT_MODE");
  if (modeEntries.length > 1) {
    return { effectiveMode: "self_host", status: "conflicting", reason: "deployment_mode_duplicate", billingEnabled: false };
  }
  const values = new Map(parseEnvEntries(envText).map((entry) => [entry.key, entry.value]));
  const rawMode = values.get("OPENMATES_DEPLOYMENT_MODE");
  if (!rawMode) {
    return { effectiveMode: "self_host", status: "missing", reason: "deployment_mode_missing", billingEnabled: false };
  }
  if (rawMode !== "self_host" && rawMode !== "official_cloud") {
    return { effectiveMode: "self_host", status: "malformed", reason: "deployment_mode_invalid", billingEnabled: false };
  }

  const overlayEnabled = values.get("OPENMATES_CLOUD_OVERLAY_ENABLED") === "true";
  const overlayPackage = values.get("OPENMATES_CLOUD_OVERLAY_PACKAGE");
  if (rawMode === "self_host") {
    const conflicting = overlayEnabled || overlayPackage === "OpenMatesCloud";
    return {
      effectiveMode: "self_host",
      status: conflicting ? "conflicting" : "valid",
      reason: conflicting ? "self_host_overlay_conflict" : "self_host_explicit",
      billingEnabled: false,
    };
  }
  if (!overlayEnabled || overlayPackage !== "OpenMatesCloud") {
    return { effectiveMode: "self_host", status: "conflicting", reason: "official_cloud_overlay_conflict", billingEnabled: false };
  }
  if (!overlayExists) {
    return { effectiveMode: "self_host", status: "unavailable", reason: "official_cloud_overlay_unavailable", billingEnabled: false };
  }
  return { effectiveMode: "official_cloud", status: "valid", reason: "official_cloud_verified", billingEnabled: true };
}

export function buildRuntimeCheckInventory(role: ServerRole, mode: ServerDeploymentMode): RuntimeCheckDefinition[] {
  const checks = RUNTIME_CHECKS[role].map((check) => ({ ...check }));
  if (role === "core" && mode === "official_cloud") {
    checks.push(...BILLING_RUNTIME_CHECKS.map((check) => ({ ...check })));
  }
  return checks;
}

export function planRuntimeVerification(
  input: { role: ServerRole; deploymentMode: ServerDeploymentMode; hasVerifiedBackup: boolean },
): {
  command: string;
  globalDeadlineSeconds: number;
  checks: RuntimeCheckDefinition[];
  phases: { checkIds: string[] }[];
  restoreStatus: "available" | "restore_unavailable";
  restoreCommand: string | null;
} {
  const checks = buildRuntimeCheckInventory(input.role, input.deploymentMode);
  const verifierService = { core: "api", upload: "app-uploads", preview: "preview" }[input.role];
  return {
    command: `docker compose exec -T ${verifierService} python -m backend.scripts.runtime_health_verifier --role ${input.role} --json`,
    globalDeadlineSeconds: 60,
    checks,
    phases: [
      { checkIds: checks.filter((check) => check.id === "compose.required_services" || check.id === "http.role_health").map((check) => check.id) },
      { checkIds: checks.filter((check) => check.id !== "compose.required_services" && check.id !== "http.role_health").map((check) => check.id) },
    ],
    restoreStatus: input.hasVerifiedBackup ? "available" : "restore_unavailable",
    restoreCommand: input.hasVerifiedBackup ? `openmates server restore --role ${input.role} --backup latest-pre-update-${input.role}.tar.gz` : null,
  };
}

export function planRuntimeMonitoringServices(
  input: { role: ServerRole; installPath: string; executablePath?: string },
): RuntimeMonitoringServicePlan {
  const executablePath = input.executablePath ?? "/usr/local/bin/openmates";
  const serviceName = `openmates-${input.role}-runtime-monitor.service`;
  const timerName = `openmates-${input.role}-runtime-monitor.timer`;
  const watchdogServiceName = `openmates-${input.role}-runtime-watchdog.service`;
  const watchdogTimerName = `openmates-${input.role}-runtime-watchdog.timer`;
  return {
    role: input.role,
    serviceName,
    timerName,
    unit: [
      "[Unit]",
      `Description=OpenMates ${input.role} runtime health monitor`,
      "After=docker.service network-online.target",
      "Wants=network-online.target",
      "",
      "[Service]",
      "Type=oneshot",
      `WorkingDirectory=${input.installPath}`,
      `ExecStart=${executablePath} server monitoring run --role ${input.role}`,
      "",
    ].join("\n"),
    timer: [
      "[Unit]",
      `Description=Schedule OpenMates ${input.role} runtime health monitor`,
      "",
      "[Timer]",
      "OnBootSec=2min",
      "OnUnitActiveSec=5min",
      "Persistent=true",
      `Unit=${serviceName}`,
      "",
      "[Install]",
      "WantedBy=timers.target",
      "",
    ].join("\n"),
    watchdogServiceName,
    watchdogTimerName,
    watchdogUnit: [
      "[Unit]",
      `Description=OpenMates ${input.role} independent runtime watchdog`,
      "After=network-online.target",
      "Wants=network-online.target",
      "",
      "[Service]",
      "Type=oneshot",
      `WorkingDirectory=${input.installPath}`,
      `ExecStart=${executablePath} server monitoring run --role ${input.role} --watchdog`,
      "",
    ].join("\n"),
    watchdogTimer: [
      "[Unit]",
      `Description=Schedule OpenMates ${input.role} independent runtime watchdog`,
      "",
      "[Timer]",
      "OnBootSec=3min",
      "OnUnitActiveSec=5min",
      "Persistent=true",
      `Unit=${watchdogServiceName}`,
      "",
      "[Install]",
      "WantedBy=timers.target",
      "",
    ].join("\n"),
  };
}

export function shouldAutoInstallRuntimeMonitoringServices(env: Record<string, string | undefined>): boolean {
  return env.OPENMATES_SKIP_RUNTIME_MONITORING !== "1";
}
