// contract-test-file: tooling
/**
 * Unit tests for CLI server management commands.
 *
 * Tests config storage, path resolution, compose argument building,
 * LLM credential checking, and help output.
 *
 * Run: node --test --experimental-strip-types tests/server.test.ts
 */

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { parse as parseYaml } from "yaml";

// Use dynamic imports to avoid ESM .js extension resolution issues with
// --experimental-strip-types. tsx handles this automatically, but we use
// node --test for consistency with the CI runner.
import type { ServerConfig } from "../src/serverConfig.ts";

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
const IMAGE_CHANNEL_TAGS = {
  stable: "main",
  main: "main",
  dev: "dev",
} as const;

// Import the functions we need to test. Since serverConfig.ts doesn't import
// other .js modules, it works fine with --experimental-strip-types.
import {
  saveServerConfig,
  loadServerConfig,
  removeServerConfig,
  resolveServerPath,
} from "../src/serverConfig.ts";
import {
  ensureSourceInstallTranslations,
  sourceInstallLocalesPath,
} from "../src/sourceInstallTranslations.ts";
import {
  parseServerRole,
  planBackup,
  planCaddyCommand,
  planContinuousUpdateService,
  planRestore,
  planServerRuntime,
  planUpdate,
  parseSecretEnvKey,
  planServerLogRangeArgs,
  resolveServiceSelection,
  resolveTemplateSource,
  findMissingRequiredSecrets,
  summarizeSecretPreflight,
  appendSelectedServices,
  parseEnvEntries,
  redactEnvValue,
  shouldCheckWebHealth,
  unsetEnvValue,
  upsertEnvValue,
  planOpenMatesCloudOverlay,
  appendOpenMatesCloudComposeFiles,
  planDockerComposeArgs,
  defaultOpenMatesCloudComposeFile,
  defaultOpenMatesCloudOverlayPath,
  buildRuntimeCheckInventory,
  planRuntimeMonitoringServices,
  planRuntimeVerification,
  resolveRuntimeDeploymentMode,
  shouldAutoInstallRuntimeMonitoringServices,
  OFFICIAL_CLOUD_NO_WEBAPP_COMPOSE_FILE,
} from "../src/serverPlanning.ts";
import {
  applyRuntimeCheckResults,
  buildBrevoRequestOptions,
  buildUpdateCompletionEmail,
  buildUpdateCompletionOutcome,
  buildOperationalDeliveryReceipt,
  buildRuntimeEmail,
  deliverUpdateCompletionEmail,
  evaluateOperationalReportFreshness,
  isBrevoIdempotencyDuplicate,
  isBrevoAcceptedResponse,
  planOperationalMonitoring,
  planUpdateCompletionDelivery,
  signRuntimeWebhookPayload,
  selectUpdateSourceLink,
  validateRuntimeWebhookDestination,
} from "../src/serverHealth.ts";
import { renderSupportStartReminder } from "../src/support.ts";
import {
  acquireServerUpdateLock,
  readServerUpdateStatus,
  serverUpdateStatusFile,
  writeServerUpdateStatus,
} from "../src/serverUpdateState.ts";

const ORIGINAL_STATE_DIR = process.env.OPENMATES_STATE_DIR;
const TEST_STATE_DIR = join(tmpdir(), `openmates-cli-state-${process.pid}-${Date.now()}`);
process.env.OPENMATES_STATE_DIR = TEST_STATE_DIR;
after(() => {
  rmSync(TEST_STATE_DIR, { recursive: true, force: true });
  if (ORIGINAL_STATE_DIR === undefined) delete process.env.OPENMATES_STATE_DIR;
  else process.env.OPENMATES_STATE_DIR = ORIGINAL_STATE_DIR;
});

it("routes source server restarts through the engineering runtime-operation guard", () => {
  const source = readFileSync(join(import.meta.dirname, "..", "src", "server.ts"), "utf-8");
  assert.match(source, /withEngineeringRuntimeOperation\(/);
  assert.match(source, /product_server_rebuild/);
  assert.match(source, /product_server_restart/);
  assert.match(source, /engineering_control_plane\.py/);
  const guardSource = source.slice(
    source.indexOf("function beginEngineeringRuntimeOperation"),
    source.indexOf("function finishEngineeringRuntimeOperation"),
  );
  assert.match(guardSource, /if \(!existsSync\(manager\) \|\| !existsSync\(sharedConfig\)\) return null/);
  assert.match(guardSource, /\.config["', ]+openmates["', ]+engineering-control-plane\.env/);
});

// server.ts imports serverConfig.js which breaks with --experimental-strip-types.
// Re-implement the pure functions we want to test inline, or import them
// from the built dist/. For unit tests of pure functions, we test the logic
// directly by extracting testable functions.
// We test hasLlmCredentials and composeArgs by importing from the built output.
// For CI, run: npm run build && node --test tests/server.test.ts

// Since server.ts imports from ./serverConfig.js, we need tsx to run tests
// that import server.ts. Use the inlined test versions below.

/**
 * Inline copy of hasLlmCredentials for testing without requiring tsx.
 * Must stay in sync with src/server.ts.
 */
function hasLlmCredentials(envPath: string): boolean {
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

/**
 * Inline copy of composeArgs for testing without requiring tsx.
 */
function readEnvMapForComposeTest(installPath: string): Record<string, string> {
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

function composeArgs(installPath: string, withOverrides: boolean, installMode?: "image" | "source"): string[] {
  const resolvedInstallMode = installMode ?? (
    existsSync(join(installPath, "backend", "core", "docker-compose.yml"))
      ? "source"
      : existsSync(join(installPath, "backend", "core", "docker-compose.selfhost.yml")) ? "image" : "source"
  );
  const env = readEnvMapForComposeTest(installPath);
  const deploymentMode = env.OPENMATES_CLOUD_OVERLAY_ENABLED === "true" ? "official_cloud" : "self_host";
  const overlayPath = env.OPENMATES_CLOUD_OVERLAY_PATH || undefined;
  const resolvedOverlayPath = overlayPath ?? defaultOpenMatesCloudOverlayPath(installPath);
  const overlayComposeFile = defaultOpenMatesCloudComposeFile(resolvedOverlayPath);
  return planDockerComposeArgs({
    openMatesPath: installPath,
    installMode: resolvedInstallMode,
    withOverrides,
    overrideExists: existsSync(join(installPath, "backend", "core", "docker-compose.override.yml")),
    deploymentMode,
    overlayPath,
    overlayComposeFile,
    overlayExists: deploymentMode === "official_cloud" && existsSync(resolvedOverlayPath) && existsSync(overlayComposeFile),
  });
}

function getDefaultImageTagForVersion(version: string): string {
  return version ? `v${version}` : "dev";
}

function defaultTemplateRefForVersion(version: string): string {
  return /-(alpha|beta|rc)(\.|\d|$)/.test(version) ? "dev" : `v${version}`;
}

function templateRefForImageTag(imageTag: string, packageVersion = ""): string {
  const channelTag = IMAGE_CHANNEL_TAGS[imageTag as keyof typeof IMAGE_CHANNEL_TAGS];
  if (channelTag) return channelTag;
  if (imageTag.startsWith("v")) return defaultTemplateRefForVersion(imageTag.slice(1));
  if (!imageTag && packageVersion) return defaultTemplateRefForVersion(packageVersion);
  return "dev";
}

function resolveTargetImageTag(
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
    if (!tag) throw new Error("Unsupported update channel.");
    return { tag, channel: tag };
  }

  const installedChannel = IMAGE_CHANNEL_TAGS[currentTag as keyof typeof IMAGE_CHANNEL_TAGS];
  if (installedChannel) return { tag: installedChannel, channel: installedChannel };
  return { tag: getDefaultImageTagForVersion(packageVersion) };
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

function docAssert(claimId: string, assertion: () => void): void {
  try {
    assertion();
  } catch (error) {
    if (error instanceof Error) {
      error.message = `[doc-assert:${claimId}] ${error.message}`;
    }
    throw error;
  }
}

// ---------------------------------------------------------------------------
// serverConfig.ts tests
// ---------------------------------------------------------------------------

describe("ServerConfig", () => {
  const STATE_DIR = TEST_STATE_DIR;
  const CONFIG_PATH = join(STATE_DIR, "server.json");
  let backupExists = false;
  let backupContent: string | null = null;

  before(() => {
    // Back up existing config if present
    if (existsSync(CONFIG_PATH)) {
      backupExists = true;
      backupContent = readFileSync(CONFIG_PATH, "utf-8");
    }
  });

  after(() => {
    // Restore backup
    if (backupExists && backupContent !== null) {
      writeFileSync(CONFIG_PATH, backupContent);
    } else {
      removeServerConfig();
    }
  });

  it("saves and loads a config", () => {
    docAssert("cli-server-config-saves-loads-and-removes", () => {
      const config: ServerConfig = {
        installPath: "/tmp/test-openmates",
        installedAt: Date.now(),
        composeProfile: "core",
        installMode: "source",
        sourceStrategy: "working_tree",
        apiUrl: "http://localhost:8000",
        appUrl: "http://localhost:5173",
      };
      saveServerConfig(config);
      const loaded = loadServerConfig();
      assert.ok(loaded);
      assert.equal(loaded.installPath, config.installPath);
      assert.equal(loaded.composeProfile, "core");
      assert.equal(loaded.installMode, "source");
      assert.equal(loaded.sourceStrategy, "working_tree");
      assert.equal(loaded.apiUrl, "http://localhost:8000");
      assert.equal(loaded.appUrl, "http://localhost:5173");
    });
  });

  it("returns null when no config exists", () => {
    removeServerConfig();
    const loaded = loadServerConfig();
    assert.equal(loaded, null);
  });

  it("removeServerConfig is safe when file does not exist", () => {
    docAssert("cli-server-config-saves-loads-and-removes", () => {
      removeServerConfig();
      assert.doesNotThrow(() => removeServerConfig());
    });
  });
});

describe("resolveServerPath", () => {
  let tempDir: string;

  before(() => {
    // Create a temp directory that looks like an OpenMates repo
    tempDir = join(tmpdir(), `openmates-test-${Date.now()}`);
    const composeDir = join(tempDir, "backend", "core");
    mkdirSync(composeDir, { recursive: true });
    writeFileSync(join(composeDir, "docker-compose.yml"), "version: '3'\n");
  });

  after(() => {
    rmSync(tempDir, { recursive: true, force: true });
    removeServerConfig();
  });

  it("resolves from --path flag", () => {
    docAssert("cli-server-path-resolution-validates-installation", () => {
      const result = resolveServerPath({ path: tempDir });
      assert.equal(result, tempDir);
    });
  });

  it("rejects --path that is not an OpenMates dir", () => {
    docAssert("cli-server-path-resolution-validates-installation", () => {
      assert.throws(
        () => resolveServerPath({ path: tmpdir() }),
        /does not appear to be an OpenMates installation/,
      );
    });
  });

  it("resolves from saved config", () => {
    saveServerConfig({
      installPath: tempDir,
      installedAt: Date.now(),
      composeProfile: "core",
    });
    const result = resolveServerPath({});
    assert.equal(result, tempDir);
    removeServerConfig();
  });

  it("resolves image-mode installs from the self-host compose marker", () => {
    const imageDir = join(tmpdir(), `openmates-image-test-${Date.now()}`);
    const composeDir = join(imageDir, "backend", "core");
    mkdirSync(composeDir, { recursive: true });
    writeFileSync(join(composeDir, "docker-compose.selfhost.yml"), "services: {}");

    const result = resolveServerPath({ path: imageDir });

    assert.equal(result, imageDir);
    rmSync(imageDir, { recursive: true, force: true });
  });

  it("throws when no installation found", () => {
    removeServerConfig();
    // Only fails if cwd is not an OpenMates dir — which tmpdir isn't
    const origCwd = process.cwd();
    try {
      process.chdir(tmpdir());
      assert.throws(
        () => resolveServerPath({}),
        /No OpenMates installation found/,
      );
    } finally {
      process.chdir(origCwd);
    }
  });
});

// ---------------------------------------------------------------------------
// server.ts tests
// ---------------------------------------------------------------------------

describe("composeArgs", () => {
  let tempDir: string;

  before(() => {
    tempDir = join(tmpdir(), `openmates-compose-test-${Date.now()}`);
    const composeDir = join(tempDir, "backend", "core");
    mkdirSync(composeDir, { recursive: true });
    writeFileSync(join(composeDir, "docker-compose.yml"), "version: '3'\n");
    writeFileSync(join(composeDir, "docker-compose.override.yml"), "version: '3'\n");
  });

  after(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("returns base compose args without overrides", () => {
    docAssert("cli-server-compose-uses-base-and-optional-overrides", () => {
      const args = composeArgs(tempDir, false);
      assert.deepEqual(args, [
        "compose", "--env-file", ".env",
        "-f", join("backend", "core", "docker-compose.yml"),
      ]);
    });
  });

  it("includes override file when requested and exists", () => {
    docAssert("cli-server-compose-uses-base-and-optional-overrides", () => {
      const args = composeArgs(tempDir, true);
      assert.equal(args.length, 7);
      assert.ok(args.includes(join("backend", "core", "docker-compose.override.yml")));
    });
  });

  it("uses self-host compose file for image mode", () => {
    const args = composeArgs(tempDir, false, "image");
    assert.deepEqual(args, [
      "compose", "--env-file", ".env",
      "-f", join("backend", "core", "docker-compose.selfhost.yml"),
    ]);
  });

  it("infers image mode from the self-host compose marker", () => {
    const imageDir = join(tmpdir(), `openmates-image-compose-${Date.now()}`);
    const composeDir = join(imageDir, "backend", "core");
    mkdirSync(composeDir, { recursive: true });
    writeFileSync(join(composeDir, "docker-compose.selfhost.yml"), "services: {}");

    const args = composeArgs(imageDir, false);

    assert.deepEqual(args, [
      "compose", "--env-file", ".env",
      "-f", join("backend", "core", "docker-compose.selfhost.yml"),
    ]);
    rmSync(imageDir, { recursive: true, force: true });
  });

  it("skips override file when it does not exist", () => {
    const emptyDir = join(tmpdir(), `no-override-${Date.now()}`);
    mkdirSync(join(emptyDir, "backend", "core"), { recursive: true });
    const args = composeArgs(emptyDir, true);
    assert.equal(args.length, 5); // No override added
    rmSync(emptyDir, { recursive: true, force: true });
  });

  it("appends the OpenMatesCloud compose file and no-webapp override when env enables official-cloud mode", () => {
    const rootDir = join(tmpdir(), `openmates-official-cloud-${Date.now()}`);
    const installPath = join(rootDir, "OpenMates");
    const overlayPath = join(rootDir, "OpenMatesCloud");
    const overlayComposeFile = join(overlayPath, "docker-compose.openmatescloud.yml");
    mkdirSync(join(installPath, "backend", "core"), { recursive: true });
    mkdirSync(overlayPath, { recursive: true });
    writeFileSync(join(installPath, "backend", "core", "docker-compose.yml"), "services: {}\n");
    writeFileSync(join(installPath, ".env"), "OPENMATES_CLOUD_OVERLAY_ENABLED=true\n");
    writeFileSync(overlayComposeFile, "services: {}\n");

    const args = composeArgs(installPath, false, "source");

    assert.deepEqual(args, [
      "compose", "--env-file", ".env",
      "-f", join("backend", "core", "docker-compose.yml"),
      "-f", overlayComposeFile,
      "-f", OFFICIAL_CLOUD_NO_WEBAPP_COMPOSE_FILE,
    ]);
    rmSync(rootDir, { recursive: true, force: true });
  });

  it("server composeArgs delegates to the shared OpenMatesCloud compose planner", () => {
    const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf-8");
    const composeSource = source.slice(source.indexOf("export function composeArgs"), source.indexOf("/** Ensure compose interpolation"));

    assert.match(composeSource, /getInstallDeploymentMode/);
    assert.match(composeSource, /ensureOfficialCloudNoWebappComposeFile/);
    assert.match(composeSource, /planDockerComposeArgs/);
  });

  it("caps generated env backups so secret-bearing copies do not accumulate", () => {
    const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf-8");
    const pruneSource = source.slice(source.indexOf("function pruneEnvBackups"), source.indexOf("function backupEnvFile"));
    const backupSource = source.slice(source.indexOf("function backupEnvFile"), source.indexOf("function writeEnvContent"));

    assert.match(source, /const ENV_BACKUP_PREFIX = "\.env\.openmates-backup-"/);
    assert.match(source, /const ENV_BACKUP_RETENTION_COUNT = 5/);
    assert.match(pruneSource, /entry\.isFile\(\) && entry\.name\.startsWith\(ENV_BACKUP_PREFIX\)/);
    assert.match(pruneSource, /backups\.slice\(0, Math\.max\(0, backups\.length - ENV_BACKUP_RETENTION_COUNT\)\)/);
    assert.match(pruneSource, /rmSync\(join\(installPath, backup\), \{ force: true \}\)/);
    assert.match(backupSource, /pruneEnvBackups\(installPath\)/);
  });
});

describe("server start override persistence", () => {
  it("registers an unregistered source checkout before starting with overrides", () => {
    const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf-8");
    const startSource = source.slice(source.indexOf("async function serverStart"), source.indexOf("async function serverStop"));

    assert.match(startSource, /flags\["with-overrides"\] === true && !config && !loadServerConfig\(\)/);
    assert.match(startSource, /await serverRegister\(\{ path: installPath, "with-overrides": true \}\)/);
    assert.match(startSource, /config = loadConfigForInstallPath\(installPath\)/);
  });
});

describe("source install translations", () => {
  it("copies generated locale JSON from a local source checkout", () => {
    const rootDir = join(tmpdir(), `openmates-source-translations-${Date.now()}`);
    const sourcePath = join(rootDir, "source");
    const installPath = join(rootDir, "install");
    const sourceLocaleDir = sourceInstallLocalesPath(sourcePath);
    mkdirSync(sourceLocaleDir, { recursive: true });
    mkdirSync(installPath, { recursive: true });
    writeFileSync(join(sourceLocaleDir, "en.json"), JSON.stringify({ common: { ok: { text: "OK" } } }));
    writeFileSync(join(sourceLocaleDir, "de.json"), JSON.stringify({ common: { ok: { text: "OK" } } }));

    const result = ensureSourceInstallTranslations(installPath, sourcePath);

    assert.equal(result.status, "copied");
    assert.equal(result.copiedFiles, 2);
    assert.equal(
      readFileSync(join(sourceInstallLocalesPath(installPath), "en.json"), "utf-8"),
      '{"common":{"ok":{"text":"OK"}}}',
    );
    assert.equal(
      readFileSync(join(sourceInstallLocalesPath(installPath), "de.json"), "utf-8"),
      '{"common":{"ok":{"text":"OK"}}}',
    );
    rmSync(rootDir, { recursive: true, force: true });
  });

  it("does not rebuild when required generated locale JSON already exists", () => {
    const installPath = join(tmpdir(), `openmates-existing-translations-${Date.now()}`);
    const localeDir = sourceInstallLocalesPath(installPath);
    mkdirSync(localeDir, { recursive: true });
    writeFileSync(join(localeDir, "en.json"), "{}");

    const result = ensureSourceInstallTranslations(installPath, null);

    assert.equal(result.status, "already_present");
    assert.equal(result.copiedFiles, 0);
    rmSync(installPath, { recursive: true, force: true });
  });
});

describe("OpenMatesCloud overlay planning", () => {
  const openMatesPath = join("/srv", "OpenMates");
  const siblingOverlayPath = join("/srv", "OpenMatesCloud");

  it("keeps self-host core mode free of overlay requirements", () => {
    const plan = planOpenMatesCloudOverlay({
      deploymentMode: "self_host",
      openMatesPath,
    });
    const baseArgs = ["compose", "--env-file", ".env", "-f", join("backend", "core", "docker-compose.selfhost.yml")];

    assert.equal(plan.enabled, false);
    assert.equal(plan.overlayPath, null);
    assert.deepEqual(plan.composeFiles, []);
    assert.equal(plan.env.OPENMATES_CLOUD_OVERLAY_ENABLED, "false");
    assert.match(plan.modeLabel, /self-host core/);
    assert.deepEqual(appendOpenMatesCloudComposeFiles(baseArgs, plan), baseArgs);
  });

  it("resolves sibling official-cloud overlay and disables the bundled webapp", () => {
    const plan = planOpenMatesCloudOverlay({
      deploymentMode: "official_cloud",
      openMatesPath,
      overlayExists: true,
    });
    const baseArgs = ["compose", "--env-file", ".env", "-f", join("backend", "core", "docker-compose.yml")];

    assert.equal(plan.enabled, true);
    assert.equal(plan.overlayPath, siblingOverlayPath);
    assert.deepEqual(plan.composeFiles, [
      join(siblingOverlayPath, "docker-compose.openmatescloud.yml"),
      OFFICIAL_CLOUD_NO_WEBAPP_COMPOSE_FILE,
    ]);
    assert.equal(plan.env.OPENMATES_CLOUD_OVERLAY_ENABLED, "true");
    assert.equal(plan.env.OPENMATES_CLOUD_OVERLAY_PATH, siblingOverlayPath);
    assert.match(plan.modeLabel, /official cloud overlay/);
    assert.deepEqual(appendOpenMatesCloudComposeFiles(baseArgs, plan), [
      ...baseArgs,
      "-f",
      join(siblingOverlayPath, "docker-compose.openmatescloud.yml"),
      "-f",
      OFFICIAL_CLOUD_NO_WEBAPP_COMPOSE_FILE,
    ]);
  });

  it("plans real Docker compose args with official-cloud overlay included", () => {
    const args = planDockerComposeArgs({
      openMatesPath,
      installMode: "source",
      deploymentMode: "official_cloud",
      overlayExists: true,
    });

    assert.deepEqual(args, [
      "compose", "--env-file", ".env",
      "-f", join("backend", "core", "docker-compose.yml"),
      "-f", join(siblingOverlayPath, "docker-compose.openmatescloud.yml"),
      "-f", OFFICIAL_CLOUD_NO_WEBAPP_COMPOSE_FILE,
    ]);
  });

  it("keeps regular self-host Docker compose args on the base core stack", () => {
    const args = planDockerComposeArgs({
      openMatesPath,
      installMode: "image",
      deploymentMode: "self_host",
      overlayExists: false,
    });

    assert.deepEqual(args, [
      "compose", "--env-file", ".env",
      "-f", join("backend", "core", "docker-compose.selfhost.yml"),
    ]);
  });

  it("requires the overlay path for official-cloud mode", () => {
    assert.throws(
      () => planOpenMatesCloudOverlay({
        deploymentMode: "official_cloud",
        openMatesPath,
        overlayExists: false,
      }),
      /OpenMatesCloud overlay path is required/,
    );
  });
});

describe("feature override config", () => {
  it("migrates legacy disabled_apps into feature_overrides.disabled", () => {
    const content = `# config\ndisabled_apps:\n  - "images"\n  - videos\nfeature_overrides:\n  enabled:\n    - "embed:code:application"\n  disabled:\n    - "app:web"\n`;

    const overrides = parseFeatureOverrides(content);

    assert.deepEqual(overrides.enabled, ["embed:code:application"]);
    assert.deepEqual(overrides.disabled, ["app:web", "app:images", "app:videos"]);
  });

  it("writes deterministic feature_overrides and removes legacy disabled_apps", () => {
    const content = `logging:\n  level: INFO\n\ndisabled_apps:\n  - videos\n`;
    const next = updateFeatureOverridesContent(content, {
      enabled: ["embed:code:application"],
      disabled: ["app:videos", "platform:projects"],
    });

    assert.match(next, /feature_overrides:\n {2}enabled:\n {4}- "embed:code:application"\n {2}disabled:\n {4}- "app:videos"\n {4}- "platform:projects"/);
    assert.doesNotMatch(next, /disabled_apps:/);
  });

  it("supports enable disable reset list updates", () => {
    const initial = parseFeatureOverrides(`feature_overrides:\n  enabled: []\n  disabled:\n    - "app:videos"\n`);
    const enabled = {
      enabled: normalizeFeatureList([...initial.enabled, "app:videos"]),
      disabled: initial.disabled.filter((id) => id !== "app:videos"),
    };
    const disabled = {
      enabled: enabled.enabled.filter((id) => id !== "platform:projects"),
      disabled: normalizeFeatureList([...enabled.disabled, "platform:projects"]),
    };
    const reset = {
      enabled: disabled.enabled.filter((id) => id !== "app:videos"),
      disabled: disabled.disabled.filter((id) => id !== "app:videos"),
    };

    assert.deepEqual(enabled, { enabled: ["app:videos"], disabled: [] });
    assert.deepEqual(disabled, { enabled: ["app:videos"], disabled: ["platform:projects"] });
    assert.deepEqual(reset, { enabled: [], disabled: ["platform:projects"] });
  });
});

describe("image-mode update planning", () => {
  it("updates default version-pinned installs to the current CLI version tag", () => {
    const target = resolveTargetImageTag({}, "v0.13.0", "0.13.0");
    assert.deepEqual(target, { tag: "v0.13.0" });
  });

  it("preserves installed channel tags when no explicit target is provided", () => {
    assert.deepEqual(resolveTargetImageTag({}, "dev", "0.13.0"), { tag: "dev", channel: "dev" });
    assert.deepEqual(resolveTargetImageTag({}, "main", "0.13.0"), { tag: "main", channel: "main" });
  });

  it("maps stable channel to the published main image tag", () => {
    const target = resolveTargetImageTag({ channel: "stable" }, "v0.13.0", "0.13.0");
    assert.deepEqual(target, { tag: "main", channel: "main" });
  });

  it("rejects ambiguous image tag and channel combinations", () => {
    assert.throws(
      () => resolveTargetImageTag({ "image-tag": "v0.13.0", channel: "dev" }, "v0.13.0", "0.13.0"),
      /either --image-tag or --channel/,
    );
  });

  it("rejects missing image tag and channel values", () => {
    assert.throws(
      () => resolveTargetImageTag({ "image-tag": true }, "v0.13.0", "0.13.0"),
      /--image-tag <tag>/,
    );
    assert.throws(
      () => resolveTargetImageTag({ channel: true }, "v0.13.0", "0.13.0"),
      /--channel stable/,
    );
  });

  it("uses dev templates for prerelease and smoke tags", () => {
    assert.equal(templateRefForImageTag("v0.13.0-alpha.0"), "dev");
    assert.equal(templateRefForImageTag("selfhost-smoke-abc123"), "dev");
  });

  it("uses release and channel template refs where available", () => {
    assert.equal(templateRefForImageTag("v0.13.0"), "v0.13.0");
    assert.equal(templateRefForImageTag("main"), "main");
    assert.equal(templateRefForImageTag("stable"), "main");
  });
});

describe("role-based server planning", () => {
  it("parses supported roles and rejects unknown roles", () => {
    assert.equal(parseServerRole(undefined), "core");
    assert.equal(parseServerRole("core"), "core");
    assert.equal(parseServerRole("upload"), "upload");
    assert.equal(parseServerRole("preview"), "preview");
    assert.throws(() => parseServerRole("worker"), /Unsupported server role/);
  });

  it("resolves core observability profiles and alert opt-in", () => {
    assert.deepEqual(planServerRuntime({ role: "core", profile: "minimal" }).profileServices, []);
    assert.deepEqual(planServerRuntime({ role: "core", profile: "standard" }).profileServices, ["openobserve", "promtail"]);
    assert.deepEqual(planServerRuntime({ role: "core", profile: "production" }).profileServices, ["openobserve", "promtail", "prometheus", "cadvisor", "node-exporter"]);
    assert.ok(planServerRuntime({ role: "core", profile: "production", withAlerts: true }).profileServices.includes("alertmanager"));
    assert.ok(planServerRuntime({ role: "core", profile: "production" }).defaultServices.includes("node-exporter"));
    assert.ok(planServerRuntime({ role: "core", profile: "production" }).defaultServices.includes("workflow-worker"));
    assert.equal(planServerRuntime({ role: "core", profile: "production", includeWebapp: false }).defaultServices.includes("webapp"), false);
    assert.equal(planServerRuntime({ role: "core", profile: "production" }).defaultServices.includes("webapp"), true);
  });

  it("validates role-specific service selections before Docker is called", () => {
    assert.deepEqual(resolveServiceSelection("core", { services: "api,task-worker" }), ["api", "task-worker"]);
    assert.deepEqual(resolveServiceSelection("core", { exclude: "webapp" }).includes("webapp"), false);
    assert.deepEqual(resolveServiceSelection("upload", { services: "app-uploads,admin-sidecar" }), ["app-uploads", "admin-sidecar"]);
    assert.throws(() => resolveServiceSelection("preview", { services: "app-uploads" }), /Invalid service/);
  });

  it("applies service filters to update commands and web health checks", () => {
    const services = resolveServiceSelection("core", { exclude: "webapp" });

    const buildArgs = appendSelectedServices(["docker", "compose", "build"], services, true);
    const upArgs = appendSelectedServices(["docker", "compose", "up", "-d"], services, true);

    assert.equal(buildArgs.includes("webapp"), false);
    assert.equal(upArgs.includes("webapp"), false);
    assert.ok(buildArgs.includes("api"));
    assert.ok(upArgs.includes("api"));
    assert.equal(shouldCheckWebHealth({ role: "core", selectedServices: services, filterRequested: true }), false);
    assert.equal(shouldCheckWebHealth({ role: "core", selectedServices: ["api", "webapp"], filterRequested: true }), true);
    assert.equal(shouldCheckWebHealth({ role: "core", deploymentMode: "official_cloud", filterRequested: false }), false);
    assert.equal(shouldCheckWebHealth({ role: "core", filterRequested: false }), true);
    assert.equal(shouldCheckWebHealth({ role: "upload", filterRequested: false }), false);
  });

  it("plans image updates with backup before pull/up and without git", () => {
    const plan = planUpdate({ role: "core", selectedServices: ["api"], dryRun: true });
    assert.deepEqual(plan.steps, ["preflight", "backup:latest-pre-update", "pull", "up", "health-check"]);
    assert.equal(plan.commands.some((command) => command.includes("git pull")), false);
    assert.equal(plan.backupName, "latest-pre-update-core.tar.gz");
  });

  it("keeps packaged core compose aligned with planned image-mode services", () => {
    const template = readFileSync(new URL("../templates/core/docker-compose.selfhost.yml", import.meta.url), "utf-8");
    const plan = planServerRuntime({ role: "core", profile: "production" });

    for (const service of plan.defaultServices) {
      assert.ok(template.includes(`\n  ${service}:`), `missing ${service} in packaged core compose template`);
    }
  });

  it("wires packaged core Promtail to generated config and required log sources", () => {
    const template = readFileSync(new URL("../templates/core/docker-compose.selfhost.yml", import.meta.url), "utf-8");
    const promtailBlock = template.match(/\n {2}promtail:\n([\s\S]*?)(?=\n {2}[a-zA-Z0-9_-]+:|\nnetworks:)/)?.[1] ?? "";
    const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf-8");

    assert.match(promtailBlock, /env_file: \.\.\/\.\.\/\.env/);
    assert.match(promtailBlock, /\.\/monitoring\/promtail:\/etc\/promtail:ro/);
    assert.match(promtailBlock, /\/var\/run\/docker\.sock:\/var\/run\/docker\.sock:ro/);
    assert.match(promtailBlock, /api-logs:\/var\/log\/api:ro/);
    assert.match(promtailBlock, /-config\.file=\/etc\/promtail\/promtail-config\.yaml/);
    assert.match(source, /CORE_PROMTAIL_CONFIG_FILE = join\("backend", "core", "monitoring", "promtail", "promtail-config\.yaml"\)/);
    assert.match(source, /writeFileSync\(promtailConfigPath, SELFHOST_PROMTAIL_CONFIG_TEMPLATE\)/);
  });

  it("packages Alertmanager config for image installs and updates", () => {
    const packaged = readFileSync(new URL("../templates/core/monitoring/alertmanager/alertmanager.yml", import.meta.url), "utf-8");
    const canonical = readFileSync(new URL("../../../../backend/core/monitoring/alertmanager/alertmanager.yml", import.meta.url), "utf-8");
    const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf-8");

    assert.deepEqual(parseYaml(packaged), parseYaml(canonical));
    assert.match(source, /CORE_ALERTMANAGER_CONFIG_FILE = join\("backend", "core", "monitoring", "alertmanager", "alertmanager\.yml"\)/);
    assert.match(source, /copyFileSync\(alertmanagerTemplatePath, alertmanagerConfigPath\)/);
    assert.match(source, /version: value\("OPENMATES_IMAGE_TAG"\) \|\| serverConfig\?\.imageTag \|\| "source"/);
  });

  it("keeps packaged core task workers wired to Vault and config volumes", () => {
    const template = readFileSync(new URL("../templates/core/docker-compose.selfhost.yml", import.meta.url), "utf-8");
    const baseBlock = template.slice(
      template.indexOf("x-openmates-worker-base:"),
      template.indexOf("services:")
    );
    const serviceBlock = (service: string) => {
      const match = template.match(new RegExp(`\\n  ${service}:\\n([\\s\\S]*?)(?=\\n  [a-zA-Z0-9_-]+:|\\nvolumes:)`));
      assert.ok(match, `missing ${service} service block`);
      return match[1];
    };

    assert.match(baseBlock, /VAULT_URL: http:\/\/vault:8200/, "worker base must include Vault URL");
    assert.match(baseBlock, /vault-setup-data:\/vault-data/, "worker base must mount Vault token data");
    assert.match(baseBlock, /\.\.\/\.\.\/config:\/app_config/, "worker base must mount provider config");

    for (const service of ["task-worker", "reminder-worker", "task-scheduler"]) {
      const block = serviceBlock(service);
      assert.match(block, /<<: \*openmates-worker-base/, `${service} must inherit worker base`);
    }

    const schedulerBlock = serviceBlock("task-scheduler");
    assert.match(schedulerBlock, /vault-setup-data:\/vault-data/, "task-scheduler must keep Vault mount when adding beat volume");
    assert.match(schedulerBlock, /\.\.\/\.\.\/config:\/app_config/, "task-scheduler must keep provider config mount when adding beat volume");
  });

  it("uses an ARM-compatible ClamAV image in the packaged upload template", () => {
    const template = readFileSync(new URL("../templates/upload/docker-compose.yml", import.meta.url), "utf-8");

    assert.match(template, /image: clamav\/clamav-debian:stable/);
  });

  it("streams Postgres backups instead of buffering pg_dump in memory", () => {
    const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf-8");

    assert.match(source, /spawnSync\(\s*"docker"/);
    assert.match(source, /stdio: \["ignore", dumpFile, "pipe"\]/);
    assert.doesNotMatch(source, /const dump = execSync\(\s*`docker exec cms-database pg_dump/);
  });

  it("hashes backup files in chunks instead of reading whole files into memory", () => {
    const source = readFileSync(new URL("../src/server.ts", import.meta.url), "utf-8");
    const backupChecksumSource = source.slice(source.indexOf("function hashFile"), source.indexOf("function createServerBackup"));

    assert.match(backupChecksumSource, /function hashFile\(path: string\): string/);
    assert.match(backupChecksumSource, /readSync\(fd, buffer/);
    assert.doesNotMatch(backupChecksumSource, /createHash\("sha256"\)\.update\(readFileSync\(path\)\)/);
    assert.doesNotMatch(backupChecksumSource, /createHash\("sha256"\)\.update\(readFileSync\(filePath\)\)/);
  });

  it("plans backup and restore content safely", () => {
    const backup = planBackup({ role: "core", includeObservability: true });
    assert.ok(backup.contents.includes("postgres-dump"));
    assert.ok(backup.contents.includes("vault-data"));
    assert.ok(backup.contents.includes("openobserve-data"));

    const restore = planRestore({ role: "core", file: "/tmp/backup.tar.gz", yes: false });
    assert.equal(restore.requiresConfirmation, true);
    assert.deepEqual(restore.steps, ["confirm", "stop", "restore", "start", "health-check"]);
  });

  it("prefers packaged templates before GitHub raw fallback", () => {
    assert.deepEqual(resolveTemplateSource({ role: "core", packagedTemplateExists: true }), {
      type: "packaged",
      path: "templates/core/docker-compose.selfhost.yml",
    });
    assert.equal(resolveTemplateSource({ role: "core", packagedTemplateExists: false, templateRef: "dev" }).type, "github-raw");
  });
});

describe("server log args", () => {
  it("keeps the existing default tail for unbounded log reads", () => {
    assert.deepEqual(planServerLogRangeArgs({}), ["--tail", "100"]);
  });

  it("passes --since through without applying the default tail cap", () => {
    assert.deepEqual(planServerLogRangeArgs({ since: "10m" }), ["--since", "10m"]);
  });

  it("combines explicit --since and --tail filters", () => {
    assert.deepEqual(planServerLogRangeArgs({ since: "2026-08-22T10:00:00Z", tail: "200" }), [
      "--since", "2026-08-22T10:00:00Z", "--tail", "200",
    ]);
  });

  it("rejects missing --since and --tail values", () => {
    assert.throws(() => planServerLogRangeArgs({ since: true }), /Provide a since value/);
    assert.throws(() => planServerLogRangeArgs({ tail: true }), /Provide a tail value/);
  });
});

describe("server preflight and Caddy planning", () => {
  it("reports newly required secrets and ignores no_api_key providers", () => {
    const missing = findMissingRequiredSecrets({
      installed: [
        { id: "legacy", envKey: "SECRET__LEGACY__API_KEY", required: true },
      ],
      target: [
        { id: "legacy", envKey: "SECRET__LEGACY__API_KEY", required: true },
        { id: "new-required", envKey: "SECRET__NEW_REQUIRED__API_KEY", required: true },
        { id: "free-local", envKey: "SECRET__FREE_LOCAL__API_KEY", required: true, noApiKey: true },
      ],
      configuredEnvKeys: ["SECRET__LEGACY__API_KEY"],
    });

    assert.deepEqual(missing, ["SECRET__NEW_REQUIRED__API_KEY"]);
  });

  it("maps SECRET env keys to Vault provider paths", () => {
    assert.deepEqual(parseSecretEnvKey("SECRET__OPENAI__API_KEY"), {
      envKey: "SECRET__OPENAI__API_KEY",
      vaultPath: "kv/data/providers/openai",
      vaultKey: "api_key",
    });
    assert.equal(parseSecretEnvKey("DIRECTUS_TOKEN"), null);
    assert.equal(parseSecretEnvKey("SECRET__BROKEN"), null);
  });

  it("summarizes inline, empty, imported, and missing Vault secrets", () => {
    const summary = summarizeSecretPreflight({
      env: {
        SECRET__OPENAI__API_KEY: "IMPORTED_TO_VAULT",
        SECRET__ANTHROPIC__API_KEY: "sk-ant-inline",
        SECRET__BRAVE__API_KEY: "",
        SECRET__FIRECRAWL__API_KEY: "IMPORTED_TO_VAULT",
        DATABASE_PASSWORD: "kept-in-env",
      },
      vaultPresence: {
        SECRET__OPENAI__API_KEY: "present",
        SECRET__FIRECRAWL__API_KEY: "missing",
      },
    });

    assert.deepEqual(summary.importedSecretEnvKeys, ["SECRET__FIRECRAWL__API_KEY", "SECRET__OPENAI__API_KEY"]);
    assert.deepEqual(summary.importedVaultPresent, ["SECRET__OPENAI__API_KEY"]);
    assert.deepEqual(summary.importedVaultMissing, ["SECRET__FIRECRAWL__API_KEY"]);
    assert.deepEqual(summary.inlineSecretEnvKeys, ["SECRET__ANTHROPIC__API_KEY"]);
    assert.deepEqual(summary.emptySecretEnvKeys, ["SECRET__BRAVE__API_KEY"]);
  });

  it("blocks continuous update plans when required secrets are missing", () => {
    const plan = planUpdate({ role: "core", selectedServices: ["api"], continuous: true, missingRequiredSecrets: ["SECRET__OPENAI__API_KEY"] });
    assert.equal(plan.blocked, true);
    assert.match(plan.blockReason ?? "", /missing required secrets/i);
  });

  it("plans host-level Caddy check, status, diff, and apply safely", () => {
    assert.deepEqual(planCaddyCommand({ role: "core", action: "check" }).steps, ["render-template", "validate"]);
    assert.deepEqual(planCaddyCommand({ role: "upload", action: "status" }).steps, ["hash-template", "hash-applied", "validate"]);
    assert.deepEqual(planCaddyCommand({ role: "preview", action: "diff" }).steps, ["hash-template", "hash-applied", "diff"]);
    assert.deepEqual(planCaddyCommand({ role: "core", action: "apply" }).steps, ["render-template", "validate", "backup-applied", "write", "reload"]);
  });

  it("renders continuous updater systemd plans without secrets", () => {
    const plan = planContinuousUpdateService({ role: "core", channel: "main", window: "02:00-04:00 Europe/Berlin" });

    assert.equal(plan.serviceName, "openmates-core-continuous-update.service");
    assert.equal(plan.timerName, "openmates-core-continuous-update.timer");
    assert.match(plan.unit, /openmates server update --role core --channel main --continuous/);
    assert.match(plan.unit, /OPENMATES_UPDATE_WINDOW=02:00-04:00 Europe\/Berlin/);
    assert.doesNotMatch(plan.unit + plan.timer, /SECRET__|API_KEY|TOKEN=/);
  });

  it("parses env entries by category with redacted secret values", () => {
    const entries = parseEnvEntries([
      "DATABASE_NAME=directus",
      "SECRET__BRAVE__API_KEY=sk-brave",
      "SECRET__GOOGLE__OAUTH_CLIENT_ID=client-id",
      "OPENOBSERVE_ROOT_PASSWORD=secret",
      "APP_AI_WORKER_CONCURRENCY=3",
    ].join("\n"));

    assert.deepEqual(entries.map((entry) => [entry.key, entry.category, entry.redactedValue]), [
      ["APP_AI_WORKER_CONCURRENCY", "advanced", "3"],
      ["SECRET__GOOGLE__OAUTH_CLIENT_ID", "integrations", "<redacted>"],
      ["OPENOBSERVE_ROOT_PASSWORD", "observability", "<redacted>"],
      ["SECRET__BRAVE__API_KEY", "providers", "<redacted>"],
      ["DATABASE_NAME", "runtime", "directus"],
    ]);
    assert.equal(redactEnvValue("SECRET__OPENAI__API_KEY", "IMPORTED_TO_VAULT"), "IMPORTED_TO_VAULT");
  });

  it("updates and unsets one canonical env file without exposing other values", () => {
    const initial = "DATABASE_NAME=directus\nSECRET__BRAVE__API_KEY=old\n";

    const updated = upsertEnvValue(initial, "SECRET__BRAVE__API_KEY", "new-secret");
    const added = upsertEnvValue(updated, "SECRET__FIRECRAWL__API_KEY", "firecrawl-secret");
    const removed = unsetEnvValue(added, "SECRET__BRAVE__API_KEY");

    assert.match(updated, /SECRET__BRAVE__API_KEY=new-secret/);
    assert.match(added, /SECRET__FIRECRAWL__API_KEY=firecrawl-secret/);
    assert.doesNotMatch(removed, /SECRET__BRAVE__API_KEY=/);
    assert.match(removed, /DATABASE_NAME=directus/);
  });
});

describe("post-update runtime health", () => {
  it("fails closed to self-host for missing, malformed, duplicate, and conflicting mode", () => {
    for (const envText of [
      "",
      "OPENMATES_DEPLOYMENT_MODE=cloud\n",
      "OPENMATES_DEPLOYMENT_MODE=OFFICIAL_CLOUD\n",
      "OPENMATES_DEPLOYMENT_MODE=official_cloud\nOPENMATES_DEPLOYMENT_MODE=self_host\n",
      "OPENMATES_DEPLOYMENT_MODE=official_cloud\nOPENMATES_CLOUD_OVERLAY_ENABLED=false\n",
    ]) {
      const result = resolveRuntimeDeploymentMode({ envText, overlayExists: true });
      assert.equal(result.effectiveMode, "self_host");
      assert.equal(result.billingEnabled, false);
    }
  });

  it("omits billing checks for self-host inventories", () => {
    const checks = buildRuntimeCheckInventory("core", "self_host");
    const schedulerCheck = checks.find((check) => check.id === "core.scheduler_freshness");
    assert.ok(checks.some((check) => check.id === "core.chat_plumbing"));
    assert.equal(checks.some((check) => check.id.startsWith("billing.")), false);
    assert.ok(checks.every((check) => check.timeoutSeconds > 0 && check.timeoutSeconds <= 60));
    assert.equal(schedulerCheck?.timeoutSeconds, 15);
  });

  it("uses one bounded parallel verification plan and reports restore availability", () => {
    const withBackup = planRuntimeVerification({ role: "core", deploymentMode: "self_host", hasVerifiedBackup: true });
    const withoutBackup = planRuntimeVerification({ role: "core", deploymentMode: "self_host", hasVerifiedBackup: false });

    assert.equal(withBackup.globalDeadlineSeconds, 60);
    assert.deepEqual(withBackup.phases[0].checkIds, ["compose.required_services", "http.role_health"]);
    assert.equal(withBackup.restoreStatus, "available");
    assert.match(withBackup.restoreCommand ?? "", /openmates server restore --role core/);
    assert.equal(withoutBackup.restoreStatus, "restore_unavailable");
    assert.equal(withoutBackup.restoreCommand, null);
  });

  it("renders an idempotent secret-free runtime monitor service and timer", () => {
    const plan = planRuntimeMonitoringServices({ role: "core", installPath: "/srv/openmates" });

    assert.equal(plan.serviceName, "openmates-core-runtime-monitor.service");
    assert.equal(plan.timerName, "openmates-core-runtime-monitor.timer");
    assert.match(plan.timer, /Persistent=true/);
    assert.match(plan.unit, /server monitoring run --role core/);
    assert.doesNotMatch(plan.unit + plan.timer, /SECRET__|API_KEY|TOKEN=/);
  });

  it("requires an explicit environment opt-out to skip automatic runtime monitor service installation", () => {
    assert.equal(shouldAutoInstallRuntimeMonitoringServices({}), true);
    assert.equal(shouldAutoInstallRuntimeMonitoringServices({ OPENMATES_SKIP_RUNTIME_MONITORING: "0" }), true);
    assert.equal(shouldAutoInstallRuntimeMonitoringServices({ OPENMATES_SKIP_RUNTIME_MONITORING: "1" }), false);
  });

  it("alerts on the second transient failure, deduplicates, then recovers", () => {
    const first = applyRuntimeCheckResults(undefined, [{ id: "core.cache", status: "failed", failureClass: "connection" }], "2026-08-06T10:00:00Z");
    const second = applyRuntimeCheckResults(first.state, [{ id: "core.cache", status: "failed", failureClass: "connection" }], "2026-08-06T10:05:00Z");
    const repeated = applyRuntimeCheckResults(second.state, [{ id: "core.cache", status: "failed", failureClass: "connection" }], "2026-08-06T10:10:00Z");
    const recovered = applyRuntimeCheckResults(repeated.state, [{ id: "core.cache", status: "passed" }], "2026-08-06T10:15:00Z");

    assert.deepEqual(first.events, []);
    assert.equal(second.events[0]?.type, "service_unhealthy");
    assert.deepEqual(repeated.events, []);
    assert.equal(recovered.events[0]?.type, "recovered");
  });

  // contract-test: direct surface=cli assertions=storage-resilience.monitoring.transition-alerts,storage-resilience.content.privacy-boundary
  it("warns once, escalates storage after one hour, and resolves once", () => {
    const failure = [{ id: "core.object_storage", status: "failed" as const, failureClass: "storage_unavailable" }];
    const first = applyRuntimeCheckResults(undefined, failure, "2026-08-25T10:00:00Z");
    const warning = applyRuntimeCheckResults(first.state, failure, "2026-08-25T10:05:00Z");
    const beforeCritical = applyRuntimeCheckResults(warning.state, failure, "2026-08-25T11:04:59Z");
    const critical = applyRuntimeCheckResults(beforeCritical.state, failure, "2026-08-25T11:05:00Z");
    const repeated = applyRuntimeCheckResults(critical.state, failure, "2026-08-25T12:05:00Z");
    const recovered = applyRuntimeCheckResults(
      repeated.state,
      [{ id: "core.object_storage", status: "passed" }],
      "2026-08-25T12:10:00Z",
    );
    const healthy = applyRuntimeCheckResults(
      recovered.state,
      [{ id: "core.object_storage", status: "passed" }],
      "2026-08-25T12:15:00Z",
    );

    assert.deepEqual(first.events, []);
    assert.equal(warning.events[0]?.type, "service_unhealthy");
    assert.deepEqual(beforeCritical.events, []);
    assert.equal(critical.events[0]?.type, "service_critical");
    assert.deepEqual(repeated.events, []);
    assert.equal(recovered.events[0]?.type, "recovered");
    assert.deepEqual(healthy.events, []);
  });

  // contract-test: direct surface=cli assertions=storage-resilience.monitoring.not-configured
  it("does not open a storage incident when storage is intentionally unconfigured", () => {
    const skipped = [{ id: "core.object_storage", status: "skipped" as const, failureClass: "not_configured" }];
    const first = applyRuntimeCheckResults(undefined, skipped, "2026-08-25T10:00:00Z");
    const second = applyRuntimeCheckResults(first.state, skipped, "2026-08-25T10:05:00Z");

    assert.deepEqual(first.events, []);
    assert.deepEqual(second.events, []);
    assert.equal(second.state.checks?.["core.object_storage"]?.incidentOpen, false);
  });

  // contract-test: direct surface=cli assertions=storage-resilience.monitoring.transition-alerts
  it("preserves every simultaneous warning critical and recovery event", () => {
    const state = {
      consecutiveFailures: 2,
      incidentOpen: true,
      checks: {
        "core.object_storage": {
          consecutiveFailures: 2,
          incidentOpen: true,
          incidentOpenedAt: "2026-08-25T10:00:00Z",
        },
        "core.cache": {
          consecutiveFailures: 1,
          incidentOpen: false,
        },
      },
    };
    const failed = applyRuntimeCheckResults(state, [
      { id: "core.object_storage", status: "failed", failureClass: "storage_unavailable", required: false },
      { id: "core.cache", status: "failed", failureClass: "connection", required: true },
    ], "2026-08-25T11:00:00Z");
    const recovered = applyRuntimeCheckResults(failed.state, [
      { id: "core.object_storage", status: "passed", required: false },
      { id: "core.cache", status: "passed", required: true },
    ], "2026-08-25T11:05:00Z");

    assert.deepEqual(failed.events.map((event) => event.type), ["service_critical", "service_unhealthy"]);
    assert.deepEqual(recovered.events.map((event) => event.type), ["recovered", "recovered"]);
    const serverSource = readFileSync(new URL("../src/server.ts", import.meta.url), "utf8");
    assert.doesNotMatch(serverSource, /applied\.events\[0\]/);
  });

  // contract-test: direct surface=cli assertions=storage-resilience.monitoring.transition-alerts
  it("does not infer a storage outage when a required baseline prevents the optional probe", () => {
    const first = applyRuntimeCheckResults(undefined, [{
      id: "core.object_storage",
      status: "skipped",
      failureClass: "dependency_failed",
      required: false,
    }], "2026-08-25T10:00:00Z");
    const second = applyRuntimeCheckResults(first.state, [{
      id: "core.object_storage",
      status: "skipped",
      failureClass: "dependency_failed",
      required: false,
    }], "2026-08-25T10:05:00Z");

    assert.deepEqual(first.events, []);
    assert.deepEqual(second.events, []);
    assert.equal(second.state.incidentOpen, false);
  });

  it("alerts immediately when the runtime verifier container is unavailable", () => {
    const result = applyRuntimeCheckResults(
      undefined,
      [{ id: "core.runtime_verifier_available", status: "failed", failureClass: "critical_availability" }],
      "2026-08-06T10:00:00Z",
    );

    assert.equal(result.events[0]?.type, "service_unhealthy");
    assert.equal(result.state.checks?.["core.runtime_verifier_available"]?.incidentOpen, true);
  });

  it("tracks failure thresholds per check instead of combining unrelated failures", () => {
    const first = applyRuntimeCheckResults(undefined, [{ id: "core.cache", status: "failed", failureClass: "connection" }], "2026-08-06T10:00:00Z");
    const unrelated = applyRuntimeCheckResults(first.state, [{ id: "core.database", status: "failed", failureClass: "connection" }], "2026-08-06T10:05:00Z");

    assert.deepEqual(unrelated.events, []);
    assert.equal(unrelated.state.checks?.["core.cache"]?.consecutiveFailures, 1);
    assert.equal(unrelated.state.checks?.["core.database"]?.consecutiveFailures, 1);
  });

  it("signs canonical webhook payloads and rejects unsafe destinations", async () => {
    const signed = signRuntimeWebhookPayload({ type: "delivery_test", checkId: "monitor" }, "test-secret", "2026-08-06T10:00:00Z", "event-1");
    assert.match(signed.headers["X-OpenMates-Signature"], /^sha256=/);
    assert.equal(signed.headers["X-OpenMates-Event-Id"], "event-1");

    await assert.rejects(() => validateRuntimeWebhookDestination("http://example.org/hook", ["93.184.216.34"]));
    await assert.rejects(() => validateRuntimeWebhookDestination("https://example.org/hook", ["127.0.0.1"]));
    await assert.rejects(() => validateRuntimeWebhookDestination("https://example.org/hook", ["169.254.1.1"]));
    await assert.rejects(() => validateRuntimeWebhookDestination("https://example.org/hook", ["::ffff:a00:1"]));
    await assert.rejects(() => validateRuntimeWebhookDestination("https://example.org/hook", ["::a9fe:101"]));
    await assert.doesNotReject(() => validateRuntimeWebhookDestination("https://example.org/hook", ["93.184.216.34"]));
  });
});

describe("operational monitoring digest", () => {
  it("pins Brevo email probes to bounded IPv4 requests", () => {
    const options = buildBrevoRequestOptions("/v3/account", "GET", "test-key");
    assert.equal(options.protocol, "https:");
    assert.equal(options.hostname, "api.brevo.com");
    assert.equal(options.servername, "api.brevo.com");
    assert.equal(options.port, 443);
    assert.equal(options.path, "/v3/account");
    assert.equal(options.method, "GET");
    assert.equal(options.family, 4);
    assert.equal(options.timeout, 10_000);
    assert.equal((options.headers as Record<string, string>)["api-key"], "test-key");
  });

  // contract-test: direct surface=cli assertions=operational-monitoring.self-host.auto-email,operational-monitoring.self-host.no-billing,operational-monitoring.environments.isolated-labeled
  it("activates self-host email only with an admin recipient and available service", () => {
    const active = planOperationalMonitoring({
      environment: "self_host",
      role: "core",
      installPath: "/srv/openmates",
      adminEmail: "admin@example.test",
      emailServiceAvailable: true,
      discordConfigured: false,
    });
    const missingRecipient = planOperationalMonitoring({
      environment: "self_host",
      role: "core",
      installPath: "/srv/openmates",
      emailServiceAvailable: true,
      discordConfigured: false,
    });
    const unavailableService = planOperationalMonitoring({
      environment: "self_host",
      role: "core",
      installPath: "/srv/openmates",
      adminEmail: "admin@example.test",
      emailServiceAvailable: false,
      discordConfigured: false,
    });

    assert.equal(active.emailEnabled, true);
    assert.equal(active.scheduleEnabled, true);
    assert.equal(missingRecipient.emailEnabled, false);
    assert.equal(missingRecipient.configurationStatus, "missing_admin_email");
    assert.equal(unavailableService.emailEnabled, false);
    assert.equal(unavailableService.configurationStatus, "email_service_unavailable");
    assert.match(active.digestUnit, /--channel email(?:\s|$)/);

    const serialized = JSON.stringify(active).toLowerCase();
    for (const forbidden of ["billing", "payment", "stripe", "invoice", "subscription", "purchase"]) {
      assert.equal(serialized.includes(forbidden), false);
    }
  });

  // contract-test: direct surface=cli assertions=operational-monitoring.self-host.auto-email,operational-monitoring.delivery.observable
  it("renders idempotent digest and stale-watchdog systemd plans", () => {
    const first = planOperationalMonitoring({
      environment: "self_host",
      role: "core",
      installPath: "/srv/openmates",
      adminEmail: "admin@example.test",
      emailServiceAvailable: true,
      discordConfigured: true,
    });
    const second = planOperationalMonitoring({
      environment: "self_host",
      role: "core",
      installPath: "/srv/openmates",
      adminEmail: "admin@example.test",
      emailServiceAvailable: true,
      discordConfigured: true,
    });

    assert.deepEqual(first, second);
    assert.match(first.digestTimer, /Persistent=true/);
    assert.match(first.digestUnit, /server monitoring digest/);
    assert.match(first.watchdogUnit, /server monitoring report-watchdog/);
    assert.doesNotMatch(first.digestUnit + first.watchdogUnit, /admin@example\.test|SECRET__|API_KEY|TOKEN=/);
  });

  // contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable,operational-monitoring.alerts.independent-urgent-path
  it("detects stale reports once and recovers after a fresh accepted report", () => {
    const grace = evaluateOperationalReportFreshness(
      { incidentOpen: false, monitoringStartedAt: "2026-08-14T11:00:00Z" },
      new Date("2026-08-14T12:00:00Z"),
    );
    const stale = evaluateOperationalReportFreshness(
      { incidentOpen: false, monitoringStartedAt: "2026-08-13T09:00:00Z" },
      new Date("2026-08-14T12:00:00Z"),
    );
    const repeated = evaluateOperationalReportFreshness(stale.state, new Date("2026-08-14T12:05:00Z"));
    const recovered = evaluateOperationalReportFreshness(
      { ...repeated.state, lastAcceptedReportAt: "2026-08-14T12:06:00Z" },
      new Date("2026-08-14T12:07:00Z"),
    );

    assert.equal(grace.event, null);
    assert.equal(stale.event?.type, "operational_report_stale");
    assert.equal(repeated.event, null);
    assert.equal(recovered.event?.type, "operational_report_recovered");
  });

  // contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable,operational-monitoring.environments.isolated-labeled
  it("keeps per-channel accepted and failed receipts without destinations", () => {
    const email = buildOperationalDeliveryReceipt({
      environment: "development",
      reportId: "report-1",
      reportSha256: "abc123",
      channel: "email",
      state: "accepted",
      attemptCount: 1,
      occurredAt: "2026-08-14T12:00:00Z",
    });
    const discord = buildOperationalDeliveryReceipt({
      environment: "development",
      reportId: "report-1",
      reportSha256: "abc123",
      channel: "discord",
      state: "failed",
      attemptCount: 3,
      occurredAt: "2026-08-14T12:00:00Z",
      sanitizedFailureClass: "delivery_timeout",
      destinationSource: "dev_fallback",
      fallbackUsed: true,
    });

    assert.equal(email.state, "accepted");
    assert.equal(discord.state, "failed");
    assert.equal("destination" in email, false);
    assert.equal("webhookUrl" in discord, false);
    assert.equal(discord.destinationSource, "dev_fallback");
    assert.equal(discord.fallbackUsed, true);
  });
});

describe("server update completion email", () => {
  // contract-test: direct surface=cli assertions=server-management.update.completion-email-required,server-management.status.privacy-boundary
  it("renders released update metadata and prefers release provenance", () => {
    const source = selectUpdateSourceLink({
      releaseUrl: "https://github.com/glowingkitty/OpenMates/releases/tag/v0.17.0",
      pullRequestUrl: "https://github.com/glowingkitty/OpenMates/pull/123",
      commitUrl: "https://github.com/glowingkitty/OpenMates/commit/abc123",
      sourceUrl: "https://github.com/glowingkitty/OpenMates/tree/v0.17.0",
    });
    const email = buildUpdateCompletionEmail({
      deliveryId: "11111111-1111-4111-8111-111111111111",
      updateMode: "image",
      installedVersion: "v0.17.0",
      role: "core",
      completedAt: "2026-08-25T12:00:00Z",
      source,
    });

    assert.deepEqual(source, {
      kind: "release",
      url: "https://github.com/glowingkitty/OpenMates/releases/tag/v0.17.0",
    });
    assert.equal(email.subject, "Server update complete");
    assert.deepEqual(email.headers, { idempotencyKey: "11111111-1111-4111-8111-111111111111" });
    assert.equal(isBrevoIdempotencyDuplicate(400, '{"code":"duplicate_parameter"}', { headers: email.headers }), true);
    assert.equal(isBrevoIdempotencyDuplicate(400, '{"message":"duplicate_parameter"}', { headers: email.headers }), false);
    assert.equal(isBrevoIdempotencyDuplicate(400, '{"code":"duplicate_parameter"}', {}), false);
    assert.equal(isBrevoAcceptedResponse("/v3/smtp/email", "POST", 201, '{"messageId":"<accepted@example.test>"}'), true);
    assert.equal(isBrevoAcceptedResponse("/v3/smtp/email", "POST", 201, "{}"), false);
    assert.equal(isBrevoAcceptedResponse("/v3/smtp/email", "POST", 204, ""), false);
    assert.equal(isBrevoAcceptedResponse("/v3/account", "GET", 200, "{}"), true);
    for (const expected of ["v0.17.0", "core", "2026-08-25T12:00:00Z", source.url]) {
      assert.match(email.textContent, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
  });

  // contract-test: direct surface=cli assertions=server-management.update.completion-email-required
  it("falls back from pull request to commit and source provenance", () => {
    assert.equal(selectUpdateSourceLink({ pullRequestUrl: "https://github.com/glowingkitty/OpenMates/pull/123" })?.kind, "pull_request");
    assert.equal(selectUpdateSourceLink({ commitUrl: "https://github.com/glowingkitty/OpenMates/commit/abc123" })?.kind, "commit");
    assert.equal(selectUpdateSourceLink({ sourceUrl: "https://github.com/glowingkitty/OpenMates/tree/dev" })?.kind, "source");
    assert.equal(selectUpdateSourceLink({ sourceUrl: "https://github.com/private/server/tree/dev" }), null);
    assert.equal(selectUpdateSourceLink({ sourceUrl: "http://github.com/glowingkitty/OpenMates/tree/dev" }), null);
  });

  // contract-test: direct surface=cli assertions=server-management.update.completion-email-required,server-management.status.privacy-boundary
  it("degrades missing and exhausted email delivery without persisting destinations", () => {
    const unavailable = buildUpdateCompletionOutcome({ status: "unavailable", attempts: 0, sanitizedReason: "email_not_configured" });
    const failed = buildUpdateCompletionOutcome({ status: "failed", attempts: 3, sanitizedReason: "delivery_failed" });
    const accepted = buildUpdateCompletionOutcome({ status: "accepted", attempts: 1 });

    assert.deepEqual(unavailable, { updateStatus: "degraded", exitCode: 1, delivery: { status: "unavailable", attempts: 0, sanitizedReason: "email_not_configured" } });
    assert.deepEqual(failed, { updateStatus: "degraded", exitCode: 1, delivery: { status: "failed", attempts: 3, sanitizedReason: "delivery_failed" } });
    assert.deepEqual(accepted, { updateStatus: "success", exitCode: 0, delivery: { status: "accepted", attempts: 1 } });
    assert.equal(JSON.stringify([unavailable, failed, accepted]).includes("admin@example.test"), false);
  });

  // contract-test: direct surface=cli assertions=server-management.update.durable-idempotency
  it("reuses one idempotency identity across bounded delivery retries", async () => {
    const payload = {
      deliveryId: "22222222-2222-4222-8222-222222222222",
      updateMode: "source" as const,
      installedVersion: "abc123",
      role: "core" as const,
      completedAt: "2026-08-25T12:00:00Z",
      source: { kind: "commit" as const, url: "https://github.com/glowingkitty/OpenMates/commit/abc123" },
    };
    const observedIds: string[] = [];
    const delivery = await deliverUpdateCompletionEmail(
      { apiKey: "redacted", from: "sender@example.test", to: "admin@example.test" },
      payload,
      async (_config, attemptPayload) => {
        observedIds.push(attemptPayload.deliveryId);
        if (observedIds.length < 3) throw new Error("ambiguous_timeout");
      },
    );

    assert.deepEqual(delivery, { status: "accepted", attempts: 3 });
    assert.deepEqual(observedIds, [payload.deliveryId, payload.deliveryId, payload.deliveryId]);
  });

  // contract-test: direct surface=cli assertions=server-management.update.durable-idempotency,server-management.update.installation-lock
  it("writes update receipts atomically, fails closed on corruption, and excludes concurrent updates", () => {
    const installPath = join(TEST_STATE_DIR, "update-state");
    writeServerUpdateStatus(installPath, "core", {
      status: "in_progress",
      step: "completion-email",
      completionEmailDeliveryId: "33333333-3333-4333-8333-333333333333",
      completionEmailDelivery: { status: "pending", attempts: 0 },
    });
    const persisted = readServerUpdateStatus(installPath, "core");
    assert.equal(persisted.completionEmailDeliveryId, "33333333-3333-4333-8333-333333333333");
    assert.equal(readdirSync(join(installPath, ".openmates")).some((name) => name.endsWith(".tmp")), false);

    const release = acquireServerUpdateLock(installPath);
    assert.throws(() => acquireServerUpdateLock(installPath), /already running/);
    release();
    assert.doesNotThrow(() => acquireServerUpdateLock(installPath)());
    const lockPath = join(installPath, ".openmates", "server-update.lock");
    writeFileSync(lockPath, "999999999:stale-owner", "utf8");
    assert.throws(() => acquireServerUpdateLock(installPath), /stale.*remove.*explicitly/i);
    assert.equal(readFileSync(lockPath, "utf8"), "999999999:stale-owner");
    rmSync(lockPath);

    writeFileSync(serverUpdateStatusFile(installPath, "core"), "{invalid", "utf8");
    assert.deepEqual(readServerUpdateStatus(installPath, "core"), { statusReadError: "invalid_update_status" });
    for (const invalidShape of ["null", "[]", '"status"', "42"]) {
      writeFileSync(serverUpdateStatusFile(installPath, "core"), invalidShape, "utf8");
      assert.deepEqual(readServerUpdateStatus(installPath, "core"), { statusReadError: "invalid_update_status" });
    }
  });

  // contract-test: direct surface=cli assertions=server-management.update.durable-idempotency
  it("reuses fresh pending receipts and blocks expired or corrupt recovery", () => {
    const base = {
      updateMode: "image" as const,
      installedVersion: "v0.17.0",
      continuousUpdate: false,
      now: new Date("2026-08-25T12:30:00Z"),
    };
    const pending = {
      updateMode: "image",
      installedVersion: "v0.17.0",
      completionEmailDeliveryId: "44444444-4444-4444-8444-444444444444",
      completionEmailPendingAt: "2026-08-25T12:15:00Z",
      completionEmailDelivery: { status: "pending", attempts: 0 },
    };

    assert.deepEqual(planUpdateCompletionDelivery({ ...base, previousStatus: pending }), {
      action: "send",
      deliveryId: pending.completionEmailDeliveryId,
      pendingAt: pending.completionEmailPendingAt,
      previousAttempts: 0,
    });
    assert.deepEqual(planUpdateCompletionDelivery({ ...base, previousStatus: { ...pending, completionEmailPendingAt: "2026-08-25T11:59:59Z" } }), {
      action: "blocked",
      deliveryId: pending.completionEmailDeliveryId,
      pendingAt: "2026-08-25T11:59:59Z",
      reason: "idempotency_window_expired",
    });
    assert.deepEqual(planUpdateCompletionDelivery({ ...base, previousStatus: { statusReadError: "invalid_update_status" } }), {
      action: "blocked",
      reason: "update_status_unreadable",
    });
    const acceptedStatus = {
      ...pending,
      sourceLink: "https://github.com/glowingkitty/OpenMates/releases/tag/v0.17.0",
      completedAt: "2026-08-25T12:20:00Z",
      completionEmailDelivery: { status: "accepted", attempts: 1 },
    };
    assert.deepEqual(planUpdateCompletionDelivery({
      ...base,
      continuousUpdate: true,
      previousStatus: acceptedStatus,
    }), {
      action: "reuse_accepted",
      deliveryId: pending.completionEmailDeliveryId,
      attempts: 1,
    });
    assert.deepEqual(planUpdateCompletionDelivery({
      ...base,
      previousStatus: { ...pending, completionEmailDelivery: { status: "pending", attempts: 1 } },
    }), {
      action: "send",
      deliveryId: pending.completionEmailDeliveryId,
      pendingAt: pending.completionEmailPendingAt,
      previousAttempts: 1,
    });
    assert.deepEqual(planUpdateCompletionDelivery({
      ...base,
      previousStatus: { ...pending, completionEmailDelivery: { status: "failed", attempts: 3 } },
    }), {
      action: "blocked",
      deliveryId: pending.completionEmailDeliveryId,
      pendingAt: pending.completionEmailPendingAt,
      reason: "retry_budget_exhausted",
    });
    assert.deepEqual(planUpdateCompletionDelivery({
      ...base,
      previousStatus: { ...pending, completionEmailDelivery: { status: "unavailable", attempts: 1 } },
    }), {
      action: "send",
      deliveryId: pending.completionEmailDeliveryId,
      pendingAt: pending.completionEmailPendingAt,
      previousAttempts: 1,
    });
    assert.deepEqual(planUpdateCompletionDelivery({
      ...base,
      continuousUpdate: true,
      previousStatus: {
        ...acceptedStatus,
        completionEmailDeliveryId: "not-a-delivery-id",
      },
    }), {
      action: "blocked",
      reason: "delivery_identity_invalid",
    });
    assert.deepEqual(planUpdateCompletionDelivery({
      ...base,
      continuousUpdate: true,
      previousStatus: { ...acceptedStatus, completionEmailDelivery: { status: "accepted", attempts: 0 } },
    }), {
      action: "blocked",
      reason: "delivery_identity_invalid",
    });
  });

  // contract-test: direct surface=cli assertions=server-management.update.durable-idempotency
  it("enforces one durable three-attempt budget across process recovery", async () => {
    const attemptNumbers: number[] = [];
    let sends = 0;
    const delivery = await deliverUpdateCompletionEmail(
      { apiKey: "redacted", from: "sender@example.test", to: "admin@example.test" },
      {
        deliveryId: "55555555-5555-4555-8555-555555555555",
        updateMode: "image",
        installedVersion: "v0.17.0",
        role: "core",
        completedAt: "2026-08-25T12:00:00Z",
        source: { kind: "release", url: "https://github.com/glowingkitty/OpenMates/releases/tag/v0.17.0" },
      },
      async () => {
        sends += 1;
        if (sends === 1) throw new Error("ambiguous_timeout");
      },
      1,
      (attempts) => attemptNumbers.push(attempts),
    );

    assert.deepEqual(delivery, { status: "accepted", attempts: 3 });
    assert.deepEqual(attemptNumbers, [2, 3]);
    assert.equal(sends, 2);
  });
});

describe("server support prompt", () => {
  it("renders a friendly start reminder for voluntary support", () => {
    const hint = renderSupportStartReminder();

    assert.match(hint, /Friendly reminder/);
    assert.match(hint, /financially support OpenMates development/);
    assert.match(hint, /https:\/\/openmates\.org\/#settings\/support/);
    assert.doesNotMatch(hint, /donate/i);
  });
});

describe("hasLlmCredentials", () => {
  let tempEnv: string;

  before(() => {
    tempEnv = join(tmpdir(), `test-env-${Date.now()}`);
  });

  after(() => {
    if (existsSync(tempEnv)) rmSync(tempEnv);
  });

  it("returns false when file does not exist", () => {
    assert.equal(hasLlmCredentials("/nonexistent/.env"), false);
  });

  it("returns false when no API keys are set", () => {
    writeFileSync(tempEnv, "DATABASE_NAME=directus\nSOME_VAR=value\n");
    assert.equal(hasLlmCredentials(tempEnv), false);
  });

  it("returns false when API key is IMPORTED_TO_VAULT", () => {
    docAssert("cli-server-requires-real-llm-api-key", () => {
      writeFileSync(tempEnv, "SECRET__OPENAI__API_KEY=IMPORTED_TO_VAULT\n");
      assert.equal(hasLlmCredentials(tempEnv), false);
    });
  });

  it("returns false when API key is empty", () => {
    writeFileSync(tempEnv, "SECRET__OPENAI__API_KEY=\n");
    assert.equal(hasLlmCredentials(tempEnv), false);
  });

  it("returns false when API key line is commented out", () => {
    writeFileSync(tempEnv, "# SECRET__OPENAI__API_KEY=sk-real-key\n");
    assert.equal(hasLlmCredentials(tempEnv), false);
  });

  it("returns false when only non-model provider keys are set", () => {
    writeFileSync(tempEnv, "SECRET__BRAVE__API_KEY=real-search-key\n");
    assert.equal(hasLlmCredentials(tempEnv), false);
  });

  it("returns true when a valid API key is set", () => {
    docAssert("cli-server-requires-real-llm-api-key", () => {
      writeFileSync(tempEnv, "SECRET__OPENAI__API_KEY=sk-proj-abc123\n");
      assert.equal(hasLlmCredentials(tempEnv), true);
    });
  });

  it("returns true when any provider has a key among many entries", () => {
    writeFileSync(tempEnv, [
      "DATABASE_NAME=directus",
      "SECRET__OPENAI__API_KEY=IMPORTED_TO_VAULT",
      "SECRET__ANTHROPIC__API_KEY=sk-ant-real",
      "OTHER_VAR=something",
    ].join("\n") + "\n");
    assert.equal(hasLlmCredentials(tempEnv), true);
  });
});

describe("runtime notification email", () => {
  // contract-test: direct surface=cli assertions=operational-monitoring.delivery.observable,operational-monitoring.environments.isolated-labeled
  it("labels alerts with server identity and actionable check details", () => {
    const email = buildRuntimeEmail({
      role: "core",
      kind: "post_update_failed",
      occurredAt: "2026-09-04T13:52:27.000Z",
      environment: "production",
      serverName: "production-core",
      deploymentMode: "official_cloud",
      version: "v0.17.0",
      checkIds: ["billing.health_freshness"],
      checkDetails: [{ id: "billing.health_freshness", failureClass: "billing_health_stale", reason: "check_failed" }],
      sanitizedReason: "check_failed",
    });

    assert.equal(email.subject, "[PRODUCTION] OpenMates core degraded: billing.health_freshness");
    for (const expected of [
      "Environment: production",
      "Server: production-core",
      "Deployment: official_cloud",
      "Version: v0.17.0",
      "Check: billing.health_freshness",
      "Failure class: billing_health_stale",
      "Next action: Review Stripe readiness, repair the configured destination, then rerun `openmates server verify --json`.",
    ]) {
      assert.match(email.textContent, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
  });
});
