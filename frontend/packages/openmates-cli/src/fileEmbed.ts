// frontend/packages/openmates-cli/src/fileEmbed.ts
/**
 * @file CLI file embed support — reads local files referenced via @path
 * in chat messages, scans them for secrets, and prepares them for
 * inclusion in the message payload.
 *
 * File content is inlined in the message text (as a code-fenced block)
 * rather than sent as a separate encrypted embed, because the CLI
 * currently lacks the client-side embed encryption + Directus storage
 * pipeline. This approach matches the --files flag in the planned
 * `openmates apps ai ask --files` command.
 *
 * Sensitive files (.env, .pem, .key, SSH keys) get special handling:
 * - .env files: zero-knowledge processing (only names + last 3 chars shown)
 * - .pem/.key/SSH: blocked by default with warning
 *
 * Architecture: docs/planned/cli-package.md (Sensitive Files Protection)
 */

import { readFileSync, statSync, existsSync } from "node:fs";
import { basename, extname, resolve } from "node:path";
import { homedir } from "node:os";
import type { OutputRedactor } from "./outputRedactor.js";

/** Maximum file size for inline inclusion (512 KB) */
const MAX_FILE_SIZE = 512 * 1024;

/** File extensions that are always blocked (private keys, credentials) */
const BLOCKED_EXTENSIONS = new Set([
  ".pem",
  ".key",
  ".p12",
  ".pfx",
  ".keystore",
  ".kdbx",
  ".credentials",
]);

/** File names that are always blocked (SSH keys, cloud credentials) */
const BLOCKED_NAMES = new Set([
  "id_rsa",
  "id_ed25519",
  "id_dsa",
  "id_ecdsa",
  "authorized_keys",
  "known_hosts",
  ".git-credentials",
  ".netrc",
  ".pgpass",
  ".my.cnf",
]);

/** File extensions for environment files (zero-knowledge processing) */
const ENV_EXTENSIONS = new Set([".env", ".envrc"]);

/** Check if a filename matches .env or .env.* pattern */
function isEnvFile(filename: string): boolean {
  const lower = filename.toLowerCase();
  if (ENV_EXTENSIONS.has(extname(lower))) return true;
  if (lower === ".env" || lower.startsWith(".env.")) return true;
  if (lower === ".envrc") return true;
  return false;
}

/** Result of processing a file for inclusion in a message */
export interface ProcessedFile {
  /** Resolved absolute path */
  path: string;
  /** File basename */
  name: string;
  /** Processed content (redacted if needed) */
  content: string;
  /** Programming language hint for code fences */
  language: string;
  /** Whether secrets were redacted */
  redacted: boolean;
  /** Whether this was a zero-knowledge env file processing */
  zeroKnowledge: boolean;
}

/** Error from file processing */
export interface FileError {
  path: string;
  error: string;
}

/** Result of processing all file references in a message */
export interface FileProcessResult {
  /** Successfully processed files */
  files: ProcessedFile[];
  /** Files that could not be processed */
  errors: FileError[];
  /** Files that were blocked (sensitive) */
  blocked: FileError[];
}

/**
 * Resolve a file path from a user @mention.
 * Handles ~/ expansion and relative paths.
 */
function resolvePath(filePath: string): string {
  if (filePath.startsWith("~/")) {
    return resolve(homedir(), filePath.slice(2));
  }
  return resolve(filePath);
}

/**
 * Get a language hint from file extension for code fences.
 */
function getLanguage(filename: string): string {
  const ext = extname(filename).toLowerCase();
  const map: Record<string, string> = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".cs": "csharp",
    ".php": "php",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".md": "markdown",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "nginx",
    ".env": "bash",
    ".envrc": "bash",
    ".dockerfile": "dockerfile",
    ".svelte": "svelte",
    ".vue": "vue",
    ".tf": "hcl",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".r": "r",
    ".m": "matlab",
    ".pl": "perl",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".scala": "scala",
    ".dart": "dart",
  };
  return map[ext] || "";
}

/**
 * Process .env files with zero-knowledge handling.
 * Shows only variable names and last 3 characters of values.
 *
 * Example:
 *   DATABASE_URL: ***ydb
 *   OPENAI_API_KEY: ***f9d
 */
function processEnvFileZeroKnowledge(content: string): string {
  const lines = content.split("\n");
  const processed: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();

    // Keep comments and empty lines as-is
    if (!line || line.startsWith("#")) {
      processed.push(line);
      continue;
    }

    // Remove optional "export " prefix
    const cleanLine = line.startsWith("export ")
      ? line.slice(7).trim()
      : line;

    const eqIndex = cleanLine.indexOf("=");
    if (eqIndex === -1) {
      processed.push(line);
      continue;
    }

    const key = cleanLine.slice(0, eqIndex).trim();
    let value = cleanLine.slice(eqIndex + 1).trim();

    // Strip quotes
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    // Show last 3 chars only
    if (value.length > 3) {
      processed.push(`${key}: ***${value.slice(-3)}`);
    } else if (value.length > 0) {
      processed.push(`${key}: ***`);
    } else {
      processed.push(`${key}: (empty)`);
    }
  }

  return processed.join("\n");
}

/**
 * Process a list of file paths for inclusion in a chat message.
 *
 * @param filePaths Array of file paths from @mention parsing
 * @param redactor The output redactor for scanning file content
 * @returns Processed files, errors, and blocked files
 */
export function processFiles(
  filePaths: string[],
  redactor: OutputRedactor | null,
): FileProcessResult {
  const files: ProcessedFile[] = [];
  const errors: FileError[] = [];
  const blocked: FileError[] = [];

  for (const rawPath of filePaths) {
    const resolvedPath = resolvePath(rawPath);
    const filename = basename(resolvedPath);
    const ext = extname(filename).toLowerCase();

    // Check if file exists
    if (!existsSync(resolvedPath)) {
      errors.push({ path: rawPath, error: "File not found" });
      continue;
    }

    // Check file stats
    let stats;
    try {
      stats = statSync(resolvedPath);
    } catch (e) {
      errors.push({
        path: rawPath,
        error: `Cannot read file: ${e instanceof Error ? e.message : String(e)}`,
      });
      continue;
    }

    if (stats.isDirectory()) {
      errors.push({ path: rawPath, error: "Is a directory, not a file" });
      continue;
    }

    if (stats.size > MAX_FILE_SIZE) {
      errors.push({
        path: rawPath,
        error: `File too large (${Math.round(stats.size / 1024)}KB > ${MAX_FILE_SIZE / 1024}KB limit)`,
      });
      continue;
    }

    // Check for blocked file types
    if (BLOCKED_EXTENSIONS.has(ext)) {
      blocked.push({
        path: rawPath,
        error: `Blocked: ${ext} files may contain private keys or credentials. ` +
          "Use --allow-sensitive to override.",
      });
      continue;
    }

    if (BLOCKED_NAMES.has(filename)) {
      blocked.push({
        path: rawPath,
        error: `Blocked: '${filename}' typically contains sensitive credentials. ` +
          "Use --allow-sensitive to override.",
      });
      continue;
    }

    // Read file content
    let content: string;
    try {
      content = readFileSync(resolvedPath, "utf-8");
    } catch (e) {
      errors.push({
        path: rawPath,
        error: `Cannot read: ${e instanceof Error ? e.message : String(e)}`,
      });
      continue;
    }

    // Special handling for .env files: zero-knowledge processing
    if (isEnvFile(filename)) {
      files.push({
        path: resolvedPath,
        name: filename,
        content: processEnvFileZeroKnowledge(content),
        language: "bash",
        redacted: true,
        zeroKnowledge: true,
      });
      continue;
    }

    // For all other files: run through the secret scanner
    let processedContent = content;
    let wasRedacted = false;

    if (redactor?.isInitialized) {
      const result = redactor.redactWithMappings(content);
      if (result.mappings.length > 0) {
        processedContent = result.redacted;
        wasRedacted = true;
      }
    }

    files.push({
      path: resolvedPath,
      name: filename,
      content: processedContent,
      language: getLanguage(filename),
      redacted: wasRedacted,
      zeroKnowledge: false,
    });
  }

  return { files, errors, blocked };
}

/**
 * Format processed files as inline code blocks for message inclusion.
 * Returns text to append to the message.
 */
export function formatFilesForMessage(files: ProcessedFile[]): string {
  if (files.length === 0) return "";

  const parts: string[] = [];

  for (const file of files) {
    const lang = file.language || "";
    const header = file.zeroKnowledge
      ? `[File: ${file.name} — zero-knowledge mode, values hidden]`
      : file.redacted
        ? `[File: ${file.name} — secrets redacted]`
        : `[File: ${file.name}]`;

    parts.push(`\n${header}\n\`\`\`${lang}\n${file.content}\n\`\`\``);
  }

  return parts.join("\n");
}
