/*
 * OpenMates CLI server planning helpers.
 *
 * Purpose: resolve server roles, service filters, update phases, backup scope,
 *          and host-level Caddy/preflight plans before shelling out to Docker.
 * Architecture: pure functions shared by CLI commands and unit tests.
 * Tests: frontend/packages/openmates-cli/tests/server.test.ts
 */

export type ServerRole = "core" | "upload" | "preview";
export type CoreProfile = "minimal" | "standard" | "production";
export type CaddyAction = "check" | "status" | "diff" | "apply";

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

const CORE_WORKER_SERVICES = [
  "task-worker",
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

const CORE_OBSERVABILITY_BY_PROFILE: Record<CoreProfile, string[]> = {
  minimal: [],
  standard: ["openobserve", "promtail"],
  production: ["openobserve", "promtail", "prometheus", "cadvisor"],
};

const ROLE_DEFINITIONS: Record<ServerRole, RoleDefinition> = {
  core: {
    dataBearing: true,
    requiredServices: ["api", "cms", "cms-database", "cache", "vault", "vault-setup", "cms-setup"],
    optionalServices: [...CORE_WORKER_SERVICES, "admin-sidecar", "webapp", "openobserve", "promtail", "prometheus", "cadvisor", "alertmanager"],
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

export function planServerRuntime(input: { role?: ServerRole | string; profile?: CoreProfile; withAlerts?: boolean }): RuntimePlan {
  const role = parseServerRole(input.role);
  const definition = ROLE_DEFINITIONS[role];
  const coreProfile: CoreProfile = input.profile ?? "production";
  const profile = role === "core" ? coreProfile : null;
  const profileServices = role === "core" ? [...CORE_OBSERVABILITY_BY_PROFILE[coreProfile]] : [];
  if (role === "core" && input.withAlerts) profileServices.push("alertmanager");

  const defaultServices = role === "core"
    ? unique([...definition.requiredServices, ...CORE_WORKER_SERVICES, "admin-sidecar", ...profileServices, "webapp"])
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
  const backupName = runtime.dataBearing && input.skipBackup !== true ? `latest-pre-update-${runtime.role}.tar.zst` : null;
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
    core: ["postgres-dump", "directus-uploads", "directus-extensions", "vault-data", "vault-setup-data", "runtime-env", "runtime-config", "manifest", "checksums"],
    upload: ["vault-data", "vault-setup-data", "runtime-env", "runtime-config", "manifest", "checksums"],
    preview: ["runtime-env", "runtime-config", "preview-cache", "manifest", "checksums"],
  };
  const contents = [...contentsByRole[role]];
  if (input.includeObservability) contents.push("openobserve-data", "prometheus-data");
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
