/*
 * OpenMates CLI Code Run input packaging.
 *
 * Purpose: materialize local and remote code inputs client-side for app-skill
 * Code Run requests. Security: the backend receives bounded file payloads only;
 * it never receives local paths, repository URLs, or raw URLs to fetch. Tests:
 * frontend/packages/openmates-cli/tests/codeRunInput.test.ts.
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { basename, relative, resolve } from "node:path";

export const CODE_RUN_MAX_FILES = 50;
export const CODE_RUN_MAX_FILE_BYTES = 1_000_000;
export const CODE_RUN_MAX_TOTAL_BYTES = 10_000_000;

const DEFAULT_IGNORES = [".git", "node_modules", "__pycache__", ".venv", "dist", "build"];

export interface CodeRunFilePayload {
  path: string;
  content_base64: string;
  language?: string;
  mime_type?: string;
  is_target?: boolean;
}

export interface CodeRunRequestPayload {
  mode: "direct" | "chat_bound";
  entry_path?: string;
  enable_internet: boolean;
  files: CodeRunFilePayload[];
  chat_id?: string;
  target_embed_id?: string;
}

export interface CodeRunFlags {
  code?: string;
  language?: string;
  filename?: string;
  entry?: string;
  file?: string | string[];
  dir?: string | string[];
  url?: string | string[];
  repo?: string;
  include?: string | string[];
  exclude?: string | string[];
  noInternet?: boolean;
  chat?: string;
  targetEmbed?: string;
}

export interface CodeRunStreamUrlParams {
  apiUrl: string;
  executionId: string;
  sessionId: string;
  token: string;
}

export async function buildCodeRunRequestsFromFlags(flags: CodeRunFlags): Promise<CodeRunRequestPayload[]> {
  if (flags.chat || flags.targetEmbed) {
    if (!flags.chat || !flags.targetEmbed) {
      throw new Error("Chat-bound Code Run requires both --chat and --target-embed.");
    }
    return [{
      mode: "chat_bound",
      chat_id: flags.chat,
      target_embed_id: flags.targetEmbed,
      enable_internet: flags.noInternet !== true,
      files: [],
    }];
  }

  const files: CodeRunFilePayload[] = [];
  const seen = new Set<string>();
  const entry = flags.entry ? normalizeCodeRunPath(flags.entry) : undefined;
  let totalBytes = 0;

  const addFile = (file: CodeRunFilePayload, byteLength: number): void => {
    const path = normalizeCodeRunPath(file.path);
    if (seen.has(path)) throw new Error(`Duplicate Code Run file path: ${path}`);
    seen.add(path);
    totalBytes += byteLength;
    if (files.length + 1 > CODE_RUN_MAX_FILES) throw new Error(`Code Run supports at most ${CODE_RUN_MAX_FILES} files.`);
    if (byteLength > CODE_RUN_MAX_FILE_BYTES) throw new Error(`Code Run file is too large: ${path}`);
    if (totalBytes > CODE_RUN_MAX_TOTAL_BYTES) throw new Error("Code Run file bundle is too large.");
    files.push({ ...file, path });
  };

  if (flags.code !== undefined) {
    const filename = normalizeCodeRunPath(flags.filename || entry || defaultFilename(flags.language));
    const buffer = Buffer.from(flags.code, "utf8");
    addFile({
      path: filename,
      content_base64: buffer.toString("base64"),
      language: flags.language || inferLanguage(filename),
      mime_type: "text/plain",
      is_target: true,
    }, buffer.byteLength);
  }

  for (const filePath of toList(flags.file)) {
    const absolute = resolve(filePath);
    const buffer = await readFile(absolute);
    const sandboxPath = normalizeCodeRunPath(basename(filePath));
    addFile({
      path: sandboxPath,
      content_base64: buffer.toString("base64"),
      language: inferLanguage(sandboxPath),
      mime_type: "text/plain",
      is_target: entry ? sandboxPath === entry : files.length === 0,
    }, buffer.byteLength);
  }

  for (const dirPath of toList(flags.dir)) {
    const root = resolve(dirPath);
    const dirFiles = await collectDirectoryFiles(root, flags.include, flags.exclude);
    for (const absolute of dirFiles) {
      const sandboxPath = normalizeCodeRunPath(relative(root, absolute).replace(/\\/g, "/"));
      const buffer = await readFile(absolute);
      addFile({
        path: sandboxPath,
        content_base64: buffer.toString("base64"),
        language: inferLanguage(sandboxPath),
        mime_type: "text/plain",
        is_target: entry ? sandboxPath === entry : files.length === 0,
      }, buffer.byteLength);
    }
  }

  for (const url of toList(flags.url)) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Failed to download Code Run URL ${redactUrl(url)} (HTTP ${response.status})`);
    const text = await response.text();
    const urlPath = new URL(url).pathname;
    const sandboxPath = normalizeCodeRunPath(entry || basename(urlPath) || "main.txt");
    const buffer = Buffer.from(text, "utf8");
    addFile({
      path: sandboxPath,
      content_base64: buffer.toString("base64"),
      language: inferLanguage(sandboxPath),
      mime_type: "text/plain",
      is_target: true,
    }, buffer.byteLength);
  }

  if (flags.repo) {
    await addGithubRepoFiles(flags.repo, toList(flags.include), async (path, text) => {
      const sandboxPath = normalizeCodeRunPath(path);
      const buffer = Buffer.from(text, "utf8");
      addFile({
        path: sandboxPath,
        content_base64: buffer.toString("base64"),
        language: inferLanguage(sandboxPath),
        mime_type: "text/plain",
        is_target: entry ? sandboxPath === entry : files.length === 0,
      }, buffer.byteLength);
    });
  }

  if (files.length === 0) throw new Error("Code Run requires --code, --file, --dir, --url, --repo, or --chat/--target-embed.");
  const entryPath = entry || files.find((file) => file.is_target)?.path || files[0].path;
  if (!files.some((file) => file.path === entryPath)) throw new Error(`Code Run entry file was not included: ${entryPath}`);
  for (const file of files) file.is_target = file.path === entryPath;

  return [{
    mode: "direct",
    entry_path: entryPath,
    enable_internet: flags.noInternet !== true,
    files,
  }];
}

export function buildCodeRunStreamUrl(params: CodeRunStreamUrlParams): string {
  const base = params.apiUrl.replace(/\/$/, "").replace(/^http:/, "ws:").replace(/^https:/, "wss:");
  const query = new URLSearchParams({ sessionId: params.sessionId, token: params.token });
  return `${base}/v1/code/run/${encodeURIComponent(params.executionId)}/stream?${query.toString()}`;
}

export function normalizeCodeRunPath(rawPath: string): string {
  const path = rawPath.trim().replace(/\\/g, "/");
  if (!path || path.includes("\0") || path.startsWith("/") || path.startsWith("~/") || /^[A-Za-z]:\//.test(path)) {
    throw new Error(`Unsafe Code Run path: ${rawPath}`);
  }
  const parts = path.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`Unsafe Code Run path: ${rawPath}`);
  }
  return parts.join("/");
}

async function collectDirectoryFiles(root: string, include: string | string[] | undefined, exclude: string | string[] | undefined): Promise<string[]> {
  const includes = toList(include);
  const excludes = [...DEFAULT_IGNORES, ...toList(exclude)];
  const files: string[] = [];

  async function walk(directory: string): Promise<void> {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const absolute = resolve(directory, entry.name);
      const rel = relative(root, absolute).replace(/\\/g, "/");
      if (matchesAny(rel, excludes) || matchesAny(entry.name, excludes)) continue;
      if (entry.isDirectory()) {
        await walk(absolute);
      } else if (entry.isFile()) {
        if (includes.length === 0 || matchesAny(rel, includes)) files.push(absolute);
      }
    }
  }

  const rootStat = await stat(root);
  if (!rootStat.isDirectory()) throw new Error(`Code Run --dir is not a directory: ${root}`);
  await walk(root);
  return files.sort();
}

async function addGithubRepoFiles(repoUrl: string, includes: string[], add: (path: string, text: string) => Promise<void>): Promise<void> {
  if (includes.length === 0) throw new Error("Code Run --repo requires at least one --include path in v1.");
  const parsed = parseGithubRepoUrl(repoUrl);
  for (const includePath of includes) {
    const path = normalizeCodeRunPath(includePath);
    const rawUrl = `https://raw.githubusercontent.com/${parsed.owner}/${parsed.repo}/${parsed.ref}/${path}`;
    const response = await fetch(rawUrl);
    if (!response.ok) throw new Error(`Failed to download GitHub file ${path} (HTTP ${response.status})`);
    await add(path, await response.text());
  }
}

function parseGithubRepoUrl(repoUrl: string): { owner: string; repo: string; ref: string } {
  const url = new URL(repoUrl);
  if (url.hostname !== "github.com") throw new Error("Code Run --repo supports public github.com URLs in v1.");
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.length < 2) throw new Error("Invalid GitHub repository URL.");
  return { owner: parts[0], repo: parts[1].replace(/\.git$/, ""), ref: "main" };
}

function toList(value: string | string[] | undefined): string[] {
  if (Array.isArray(value)) return value.flatMap((item) => item.split("\n")).filter(Boolean);
  if (typeof value === "string") return value.split("\n").filter(Boolean);
  return [];
}

function matchesAny(path: string, patterns: string[]): boolean {
  return patterns.some((pattern) => matchesPattern(path, pattern));
}

function matchesPattern(path: string, pattern: string): boolean {
  if (!pattern) return false;
  if (pattern.includes("*")) {
    const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
    return new RegExp(`^${escaped}$`).test(path) || new RegExp(`(^|/)${escaped}$`).test(path);
  }
  return path === pattern || path.startsWith(`${pattern}/`) || path.endsWith(`/${pattern}`);
}

function inferLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase();
  if (ext === "py") return "python";
  if (ext === "js" || ext === "mjs" || ext === "cjs") return "javascript";
  if (ext === "ts") return "typescript";
  if (ext === "sh") return "bash";
  if (ext === "go") return "go";
  if (ext === "rs") return "rust";
  if (ext === "c") return "c";
  if (ext === "cc" || ext === "cpp" || ext === "cxx") return "cpp";
  return "";
}

function defaultFilename(language: string | undefined): string {
  if (language === "python" || language === "py") return "main.py";
  if (language === "javascript" || language === "js" || language === "node") return "main.js";
  if (language === "typescript" || language === "ts") return "main.ts";
  if (language === "bash" || language === "sh") return "main.sh";
  return "main.txt";
}

function redactUrl(rawUrl: string): string {
  const url = new URL(rawUrl);
  url.search = "";
  url.hash = "";
  return url.toString();
}
