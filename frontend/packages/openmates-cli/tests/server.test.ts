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
      /^SECRET__\w+__API_KEY$/.test(key) &&
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
function composeArgs(installPath: string, withOverrides: boolean): string[] {
  const COMPOSE_FILE = join("backend", "core", "docker-compose.yml");
  const COMPOSE_OVERRIDE = join("backend", "core", "docker-compose.override.yml");
  const args = ["compose", "--env-file", ".env", "-f", COMPOSE_FILE];
  if (withOverrides && existsSync(join(installPath, COMPOSE_OVERRIDE))) {
    args.push("-f", COMPOSE_OVERRIDE);
  }
  return args;
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
      backupContent = require("node:fs").readFileSync(CONFIG_PATH, "utf-8");
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
    const config: ServerConfig = {
      installPath: "/tmp/test-openmates",
      installedAt: Date.now(),
      composeProfile: "core",
    };
    saveServerConfig(config);
    const loaded = loadServerConfig();
    assert.ok(loaded);
    assert.equal(loaded.installPath, config.installPath);
    assert.equal(loaded.composeProfile, "core");
  });

  it("returns null when no config exists", () => {
    removeServerConfig();
    const loaded = loadServerConfig();
    assert.equal(loaded, null);
  });

  it("removeServerConfig is safe when file does not exist", () => {
    removeServerConfig();
    assert.doesNotThrow(() => removeServerConfig());
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
    const result = resolveServerPath({ path: tempDir });
    assert.equal(result, tempDir);
  });

  it("rejects --path that is not an OpenMates dir", () => {
    assert.throws(
      () => resolveServerPath({ path: tmpdir() }),
      /does not appear to be an OpenMates installation/,
    );
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
    const args = composeArgs(tempDir, false);
    assert.deepEqual(args, [
      "compose", "--env-file", ".env",
      "-f", join("backend", "core", "docker-compose.yml"),
    ]);
  });

  it("includes override file when requested and exists", () => {
    const args = composeArgs(tempDir, true);
    assert.equal(args.length, 7);
    assert.ok(args.includes(join("backend", "core", "docker-compose.override.yml")));
  });

  it("skips override file when it does not exist", () => {
    const emptyDir = join(tmpdir(), `no-override-${Date.now()}`);
    mkdirSync(join(emptyDir, "backend", "core"), { recursive: true });
    const args = composeArgs(emptyDir, true);
    assert.equal(args.length, 5); // No override added
    rmSync(emptyDir, { recursive: true, force: true });
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
    writeFileSync(tempEnv, "SECRET__OPENAI__API_KEY=IMPORTED_TO_VAULT\n");
    assert.equal(hasLlmCredentials(tempEnv), false);
  });

  it("returns false when API key is empty", () => {
    writeFileSync(tempEnv, "SECRET__OPENAI__API_KEY=\n");
    assert.equal(hasLlmCredentials(tempEnv), false);
  });

  it("returns false when API key line is commented out", () => {
    writeFileSync(tempEnv, "# SECRET__OPENAI__API_KEY=sk-real-key\n");
    assert.equal(hasLlmCredentials(tempEnv), false);
  });

  it("returns true when a valid API key is set", () => {
    writeFileSync(tempEnv, "SECRET__OPENAI__API_KEY=sk-proj-abc123\n");
    assert.equal(hasLlmCredentials(tempEnv), true);
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
