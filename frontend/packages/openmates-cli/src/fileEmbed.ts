// frontend/packages/openmates-cli/src/fileEmbed.ts
/**
 * @file CLI file embed support — reads local files referenced via @path
 * in chat messages, creates proper embeds matching the web app's architecture.
 *
 * File handling by type (mirrors web app's fileHandlers.ts):
 *
 * - Code/text files (.ts, .py, .json, .md, etc.):
 *   PII/secret scanned → TOON encoded → encrypted as code-code embed
 *   No S3 upload (same as web app — code lives in encrypted embed content)
 *
 * - Images (.jpg, .png, .webp, .gif, etc.):
 *   Uploaded to S3 via upload.openmates.org → image embed created
 *
 * - PDFs (.pdf):
 *   Uploaded to S3 → PDF embed created → background OCR triggered
 *
 * - Sensitive files (.env, .pem, .key, SSH keys):
 *   .env: zero-knowledge processing (only names + last 3 chars shown)
 *   .pem/.key/SSH: blocked by default
 *
 * File size limit: 100 MB per file (matches web app PER_FILE_MAX_SIZE)
 *
 * Mirrors: fileHandlers.ts, embedHandlers.ts, codeEmbedService.ts, uploadService.ts
 * Architecture: docs/architecture/embeds.md
 */

import { readFileSync, statSync, existsSync } from "node:fs";
import { basename, extname, resolve } from "node:path";
import { homedir } from "node:os";
import { createHash } from "node:crypto";
import type { OutputRedactor } from "./outputRedactor.js";
import {
  generateEmbedId,
  toonEncodeContent,
  createEmbedReferenceBlock,
  computeSHA256,
  type PreparedEmbed,
} from "./embedCreator.js";

// ── Constants (mirrors fileHandlers.ts) ────────────────────────────────

/** Maximum file size: 100 MB per file (same as web app PER_FILE_MAX_SIZE) */
const MAX_PER_FILE_SIZE = 100 * 1024 * 1024;

/** File extensions that are always blocked (private keys, credentials) */
const BLOCKED_EXTENSIONS = new Set([
  ".pem", ".key", ".p12", ".pfx", ".keystore", ".kdbx", ".credentials",
]);

/** File names that are always blocked (SSH keys, cloud credentials) */
const BLOCKED_NAMES = new Set([
  "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa",
  "authorized_keys", "known_hosts",
  ".git-credentials", ".netrc", ".pgpass", ".my.cnf",
]);

/**
 * Code/text file extensions (mirrors web app's isCodeOrTextFile).
 * These get local embed creation with PII scanning, no S3 upload.
 */
const CODE_EXTENSIONS = new Set([
  "py", "js", "ts", "html", "css", "json", "svelte",
  "java", "cpp", "c", "h", "hpp", "rs", "go", "rb", "php", "swift",
  "kt", "txt", "md", "xml", "yaml", "yml", "sh", "bash",
  "sql", "vue", "jsx", "tsx", "scss", "less", "sass",
  "dockerfile", "toml", "ini", "cfg", "conf", "env", "envrc",
  "graphql", "gql", "r", "m", "pl", "lua", "ex", "exs",
  "erl", "hs", "scala", "dart", "tf",
]);

/**
 * Image MIME types supported for S3 upload (mirrors web app + upload server whitelist)
 */
const IMAGE_EXTENSIONS = new Set([
  "jpg", "jpeg", "png", "webp", "gif", "heic", "heif", "bmp", "tiff", "tif", "svg",
]);

/** Check if a filename matches .env or .env.* pattern */
function isEnvFile(filename: string): boolean {
  const lower = filename.toLowerCase();
  return lower === ".env" || lower.startsWith(".env.") || lower === ".envrc";
}

/** Get file extension without the dot, lowercase */
function getExt(filename: string): string {
  const ext = extname(filename).toLowerCase();
  return ext.startsWith(".") ? ext.slice(1) : ext;
}

/** Check if filename is a code/text file */
function isCodeOrTextFile(filename: string): boolean {
  const lower = filename.toLowerCase();
  if (lower === "dockerfile") return true;
  // .env, .env.local, .env.production, .envrc — extname returns "" for dotfiles
  if (isEnvFile(lower)) return true;
  return CODE_EXTENSIONS.has(getExt(filename));
}

/** Check if filename is an image */
function isImageFile(filename: string): boolean {
  return IMAGE_EXTENSIONS.has(getExt(filename));
}

/** Check if filename is a PDF */
function isPDFFile(filename: string): boolean {
  return getExt(filename) === "pdf";
}

// ── Language detection ─────────────────────────────────────────────────

const LANGUAGE_MAP: Record<string, string> = {
  ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  py: "python", rb: "ruby", rs: "rust", go: "go",
  java: "java", kt: "kotlin", swift: "swift",
  c: "c", cpp: "cpp", h: "c", hpp: "cpp", cs: "csharp",
  php: "php", sql: "sql", sh: "bash", bash: "bash", zsh: "bash",
  yml: "yaml", yaml: "yaml", json: "json", xml: "xml",
  html: "html", css: "css", scss: "scss", less: "less",
  md: "markdown", toml: "toml", ini: "ini", cfg: "ini",
  env: "bash", envrc: "bash", svelte: "svelte", vue: "vue",
  graphql: "graphql", gql: "graphql", tf: "hcl", dart: "dart",
  dockerfile: "dockerfile", txt: "text",
};

function detectLanguage(filename: string): string {
  if (filename.toLowerCase() === "dockerfile") return "dockerfile";
  return LANGUAGE_MAP[getExt(filename)] || "text";
}

// ── Result types ───────────────────────────────────────────────────────

/** Result of processing a file for embed creation */
export interface ProcessedFileEmbed {
  /** The prepared embed (ready for encryption) */
  embed: PreparedEmbed;
  /** Embed reference block to insert into message content */
  referenceBlock: string;
  /** Display name for user feedback */
  displayName: string;
  /** Whether secrets were redacted */
  secretsRedacted: boolean;
  /** Whether this was zero-knowledge .env processing */
  zeroKnowledge: boolean;
  /** Whether this requires S3 upload (images, PDFs) */
  requiresUpload: boolean;
  /** For upload files: the local file path for upload */
  localPath?: string;
}

/** Error from file processing */
export interface FileError {
  path: string;
  error: string;
}

/** Complete result of processing all file references */
export interface FileProcessResult {
  /** Successfully processed files (ready for embed creation) */
  embeds: ProcessedFileEmbed[];
  /** Files that could not be processed */
  errors: FileError[];
  /** Files that were blocked (sensitive) */
  blocked: FileError[];
}

// ── .env zero-knowledge processing ─────────────────────────────────────

/**
 * Process .env files with zero-knowledge handling.
 * Shows only variable names and last 3 characters of values.
 */
function processEnvFileZeroKnowledge(content: string): string {
  const lines = content.split("\n");
  const processed: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      processed.push(line);
      continue;
    }

    const cleanLine = line.startsWith("export ") ? line.slice(7).trim() : line;
    const eqIndex = cleanLine.indexOf("=");
    if (eqIndex === -1) {
      processed.push(line);
      continue;
    }

    const key = cleanLine.slice(0, eqIndex).trim();
    let value = cleanLine.slice(eqIndex + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    if (value.length > 3) {
      processed.push(`${key}=***${value.slice(-3)}`);
    } else if (value.length > 0) {
      processed.push(`${key}=***`);
    } else {
      processed.push(`${key}=`);
    }
  }

  return processed.join("\n");
}

// ── Path resolution ────────────────────────────────────────────────────

function resolvePath(filePath: string): string {
  if (filePath.startsWith("~/")) {
    return resolve(homedir(), filePath.slice(2));
  }
  return resolve(filePath);
}

// ── Main processing ────────────────────────────────────────────────────

/**
 * Process a list of file paths for embed creation.
 * Routes each file to the appropriate handler based on type.
 *
 * @param filePaths Array of file paths from @mention parsing
 * @param redactor Output redactor for secret scanning file content
 * @returns Processed embeds, errors, and blocked files
 */
export function processFiles(
  filePaths: string[],
  redactor: OutputRedactor | null,
): FileProcessResult {
  const embeds: ProcessedFileEmbed[] = [];
  const errors: FileError[] = [];
  const blocked: FileError[] = [];

  for (const rawPath of filePaths) {
    const resolvedPath = resolvePath(rawPath);
    const filename = basename(resolvedPath);
    const ext = getExt(filename);

    // Validate existence
    if (!existsSync(resolvedPath)) {
      errors.push({ path: rawPath, error: "File not found" });
      continue;
    }

    // Validate stats
    let stats;
    try {
      stats = statSync(resolvedPath);
    } catch (e) {
      errors.push({
        path: rawPath,
        error: `Cannot read: ${e instanceof Error ? e.message : String(e)}`,
      });
      continue;
    }

    if (stats.isDirectory()) {
      errors.push({ path: rawPath, error: "Is a directory, not a file" });
      continue;
    }

    if (stats.size > MAX_PER_FILE_SIZE) {
      errors.push({
        path: rawPath,
        error: `File too large (${Math.round(stats.size / 1024 / 1024)}MB > 100MB limit)`,
      });
      continue;
    }

    // Check blocked files
    if (BLOCKED_EXTENSIONS.has(`.${ext}`)) {
      blocked.push({
        path: rawPath,
        error: `Blocked: .${ext} files may contain private keys. Use --allow-sensitive to override.`,
      });
      continue;
    }

    if (BLOCKED_NAMES.has(filename)) {
      blocked.push({
        path: rawPath,
        error: `Blocked: '${filename}' typically contains credentials. Use --allow-sensitive to override.`,
      });
      continue;
    }

    // Route by file type
    if (isCodeOrTextFile(filename)) {
      const result = processCodeFile(resolvedPath, filename, redactor);
      if (result) embeds.push(result);
      else errors.push({ path: rawPath, error: "Failed to process file" });
    } else if (isImageFile(filename)) {
      const result = processImageFile(resolvedPath, filename);
      if (result) embeds.push(result);
      else errors.push({ path: rawPath, error: "Failed to process image" });
    } else if (isPDFFile(filename)) {
      const result = processPDFFile(resolvedPath, filename);
      if (result) embeds.push(result);
      else errors.push({ path: rawPath, error: "Failed to process PDF" });
    } else {
      errors.push({
        path: rawPath,
        error: `Unsupported file type: .${ext}. Supported: code/text, images, PDFs.`,
      });
    }
  }

  return { embeds, errors, blocked };
}

// ── File type handlers ─────────────────────────────────────────────────

/**
 * Process a code/text file into a code-code embed.
 * Content is PII/secret scanned, TOON-encoded.
 * No S3 upload — content lives in the encrypted embed.
 *
 * Mirrors: codeEmbedService.ts createCodeEmbed()
 */
function processCodeFile(
  filePath: string,
  filename: string,
  redactor: OutputRedactor | null,
): ProcessedFileEmbed | null {
  try {
    let content = readFileSync(filePath, "utf-8");
    let secretsRedacted = false;
    let zeroKnowledge = false;

    // .env files: zero-knowledge processing
    if (isEnvFile(filename)) {
      content = processEnvFileZeroKnowledge(content);
      secretsRedacted = true;
      zeroKnowledge = true;
    } else if (redactor?.isInitialized) {
      // Run through secret scanner for other text files
      const result = redactor.redactWithMappings(content);
      if (result.mappings.length > 0) {
        content = result.redacted;
        secretsRedacted = true;
      }
    }

    const language = detectLanguage(filename);
    const lineCount = content.split("\n").length;

    // Build TOON content (mirrors codeEmbedService.ts)
    const embedContent = toonEncodeContent({
      type: "code",
      language,
      code: content,
      filename,
      status: "finished",
      line_count: lineCount,
    });

    const embedId = generateEmbedId();
    const textPreview = `${filename} (${language}, ${lineCount} lines)`;
    const contentHash = createHash("sha256").update(content).digest("hex");

    const embed: PreparedEmbed = {
      embedId,
      type: "code-code",
      content: embedContent,
      textPreview,
      status: "finished",
      filePath: filename,
      contentHash,
      textLengthChars: content.length,
    };

    return {
      embed,
      referenceBlock: createEmbedReferenceBlock("code", embedId),
      displayName: filename,
      secretsRedacted,
      zeroKnowledge,
      requiresUpload: false,
    };
  } catch (e) {
    process.stderr.write(
      `\x1b[31mError:\x1b[0m Failed to read ${filename}: ${e instanceof Error ? e.message : String(e)}\n`,
    );
    return null;
  }
}

/**
 * Process an image file for S3 upload.
 * The actual upload happens later in the send pipeline.
 *
 * Mirrors: embedHandlers.ts insertImage() + _performUpload()
 */
function processImageFile(
  filePath: string,
  filename: string,
): ProcessedFileEmbed | null {
  try {
    const embedId = generateEmbedId();

    // Create a placeholder embed — real content comes from upload response
    const embedContent = toonEncodeContent({
      type: "image",
      app_id: "images",
      skill_id: "upload",
      status: "uploading",
      filename,
    });

    const embed: PreparedEmbed = {
      embedId,
      type: "image",
      content: embedContent,
      textPreview: filename,
      status: "finished", // Will be set to "finished" after upload
    };

    return {
      embed,
      referenceBlock: createEmbedReferenceBlock("image", embedId),
      displayName: filename,
      secretsRedacted: false,
      zeroKnowledge: false,
      requiresUpload: true,
      localPath: filePath,
    };
  } catch (e) {
    process.stderr.write(
      `\x1b[31mError:\x1b[0m Failed to process ${filename}: ${e instanceof Error ? e.message : String(e)}\n`,
    );
    return null;
  }
}

/**
 * Process a PDF file for S3 upload.
 *
 * Mirrors: embedHandlers.ts insertPDF()
 */
function processPDFFile(
  filePath: string,
  filename: string,
): ProcessedFileEmbed | null {
  try {
    const embedId = generateEmbedId();

    const embedContent = toonEncodeContent({
      type: "pdf",
      status: "uploading",
      filename,
    });

    const embed: PreparedEmbed = {
      embedId,
      type: "pdf",
      content: embedContent,
      textPreview: filename,
      status: "processing", // PDFs start as "processing" for background OCR
    };

    return {
      embed,
      referenceBlock: createEmbedReferenceBlock("pdf", embedId),
      displayName: filename,
      secretsRedacted: false,
      zeroKnowledge: false,
      requiresUpload: true,
      localPath: filePath,
    };
  } catch (e) {
    process.stderr.write(
      `\x1b[31mError:\x1b[0m Failed to process ${filename}: ${e instanceof Error ? e.message : String(e)}\n`,
    );
    return null;
  }
}

/**
 * Format embed reference blocks for message content.
 * Returns text to append to the message (embed JSON references).
 */
export function formatEmbedsForMessage(embeds: ProcessedFileEmbed[]): string {
  if (embeds.length === 0) return "";
  return "\n" + embeds.map((e) => e.referenceBlock).join("\n");
}
