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
import { join, resolve, relative } from "node:path";

import { classifyProjectFileRisk } from "./projectFileRisk.js";

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

export type RgRunner = (args: string[], cwd: string) => Promise<string>;

export interface RemoteAccessSearchOptions {
  query: string;
  sourceRoot: string;
  maxResults?: number;
  userProtectedPatterns?: string[];
  runRg: RgRunner;
}

const DEFAULT_MAX_SEARCH_RESULTS = 20;
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
  return join(homeDirectory, ".openmates", "remote-cache", sourceId);
}

export async function searchRemoteSource(options: RemoteAccessSearchOptions): Promise<RemoteAccessSearchResult> {
  const sourceRoot = resolve(options.sourceRoot);
  const maxResults = options.maxResults ?? DEFAULT_MAX_SEARCH_RESULTS;
  const output = await options.runRg(["--json", "--line-number", "--", options.query, "."], sourceRoot);
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
