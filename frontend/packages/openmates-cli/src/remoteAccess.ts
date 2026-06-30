/*
 * Project remote-access bridge primitives.
 *
 * Purpose: provide bounded, read-only source search and cache-path helpers for
 * Project remote sources before interactive bridge commands are wired.
 * Architecture: CLI executes source reads/searches locally; OpenMates stores
 * only encrypted metadata and opaque source IDs.
 * Security: searches run inside approved source roots and filter high-risk,
 * binary, and out-of-root paths before returning snippets.
 * Tests: frontend/packages/openmates-cli/tests/remoteAccess.test.ts.
 */

import { homedir } from "node:os";
import { chmodSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { join, resolve, relative } from "node:path";

import { classifyProjectFileRisk, PROJECT_HIGH_RISK_GLOBS } from "./projectFileRisk.js";

export interface RemoteAccessSearchMatch {
  path: string;
  line: number;
  snippet: string;
}

export interface RemoteAccessSearchResult {
  matches: RemoteAccessSearchMatch[];
  omitted: number;
  excluded: number;
}

export interface RemoteAccessSourceRecord {
  sourceId: string;
  projectId?: string;
  sourceType: "local_folder" | "local_git_repository" | "remote_folder" | "remote_git_repository";
  rootPath: string;
  displayName: string;
  cachePath: string;
  status: "connected" | "offline" | "permission_required" | "revoked";
  createdAt: number;
  updatedAt: number;
}

export type RgRunner = (args: string[], cwd: string, maxOutputMatches?: number) => Promise<string>;

export interface RemoteAccessSearchOptions {
  query: string;
  sourceRoot: string;
  maxResults?: number;
  userProtectedPatterns?: string[];
  runRg: RgRunner;
}

export interface StartRemoteAccessSourceInput {
  sourceId: string;
  projectId?: string;
  rootPath: string;
  sourceType?: RemoteAccessSourceRecord["sourceType"];
  displayName?: string;
  homeDirectory?: string;
}

export interface StoredRemoteAccessSearchOptions {
  sourceId: string;
  query: string;
  maxResults?: number;
  homeDirectory?: string;
  userProtectedPatterns?: string[];
  runRg: RgRunner;
}

const DEFAULT_MAX_SEARCH_RESULTS = 20;
const MAX_SOURCE_ID_LENGTH = 128;
const BINARY_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".pdf",
  ".zip",
  ".gz",
  ".tar",
  ".mp3",
  ".mp4",
  ".mov",
]);

export function resolveRemoteCachePath(sourceId: string, homeDirectory = homedir()): string {
  assertSafeSourceId(sourceId);
  return join(homeDirectory, ".openmates", "remote-cache", sourceId);
}

export function startRemoteAccessSource(input: StartRemoteAccessSourceInput): RemoteAccessSourceRecord {
  assertSafeSourceId(input.sourceId);
  const homeDirectory = input.homeDirectory ?? homedir();
  const rootPath = resolve(input.rootPath);
  if (!existsSync(rootPath) || !statSync(rootPath).isDirectory()) {
    throw new Error(`Remote source path does not exist or is not a directory: ${rootPath}`);
  }
  const now = Math.floor(Date.now() / 1000);
  const source: RemoteAccessSourceRecord = {
    sourceId: input.sourceId,
    projectId: input.projectId,
    sourceType: input.sourceType ?? "local_folder",
    rootPath,
    displayName: input.displayName ?? input.sourceId,
    cachePath: resolveRemoteCachePath(input.sourceId, homeDirectory),
    status: "connected",
    createdAt: now,
    updatedAt: now,
  };
  const sources = listRemoteAccessSources(homeDirectory).filter((entry) => entry.sourceId !== input.sourceId);
  saveRemoteAccessSources([...sources, source], homeDirectory);
  mkdirSync(source.cachePath, { recursive: true, mode: 0o700 });
  return source;
}

export function listRemoteAccessSources(homeDirectory = homedir()): RemoteAccessSourceRecord[] {
  const filePath = remoteAccessStorePath(homeDirectory);
  if (!existsSync(filePath)) return [];
  try {
    const parsed = JSON.parse(readFileSync(filePath, "utf-8")) as { sources?: RemoteAccessSourceRecord[] };
    if (!Array.isArray(parsed.sources)) {
      throw new Error("Remote source store is missing the sources array");
    }
    parsed.sources.forEach((source, index) => assertRemoteAccessSourceRecord(source, index));
    return parsed.sources;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to read remote source store at ${filePath}: ${message}`);
  }
}

export async function searchStoredRemoteAccessSource(options: StoredRemoteAccessSearchOptions): Promise<RemoteAccessSearchResult> {
  const source = listRemoteAccessSources(options.homeDirectory).find((entry) => entry.sourceId === options.sourceId);
  if (!source) {
    throw new Error(`Remote source '${options.sourceId}' is not attached`);
  }
  return searchRemoteSource({
    query: options.query,
    sourceRoot: source.rootPath,
    maxResults: options.maxResults,
    userProtectedPatterns: options.userProtectedPatterns,
    runRg: options.runRg,
  });
}

export async function searchRemoteSource(options: RemoteAccessSearchOptions): Promise<RemoteAccessSearchResult> {
  const sourceRoot = resolve(options.sourceRoot);
  const maxResults = normalizeMaxResults(options.maxResults);
  const output = await options.runRg(
    buildRgSearchArgs(options.query, options.userProtectedPatterns ?? []),
    sourceRoot,
    maxResults + 1,
  );
  const matches: RemoteAccessSearchMatch[] = [];
  let omitted = 0;
  let excluded = 0;

  for (const line of output.split("\n")) {
    if (!line.trim()) continue;
    const match = parseRgMatch(line);
    if (!match) continue;
    if (shouldExcludePath(sourceRoot, match.path, options.userProtectedPatterns ?? [])) {
      excluded += 1;
      continue;
    }
    if (matches.length >= maxResults) {
      omitted += 1;
      continue;
    }
    matches.push(match);
  }

  return { matches, omitted, excluded };
}

function assertSafeSourceId(sourceId: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(sourceId) || sourceId.length > MAX_SOURCE_ID_LENGTH) {
    throw new Error("Remote source ID must be 1-128 characters and contain only letters, numbers, dot, underscore, or hyphen");
  }
}

function normalizeMaxResults(value: number | undefined): number {
  const maxResults = value ?? DEFAULT_MAX_SEARCH_RESULTS;
  if (!Number.isInteger(maxResults) || maxResults <= 0) {
    throw new Error("Remote source search limit must be a positive integer");
  }
  return maxResults;
}

function buildRgSearchArgs(query: string, userProtectedPatterns: string[]): string[] {
  const args = ["--json", "--line-number"];
  for (const pattern of [...PROJECT_HIGH_RISK_GLOBS, ...binaryRgGlobs(), ...userProtectedPatterns]) {
    args.push("--glob", `!${pattern.replace(/\\/g, "/")}`);
  }
  args.push("--", query, ".");
  return args;
}

function binaryRgGlobs(): string[] {
  return [...BINARY_EXTENSIONS].flatMap((extension) => [`*${extension}`, `**/*${extension}`]);
}

export async function runRgCommand(args: string[], cwd: string, maxOutputMatches?: number): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn("rg", args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdoutLines: string[] = [];
    const stderrChunks: string[] = [];
    let pendingStdout = "";
    let matchCount = 0;
    let killedForCap = false;

    child.stdout.setEncoding("utf-8");
    child.stdout.on("data", (chunk: string) => {
      pendingStdout += chunk;
      const lines = pendingStdout.split("\n");
      pendingStdout = lines.pop() ?? "";
      for (const line of lines) {
        if (!line) continue;
        stdoutLines.push(line);
        if (line.includes('"type":"match"')) {
          matchCount += 1;
        }
        if (maxOutputMatches !== undefined && matchCount >= maxOutputMatches) {
          killedForCap = true;
          child.kill();
          break;
        }
      }
    });

    child.stderr.setEncoding("utf-8");
    child.stderr.on("data", (chunk: string) => stderrChunks.push(chunk));

    child.on("error", reject);
    child.on("close", (code) => {
      if (pendingStdout) stdoutLines.push(pendingStdout);
      if (code === 0 || code === 1 || killedForCap) {
        resolvePromise(stdoutLines.join("\n"));
        return;
      }
      reject(new Error(`rg failed with exit code ${code}: ${stderrChunks.join("").trim()}`));
    });
  });
}

function shouldExcludePath(sourceRoot: string, relativePath: string, userProtectedPatterns: string[]): boolean {
  if (!isPathInsideRoot(sourceRoot, relativePath)) return true;
  if (isBinaryPath(relativePath)) return true;
  return classifyProjectFileRisk(relativePath, userProtectedPatterns).isHighRisk;
}

function isPathInsideRoot(sourceRoot: string, relativePath: string): boolean {
  const resolvedPath = resolve(sourceRoot, relativePath);
  const relation = relative(sourceRoot, resolvedPath);
  return relation === "" || (!relation.startsWith("..") && !resolve(relation).startsWith("/.."));
}

function isBinaryPath(path: string): boolean {
  const lowerPath = path.toLowerCase();
  for (const extension of BINARY_EXTENSIONS) {
    if (lowerPath.endsWith(extension)) return true;
  }
  return false;
}

function parseRgMatch(line: string): RemoteAccessSearchMatch | null {
  try {
    const parsed = JSON.parse(line) as {
      type?: string;
      data?: {
        path?: { text?: string };
        line_number?: number;
        lines?: { text?: string };
      };
    };
    if (parsed.type !== "match") return null;
    const path = parsed.data?.path?.text;
    const lineNumber = parsed.data?.line_number;
    const snippet = parsed.data?.lines?.text;
    if (typeof path !== "string" || typeof lineNumber !== "number" || typeof snippet !== "string") {
      return null;
    }
    return { path, line: lineNumber, snippet };
  } catch {
    return null;
  }
}

function remoteAccessStorePath(homeDirectory: string): string {
  return join(homeDirectory, ".openmates", "remote-sources.json");
}

function saveRemoteAccessSources(sources: RemoteAccessSourceRecord[], homeDirectory: string): void {
  const filePath = remoteAccessStorePath(homeDirectory);
  const stateDir = join(homeDirectory, ".openmates");
  mkdirSync(stateDir, { recursive: true, mode: 0o700 });
  chmodSync(stateDir, 0o700);
  writeFileSync(filePath, `${JSON.stringify({ sources }, null, 2)}\n`, { mode: 0o600 });
  chmodSync(filePath, 0o600);
}

function assertRemoteAccessSourceRecord(value: unknown, index: number): asserts value is RemoteAccessSourceRecord {
  if (typeof value !== "object" || value === null) {
    throw new Error(`Remote source record ${index} is not an object`);
  }
  const source = value as Partial<RemoteAccessSourceRecord>;
  const validStatus = ["connected", "offline", "permission_required", "revoked"].includes(source.status ?? "");
  const validType = ["local_folder", "local_git_repository", "remote_folder", "remote_git_repository"].includes(
    source.sourceType ?? "",
  );
  if (
    typeof source.sourceId !== "string" ||
    (source.projectId !== undefined && typeof source.projectId !== "string") ||
    !validType ||
    typeof source.rootPath !== "string" ||
    typeof source.displayName !== "string" ||
    typeof source.cachePath !== "string" ||
    !validStatus ||
    typeof source.createdAt !== "number" ||
    typeof source.updatedAt !== "number"
  ) {
    throw new Error(`Remote source record ${index} is invalid`);
  }
  assertSafeSourceId(source.sourceId);
}
