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
 * - Audio (.mp3, .wav, .webm, etc.):
 *   Uploaded to S3 → audio-recording embed created for audio.transcribe
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
import JSZip from "jszip";
import type { OutputRedactor } from "./outputRedactor.js";
import {
  createEmbedRef,
  generateEmbedId,
  toonEncodeContent,
  createEmbedReferenceBlock,
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

/** Audio file extensions supported by the upload service and audio.transcribe skill. */
const AUDIO_EXTENSIONS = new Set([
  "mp3", "m4a", "mp4", "wav", "webm", "ogg", "oga", "aac",
]);

/** Text table file extensions converted locally into sheets-sheet embeds. */
const DELIMITED_TABLE_EXTENSIONS = new Set(["csv", "tsv"]);

/** Minimal Office Open XML documents converted locally so PII is redacted before send. */
const DOC_EXTENSIONS = new Set(["docx"]);

/** Minimal Office Open XML spreadsheets converted locally so PII is redacted before send. */
const SHEET_EXTENSIONS = new Set(["xlsx"]);

const XLSX_CELL_REF_RE = /^([A-Z]+)(\d+)$/i;

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

/** Check if filename is an audio file. */
function isAudioFile(filename: string): boolean {
  return AUDIO_EXTENSIONS.has(getExt(filename));
}

function isDelimitedTableFile(filename: string): boolean {
  return DELIMITED_TABLE_EXTENSIONS.has(getExt(filename));
}

function isDocFile(filename: string): boolean {
  return DOC_EXTENSIONS.has(getExt(filename));
}

function isSheetFile(filename: string): boolean {
  return SHEET_EXTENSIONS.has(getExt(filename));
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

function escapeMarkdownCell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\r?\n/g, " ").trim();
}

function parseDelimitedLine(line: string, delimiter: string): string[] {
  const cells: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    const next = line[i + 1];

    if (char === '"') {
      if (inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === delimiter && !inQuotes) {
      cells.push(current);
      current = "";
      continue;
    }

    current += char;
  }

  cells.push(current);
  return cells;
}

function delimitedTextToMarkdownTable(text: string, delimiter: "," | "\t"): string {
  const rows = text
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0)
    .map((line) => parseDelimitedLine(line, delimiter));

  if (rows.length === 0) return "";
  const maxCols = Math.max(...rows.map((row) => row.length));
  const normalized = rows.map((row) => {
    const next = [...row];
    while (next.length < maxCols) next.push("");
    return next.map(escapeMarkdownCell);
  });

  const [header, ...body] = normalized;
  const divider = new Array(maxCols).fill("---");
  return [header, divider, ...body]
    .map((row) => `| ${row.join(" | ")} |`)
    .join("\n");
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function decodeXmlText(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function getXmlBlocks(xml: string, localName: string): string[] {
  const pattern = new RegExp(`<(?:[\\w-]+:)?${localName}\\b[^>]*>([\\s\\S]*?)<\\/(?:[\\w-]+:)?${localName}>`, "gi");
  return Array.from(xml.matchAll(pattern)).map((match) => match[1] || "");
}

function getXmlElements(xml: string, localName: string): Array<{ attrs: string; body: string }> {
  const pattern = new RegExp(`<(?:[\\w-]+:)?${localName}\\b([^>]*)>([\\s\\S]*?)<\\/(?:[\\w-]+:)?${localName}>`, "gi");
  return Array.from(xml.matchAll(pattern)).map((match) => ({
    attrs: match[1] || "",
    body: match[2] || "",
  }));
}

function getXmlStartTags(xml: string, localName: string): string[] {
  const pattern = new RegExp(`<(?:[\\w-]+:)?${localName}\\b([^>]*)/?>`, "gi");
  return Array.from(xml.matchAll(pattern)).map((match) => match[1] || "");
}

function getXmlAttribute(attrs: string, name: string): string | null {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = attrs.match(new RegExp(`(?:^|\\s)${escaped}="([^"]*)"`, "i"));
  return match?.[1] || null;
}

function getTextFromDocxParagraph(paragraphXml: string): string {
  const textRuns = getXmlBlocks(paragraphXml, "t").map(decodeXmlText);
  if (textRuns.length > 0) return textRuns.join("");
  return decodeXmlText(paragraphXml.replace(/<[^>]+>/g, "")).trim();
}

async function docxBufferToHtml(buffer: Buffer): Promise<string> {
  const zip = await JSZip.loadAsync(buffer);
  const documentXml = await zip.file("word/document.xml")?.async("string");
  if (!documentXml) return "";

  const paragraphs = getXmlBlocks(documentXml, "p")
    .map(getTextFromDocxParagraph)
    .map((text) => text.trim())
    .filter(Boolean);

  return paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("\n");
}

function columnLettersToIndex(letters: string): number {
  let index = 0;
  for (const char of letters.toUpperCase()) {
    index = index * 26 + char.charCodeAt(0) - 64;
  }
  return index - 1;
}

function parseSharedStrings(xml: string | undefined): string[] {
  if (!xml) return [];
  return getXmlBlocks(xml, "si").map((item) =>
    getXmlBlocks(item, "t").map(decodeXmlText).join(""),
  );
}

async function resolveWorksheetPath(zip: JSZip): Promise<string> {
  const workbookXml = await zip.file("xl/workbook.xml")?.async("string");
  const firstSheet = workbookXml ? getXmlStartTags(workbookXml, "sheet")[0] : undefined;
  const relationshipId = firstSheet ? getXmlAttribute(firstSheet, "r:id") : null;
  if (!relationshipId) return "xl/worksheets/sheet1.xml";

  const relsXml = await zip.file("xl/_rels/workbook.xml.rels")?.async("string");
  if (!relsXml) return "xl/worksheets/sheet1.xml";

  const relationship = getXmlStartTags(relsXml, "Relationship").find(
    (attrs) => getXmlAttribute(attrs, "Id") === relationshipId,
  );
  const target = relationship ? getXmlAttribute(relationship, "Target") || "worksheets/sheet1.xml" : "worksheets/sheet1.xml";
  return target.startsWith("/") ? target.slice(1) : `xl/${target.replace(/^\.\.\//, "")}`;
}

function getCellValue(cell: { attrs: string; body: string }, sharedStrings: string[]): string {
  const type = getXmlAttribute(cell.attrs, "t");
  if (type === "inlineStr") {
    return getXmlBlocks(cell.body, "t").map(decodeXmlText).join("");
  }

  const value = decodeXmlText(getXmlBlocks(cell.body, "v")[0] || "");
  if (type === "s") return sharedStrings[Number(value)] || "";
  if (type === "b") return value === "1" ? "TRUE" : "FALSE";
  return value;
}

async function xlsxBufferToMarkdownTable(buffer: Buffer): Promise<string> {
  const zip = await JSZip.loadAsync(buffer);
  const sharedStrings = parseSharedStrings(await zip.file("xl/sharedStrings.xml")?.async("string"));
  const worksheetPath = await resolveWorksheetPath(zip);
  const sheetXml = await zip.file(worksheetPath)?.async("string");
  if (!sheetXml) return "";

  const rows = getXmlBlocks(sheetXml, "row").map((row) => {
    const cells: string[] = [];
    for (const cell of getXmlElements(row, "c")) {
      const cellRef = getXmlAttribute(cell.attrs, "r") || "";
      const match = cellRef.match(XLSX_CELL_REF_RE);
      const index = match ? columnLettersToIndex(match[1]) : cells.length;
      cells[index] = getCellValue(cell, sharedStrings);
    }
    return cells.map((cell) => cell || "");
  }).filter((row) => row.some((cell) => cell.trim().length > 0));

  if (rows.length === 0) return "";
  const maxCols = Math.max(...rows.map((row) => row.length));
  const csvLike = rows.map((row) => {
    const next = [...row];
    while (next.length < maxCols) next.push("");
    return next.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",");
  }).join("\n");
  return delimitedTextToMarkdownTable(csvLike, ",");
}

function redactContent(content: string, redactor: OutputRedactor | null): {
  content: string;
  secretsRedacted: boolean;
} {
  if (!redactor?.isInitialized) return { content, secretsRedacted: false };
  const result = redactor.redactWithMappings(content);
  return {
    content: result.redacted,
    secretsRedacted: result.mappings.length > 0,
  };
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
  /** Whether this requires S3 upload (images, PDFs, audio) */
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
    if (isDelimitedTableFile(filename)) {
      const result = processDelimitedTableFile(resolvedPath, filename, redactor);
      if (result) embeds.push(result);
      else errors.push({ path: rawPath, error: "Failed to process table file" });
    } else if (isDocFile(filename) || isSheetFile(filename)) {
      errors.push({
        path: rawPath,
        error: `Office file .${ext} requires async processing; use processFilesAsync().`,
      });
    } else if (isCodeOrTextFile(filename)) {
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
    } else if (isAudioFile(filename)) {
      const result = processAudioFile(resolvedPath, filename);
      if (result) embeds.push(result);
      else errors.push({ path: rawPath, error: "Failed to process audio" });
    } else {
      errors.push({
        path: rawPath,
        error: `Unsupported file type: .${ext}. Supported: code/text, images, PDFs, audio.`,
      });
    }
  }

  return { embeds, errors, blocked };
}

/** Async variant used by chat sends so DOCX/XLSX can be parsed before upload/send. */
export async function processFilesAsync(
  filePaths: string[],
  redactor: OutputRedactor | null,
): Promise<FileProcessResult> {
  const syncPaths: string[] = [];
  const embeds: ProcessedFileEmbed[] = [];
  const errors: FileError[] = [];
  const blocked: FileError[] = [];

  for (const rawPath of filePaths) {
    const resolvedPath = resolvePath(rawPath);
    const filename = basename(resolvedPath);
    const ext = getExt(filename);

    if (!isDocFile(filename) && !isSheetFile(filename)) {
      syncPaths.push(rawPath);
      continue;
    }

    if (!existsSync(resolvedPath)) {
      errors.push({ path: rawPath, error: "File not found" });
      continue;
    }

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

    try {
      const result = isDocFile(filename)
        ? await processDocxFile(resolvedPath, filename, redactor)
        : await processXlsxFile(resolvedPath, filename, redactor);
      if (result) embeds.push(result);
      else errors.push({ path: rawPath, error: `Failed to process .${ext} file` });
    } catch (e) {
      errors.push({
        path: rawPath,
        error: `Failed to process .${ext} file: ${e instanceof Error ? e.message : String(e)}`,
      });
    }
  }

  const syncResult = processFiles(syncPaths, redactor);
  embeds.push(...syncResult.embeds);
  errors.push(...syncResult.errors);
  blocked.push(...syncResult.blocked);

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

    const embedId = generateEmbedId();
    const embedRef = createEmbedRef("code", `${filename}:${embedId}`);

    // Build TOON content (mirrors codeEmbedService.ts)
    const embedContent = toonEncodeContent({
      type: "code",
      language,
      code: content,
      filename,
      embed_ref: embedRef,
      status: "finished",
      line_count: lineCount,
    });

    const textPreview = `${filename} (${language}, ${lineCount} lines)`;
    const contentHash = createHash("sha256").update(content).digest("hex");

    const embed: PreparedEmbed = {
      embedId,
      embedRef,
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
      referenceBlock: createEmbedReferenceBlock(embedRef),
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

function processDelimitedTableFile(
  filePath: string,
  filename: string,
  redactor: OutputRedactor | null,
): ProcessedFileEmbed | null {
  try {
    const delimiter = getExt(filename) === "tsv" ? "\t" : ",";
    const tableMarkdown = delimitedTextToMarkdownTable(readFileSync(filePath, "utf-8"), delimiter);
    return createSheetFileEmbed(tableMarkdown, filename, redactor);
  } catch (e) {
    process.stderr.write(
      `\x1b[31mError:\x1b[0m Failed to read ${filename}: ${e instanceof Error ? e.message : String(e)}\n`,
    );
    return null;
  }
}

async function processDocxFile(
  filePath: string,
  filename: string,
  redactor: OutputRedactor | null,
): Promise<ProcessedFileEmbed | null> {
  const html = await docxBufferToHtml(readFileSync(filePath));
  if (!html) return null;
  const { content, secretsRedacted } = redactContent(html, redactor);
  const wordCount = content.split(/\s+/).filter((word) => word.trim()).length;
  const embedId = generateEmbedId();
  const embedRef = createEmbedRef("docs-doc", `${filename}:${embedId}`);
  const embedContent = toonEncodeContent({
    type: "docs-doc",
    title: filename,
    filename,
    html: content,
    code: content,
    word_count: wordCount,
    status: "finished",
    embed_ref: embedRef,
  });

  return {
    embed: {
      embedId,
      embedRef,
      type: "docs-doc",
      content: embedContent,
      textPreview: filename,
      status: "finished",
      filePath: filename,
      contentHash: createHash("sha256").update(content).digest("hex"),
      textLengthChars: content.length,
    },
    referenceBlock: createEmbedReferenceBlock(embedRef),
    displayName: filename,
    secretsRedacted,
    zeroKnowledge: false,
    requiresUpload: false,
  };
}

async function processXlsxFile(
  filePath: string,
  filename: string,
  redactor: OutputRedactor | null,
): Promise<ProcessedFileEmbed | null> {
  const tableMarkdown = await xlsxBufferToMarkdownTable(readFileSync(filePath));
  return tableMarkdown ? createSheetFileEmbed(tableMarkdown, filename, redactor) : null;
}

function createSheetFileEmbed(
  tableMarkdown: string,
  filename: string,
  redactor: OutputRedactor | null,
): ProcessedFileEmbed {
  const { content, secretsRedacted } = redactContent(tableMarkdown, redactor);
  const rows = content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("|") && line.endsWith("|"));
  const headerLine = rows[0] || "";
  const colCount = Math.max(0, (headerLine.match(/\|/g) || []).length - 1);
  const rowCount = Math.max(0, rows.length - 2);
  const embedId = generateEmbedId();
  const embedRef = createEmbedRef("sheet", `${filename}:${embedId}`);
  const embedContent = toonEncodeContent({
    type: "sheet",
    title: filename,
    table: content,
    code: content,
    row_count: rowCount,
    col_count: colCount,
    rows: rowCount,
    cols: colCount,
    status: "finished",
    embed_ref: embedRef,
  });

  return {
    embed: {
      embedId,
      embedRef,
      type: "sheets-sheet",
      content: embedContent,
      textPreview: filename,
      status: "finished",
      filePath: filename,
      contentHash: createHash("sha256").update(content).digest("hex"),
      textLengthChars: content.length,
    },
    referenceBlock: createEmbedReferenceBlock(embedRef),
    displayName: filename,
    secretsRedacted,
    zeroKnowledge: false,
    requiresUpload: false,
  };
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
    const embedRef = createEmbedRef("image", `${filename}:${embedId}`);

    // Create a placeholder embed — real content comes from upload response
    const embedContent = toonEncodeContent({
      type: "image",
      app_id: "images",
      skill_id: "upload",
      status: "uploading",
      filename,
      embed_ref: embedRef,
    });

    const embed: PreparedEmbed = {
      embedId,
      embedRef,
      type: "image",
      content: embedContent,
      textPreview: filename,
      status: "finished", // Will be set to "finished" after upload
    };

    return {
      embed,
      referenceBlock: createEmbedReferenceBlock(embedRef),
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
    const embedRef = createEmbedRef("pdf", `${filename}:${embedId}`);

    const embedContent = toonEncodeContent({
      type: "pdf",
      status: "uploading",
      filename,
      embed_ref: embedRef,
    });

    const embed: PreparedEmbed = {
      embedId,
      embedRef,
      type: "pdf",
      content: embedContent,
      textPreview: filename,
      status: "processing", // PDFs start as "processing" for background OCR
    };

    return {
      embed,
      referenceBlock: createEmbedReferenceBlock(embedRef),
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
 * Process an audio file for S3 upload.
 * The uploaded file becomes an audio-recording embed that audio.transcribe can consume.
 */
function processAudioFile(
  filePath: string,
  filename: string,
): ProcessedFileEmbed | null {
  try {
    const embedId = generateEmbedId();
    const embedRef = `${createEmbedRef("audio-recording", filename)}-${embedId}`;

    const embedContent = toonEncodeContent({
      app_id: "audio",
      skill_id: "transcribe",
      type: "audio-recording",
      status: "uploading",
      filename,
      embed_ref: embedRef,
    });

    const embed: PreparedEmbed = {
      embedId,
      embedRef,
      type: "audio-recording",
      content: embedContent,
      textPreview: filename,
      status: "processing",
    };

    return {
      embed,
      referenceBlock: createEmbedReferenceBlock(embedRef),
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
 * Returns text to append to the message (markdown embed references).
 */
export function formatEmbedsForMessage(embeds: ProcessedFileEmbed[]): string {
  if (embeds.length === 0) return "";
  return "\n" + embeds.map((e) => e.referenceBlock).join("\n");
}
