/**
 * Paste classification helpers for the message composer.
 *
 * Keeps automatic paste conversion conservative: prose stays editable text,
 * obvious code becomes code embeds, long/formatted documents become docs embeds,
 * and tabular clipboard data becomes sheet embeds.
 * Pure functions live here so the behavior can be unit-tested without Svelte.
 */

export type PastedContentKind = "text" | "code" | "document" | "sheet";

export interface PasteClassificationInput {
  text: string;
  html?: string | null;
  vsCodeLanguage?: string | null;
  detectedLanguage?: string | null;
}

export interface PasteClassificationResult {
  kind: PastedContentKind;
  reason: string;
  sheetMarkdown?: string;
  documentHtml?: string;
}

const LONG_DOCUMENT_MIN_CHARS = 1800;
const LONG_DOCUMENT_MIN_WORDS = 180;
const LONG_DOCUMENT_MIN_LINES = 10;

const CODE_LIKE_LANGUAGES = new Set([
  "bash",
  "c",
  "cpp",
  "css",
  "go",
  "html",
  "java",
  "javascript",
  "json",
  "kotlin",
  "php",
  "python",
  "ruby",
  "rust",
  "sql",
  "svelte",
  "swift",
  "typescript",
  "xml",
  "yaml",
  "zsh",
]);

const DOCUMENT_HTML_TAG_PATTERN = /<(h[1-6]|article|section|blockquote|ol|ul|li)\b/i;
const TABLE_HTML_PATTERN = /<table\b/i;
const MARKDOWN_HEADING_PATTERN = /^#{1,6}\s+\S+/m;
const MARKDOWN_TABLE_SEPARATOR_PATTERN = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/m;

export function classifyPastedContent({
  text,
  html,
  vsCodeLanguage,
  detectedLanguage,
}: PasteClassificationInput): PasteClassificationResult {
  const trimmedText = text.trim();
  const trimmedHtml = html?.trim() || "";

  if (!trimmedText && !trimmedHtml) {
    return { kind: "text", reason: "empty" };
  }

  const htmlTable = extractHtmlTableAsMarkdown(trimmedHtml);
  if (htmlTable) {
    return { kind: "sheet", reason: "html-table", sheetMarkdown: htmlTable };
  }

  const markdownTable = extractMarkdownTable(trimmedText);
  if (markdownTable) {
    return { kind: "sheet", reason: "markdown-table", sheetMarkdown: markdownTable };
  }

  const delimitedTable = extractDelimitedTableAsMarkdown(trimmedText);
  if (delimitedTable) {
    return { kind: "sheet", reason: "delimited-table", sheetMarkdown: delimitedTable };
  }

  if (vsCodeLanguage) {
    return { kind: "code", reason: "vscode" };
  }

  if (hasDocumentFormatting(trimmedText, trimmedHtml)) {
    return {
      kind: "document",
      reason: "formatted-document",
      documentHtml: trimmedHtml || plainTextToDocumentHtml(trimmedText),
    };
  }

  if (isCodeLanguage(detectedLanguage)) {
    return { kind: "code", reason: "language-detection" };
  }

  if (isLongDocument(trimmedText)) {
    return {
      kind: "document",
      reason: "long-prose",
      documentHtml: plainTextToDocumentHtml(trimmedText),
    };
  }

  return { kind: "text", reason: "short-plain-text" };
}

export function plainTextToDocumentHtml(text: string): string {
  const paragraphs = text
    .trim()
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  if (paragraphs.length === 0) return "";

  return paragraphs
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, "<br>")}</p>`)
    .join("\n");
}

function hasDocumentFormatting(text: string, html: string): boolean {
  if (TABLE_HTML_PATTERN.test(html)) return true;
  if (DOCUMENT_HTML_TAG_PATTERN.test(html)) return true;
  if (MARKDOWN_HEADING_PATTERN.test(text)) return true;
  return false;
}

function isLongDocument(text: string): boolean {
  const words = text.split(/\s+/).filter(Boolean).length;
  const lines = text.split("\n").filter((line) => line.trim()).length;
  return (
    text.length >= LONG_DOCUMENT_MIN_CHARS ||
    words >= LONG_DOCUMENT_MIN_WORDS ||
    lines >= LONG_DOCUMENT_MIN_LINES
  );
}

function isCodeLanguage(language?: string | null): boolean {
  return !!language && CODE_LIKE_LANGUAGES.has(language.toLowerCase());
}

function extractMarkdownTable(text: string): string | null {
  if (!text.includes("|") || !MARKDOWN_TABLE_SEPARATOR_PATTERN.test(text)) return null;

  const lines = text.split("\n").map((line) => line.trim());
  const tableLines = lines.filter((line) => line.startsWith("|") && line.endsWith("|"));
  if (tableLines.length < 2) return null;

  return tableLines.join("\n");
}

function extractDelimitedTableAsMarkdown(text: string): string | null {
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) return null;

  const delimiter = lines.some((line) => line.includes("\t")) ? "\t" : ",";
  if (delimiter === "," && !lines.every((line) => line.includes(","))) return null;
  if (delimiter === "," && lines.length < 3) return null;

  const rows = lines.map((line) => splitDelimitedRow(line, delimiter));
  const columnCount = rows[0]?.length || 0;
  if (columnCount < 2 || !rows.every((row) => row.length === columnCount)) return null;

  return rowsToMarkdownTable(rows);
}

function extractHtmlTableAsMarkdown(html: string): string | null {
  if (!TABLE_HTML_PATTERN.test(html)) return null;

  const rowMatches = Array.from(html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi));
  const rows = rowMatches
    .map((rowMatch) => {
      const cells = Array.from(rowMatch[1].matchAll(/<t[hd]\b[^>]*>([\s\S]*?)<\/t[hd]>/gi))
        .map((cellMatch) => htmlToPlainText(cellMatch[1]));
      return cells;
    })
    .filter((row) => row.length > 0);

  if (rows.length < 2) return null;
  const columnCount = rows[0].length;
  if (columnCount < 2) return null;

  return rowsToMarkdownTable(rows.map((row) => padRow(row, columnCount)));
}

function splitDelimitedRow(line: string, delimiter: string): string[] {
  if (delimiter === "\t") return line.split("\t").map((cell) => cell.trim());

  return line.split(",").map((cell) => cell.trim().replace(/^"|"$/g, ""));
}

function rowsToMarkdownTable(rows: string[][]): string {
  const [header, ...body] = rows;
  const safeHeader = header.map(escapeTableCell);
  const separator = safeHeader.map(() => "---");
  const safeBody = body.map((row) => row.map(escapeTableCell));
  return [safeHeader, separator, ...safeBody]
    .map((row) => `| ${row.join(" | ")} |`)
    .join("\n");
}

function padRow(row: string[], columnCount: number): string[] {
  return [...row, ...Array(Math.max(0, columnCount - row.length)).fill("")].slice(0, columnCount);
}

function escapeTableCell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();
}

function htmlToPlainText(html: string): string {
  return html
    .replace(/<br\s*\/?\s*>/gi, " ")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
