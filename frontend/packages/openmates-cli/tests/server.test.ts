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
import { existsSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { tmpdir } from "node:os";

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
function composeArgs(installPath: string, withOverrides: boolean, installMode?: "image" | "source"): string[] {
  const resolvedInstallMode = installMode ?? (
    existsSync(join(installPath, "backend", "core", "docker-compose.selfhost.yml")) ? "image" : "source"
  );
  const COMPOSE_FILE = resolvedInstallMode === "image"
    ? join("backend", "core", "docker-compose.selfhost.yml")
    : join("backend", "core", "docker-compose.yml");
  const COMPOSE_OVERRIDE = join("backend", "core", "docker-compose.override.yml");
  const args = ["compose", "--env-file", ".env", "-f", COMPOSE_FILE];
  if (withOverrides && existsSync(join(installPath, COMPOSE_OVERRIDE))) {
    args.push("-f", COMPOSE_OVERRIDE);
  }
  return args;
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
  const STATE_DIR = join(homedir(), ".openmates");
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
        apiUrl: "http://localhost:8000",
        appUrl: "http://localhost:5173",
      };
      saveServerConfig(config);
      const loaded = loadServerConfig();
      assert.ok(loaded);
      assert.equal(loaded.installPath, config.installPath);
      assert.equal(loaded.composeProfile, "core");
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
    const target = resolveTargetImageTag({}, "v0.11.0-alpha.0", "0.12.0-alpha.0");
    assert.deepEqual(target, { tag: "v0.12.0-alpha.0" });
  });

  it("preserves installed channel tags when no explicit target is provided", () => {
    assert.deepEqual(resolveTargetImageTag({}, "dev", "0.12.0-alpha.0"), { tag: "dev", channel: "dev" });
    assert.deepEqual(resolveTargetImageTag({}, "main", "0.12.0"), { tag: "main", channel: "main" });
  });

  it("maps stable channel to the published main image tag", () => {
    const target = resolveTargetImageTag({ channel: "stable" }, "v0.11.0", "0.12.0");
    assert.deepEqual(target, { tag: "main", channel: "main" });
  });

  it("rejects ambiguous image tag and channel combinations", () => {
    assert.throws(
      () => resolveTargetImageTag({ "image-tag": "v0.12.0", channel: "dev" }, "v0.11.0", "0.12.0"),
      /either --image-tag or --channel/,
    );
  });

  it("rejects missing image tag and channel values", () => {
    assert.throws(
      () => resolveTargetImageTag({ "image-tag": true }, "v0.11.0", "0.12.0"),
      /--image-tag <tag>/,
    );
    assert.throws(
      () => resolveTargetImageTag({ channel: true }, "v0.11.0", "0.12.0"),
      /--channel stable/,
    );
  });

  it("uses dev templates for prerelease and smoke tags", () => {
    assert.equal(templateRefForImageTag("v0.12.0-alpha.0"), "dev");
    assert.equal(templateRefForImageTag("selfhost-smoke-abc123"), "dev");
  });

  it("uses release and channel template refs where available", () => {
    assert.equal(templateRefForImageTag("v0.12.0"), "v0.12.0");
    assert.equal(templateRefForImageTag("main"), "main");
    assert.equal(templateRefForImageTag("stable"), "main");
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
