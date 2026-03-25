/*
 * OpenMates CLI server configuration storage.
 *
 * Purpose: persist and resolve the OpenMates server installation path so that
 *          server management commands (start, stop, logs, etc.) work from any
 *          directory without requiring --path every time.
 * Architecture: stores config in ~/.openmates/server.json alongside session.json.
 * Tests: frontend/packages/openmates-cli/tests/server.test.ts
 */

import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ServerConfig {
  /** Absolute path to the cloned OpenMates repository */
  installPath: string;
  /** Timestamp when the server was installed */
  installedAt: number;
  /** Whether the override compose file is used (Directus, Grafana) */
  composeProfile: "core" | "full";
}

// ---------------------------------------------------------------------------
// Filesystem helpers (minimal — no secrets, so 0o644 is fine for the file)
// ---------------------------------------------------------------------------

const STATE_DIR = join(homedir(), ".openmates");
const CONFIG_FILE = "server.json";

function ensureStateDir(): string {
  if (!existsSync(STATE_DIR)) {
    mkdirSync(STATE_DIR, { recursive: true, mode: 0o700 });
  }
  return STATE_DIR;
}

// ---------------------------------------------------------------------------
// Save / Load
// ---------------------------------------------------------------------------

export function saveServerConfig(config: ServerConfig): void {
  const dir = ensureStateDir();
  const filePath = join(dir, CONFIG_FILE);
  writeFileSync(filePath, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o644 });
}

export function loadServerConfig(): ServerConfig | null {
  const filePath = join(STATE_DIR, CONFIG_FILE);
  if (!existsSync(filePath)) return null;
  try {
    return JSON.parse(readFileSync(filePath, "utf-8")) as ServerConfig;
  } catch {
    return null;
  }
}

export function removeServerConfig(): void {
  const filePath = join(STATE_DIR, CONFIG_FILE);
  if (existsSync(filePath)) {
    rmSync(filePath);
  }
}

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

/** Marker file that confirms a directory is an OpenMates installation. */
const COMPOSE_MARKER = join("backend", "core", "docker-compose.yml");

function isOpenMatesDir(dir: string): boolean {
  return existsSync(join(dir, COMPOSE_MARKER));
}

/**
 * Resolve the OpenMates server installation path.
 *
 * Priority:
 *   1. --path flag (explicit override)
 *   2. Saved config (~/.openmates/server.json)
 *   3. Current working directory (if it looks like an OpenMates repo)
 *   4. Error
 */
export function resolveServerPath(flags: Record<string, string | boolean>): string {
  // 1. Explicit --path flag
  if (typeof flags.path === "string" && flags.path) {
    const explicit = resolve(flags.path);
    if (!isOpenMatesDir(explicit)) {
      throw new Error(
        `${explicit} does not appear to be an OpenMates installation ` +
        `(missing ${COMPOSE_MARKER}).`,
      );
    }
    return explicit;
  }

  // 2. Saved config
  const config = loadServerConfig();
  if (config?.installPath && isOpenMatesDir(config.installPath)) {
    return config.installPath;
  }

  // 3. Current working directory
  const cwd = process.cwd();
  if (isOpenMatesDir(cwd)) {
    return cwd;
  }

  throw new Error(
    "No OpenMates installation found.\n" +
    "Run 'openmates server install' to set up a new server, or use --path <dir>.",
  );
}
