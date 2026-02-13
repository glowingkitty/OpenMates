/**
 * Sheet/Table embed content utilities
 *
 * Handles parsing and formatting of markdown tables stored in sheet embeds.
 * Tables are stored as markdown in the embed content and rendered as HTML tables.
 */

/**
 * Parsed table cell with alignment info
 */
export interface TableCell {
  content: string;
  align?: "left" | "center" | "right";
}

/**
 * Parsed table structure
 */
export interface ParsedTable {
  headers: TableCell[];
  rows: TableCell[][];
  rowCount: number;
  colCount: number;
}

/**
 * Parse markdown table content into structured table data
 * @param markdownTable - The markdown table string
 * @returns Parsed table structure
 */
export function parseMarkdownTable(markdownTable: string): ParsedTable {
  const lines = markdownTable
    .trim()
    .split("\n")
    .filter((line) => line.trim());

  if (lines.length < 2) {
    // Need at least header and separator
    return { headers: [], rows: [], rowCount: 0, colCount: 0 };
  }

  // Parse header row
  const headerLine = lines[0];
  const headers = parseTableRow(headerLine);
  const colCount = headers.length;

  // Parse separator row to get alignment info
  const separatorLine = lines[1];
  const alignments = parseAlignments(separatorLine, colCount);

  // Apply alignments to headers
  const headersWithAlign: TableCell[] = headers.map((content, i) => ({
    content,
    align: alignments[i],
  }));

  // Parse data rows
  const rows: TableCell[][] = [];
  for (let i = 2; i < lines.length; i++) {
    const rowCells = parseTableRow(lines[i]);
    // Pad or trim to match column count
    const normalizedRow: TableCell[] = [];
    for (let j = 0; j < colCount; j++) {
      normalizedRow.push({
        content: rowCells[j] || "",
        align: alignments[j],
      });
    }
    rows.push(normalizedRow);
  }

  return {
    headers: headersWithAlign,
    rows,
    rowCount: rows.length,
    colCount,
  };
}

/**
 * Parse a single table row into cells
 */
function parseTableRow(line: string): string[] {
  // Remove leading/trailing pipes and split by |
  const trimmed = line.trim();
  const withoutPipes = trimmed.startsWith("|") ? trimmed.slice(1) : trimmed;
  const content = withoutPipes.endsWith("|")
    ? withoutPipes.slice(0, -1)
    : withoutPipes;

  return content.split("|").map((cell) => stripInlineMarkdown(cell.trim()));
}

/**
 * Strip inline markdown formatting from text.
 * Removes bold (**text**), italic (*text*), strikethrough (~~text~~),
 * and inline code (`text`) markers, keeping the inner text.
 */
export function stripInlineMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1") // bold **text**
    .replace(/__(.+?)__/g, "$1") // bold __text__
    .replace(/\*(.+?)\*/g, "$1") // italic *text*
    .replace(/_(.+?)_/g, "$1") // italic _text_
    .replace(/~~(.+?)~~/g, "$1") // strikethrough ~~text~~
    .replace(/`(.+?)`/g, "$1"); // inline code `text`
}

/**
 * Parse alignment separator row
 */
function parseAlignments(
  separatorLine: string,
  colCount: number,
): Array<"left" | "center" | "right" | undefined> {
  const cells = parseTableRow(separatorLine);

  return cells.slice(0, colCount).map((cell) => {
    const trimmed = cell.trim().replace(/\s/g, "");

    // Check for alignment markers
    const hasLeftColon = trimmed.startsWith(":");
    const hasRightColon = trimmed.endsWith(":");

    if (hasLeftColon && hasRightColon) {
      return "center";
    } else if (hasRightColon) {
      return "right";
    } else if (hasLeftColon) {
      return "left";
    }

    // Default is left
    return undefined;
  });
}

/**
 * Parse sheet embed content to extract table markdown and metadata
 * @param content - TOON-decoded embed content or raw markdown
 * @param overrides - Optional overrides for title
 * @returns Parsed table content and metadata
 */
export function parseSheetEmbedContent(
  content: string | Record<string, unknown>,
  overrides?: { title?: string },
): { markdown: string; title?: string; parsedTable: ParsedTable } {
  let markdown = "";
  let title = overrides?.title;

  if (typeof content === "object" && content !== null) {
    // TOON-decoded content object - cast to access properties safely
    const contentObj = content as Record<string, string | undefined>;
    markdown = (contentObj.code ||
      contentObj.table ||
      contentObj.content ||
      "") as string;
    if (!title && typeof contentObj.title === "string") {
      title = contentObj.title;
    }
  } else if (typeof content === "string") {
    markdown = content;
  }

  // Extract title from HTML comment if present
  // Format: <!-- title: "My Table" -->
  if (!title) {
    const titleMatch = markdown.match(/<!--\s*title:\s*"([^"]+)"\s*-->/);
    if (titleMatch) {
      title = titleMatch[1];
      // Remove the title comment from markdown
      markdown = markdown
        .replace(/<!--\s*title:\s*"[^"]+"\s*-->\n?/, "")
        .trim();
    }
  }

  const parsedTable = parseMarkdownTable(markdown);

  return { markdown, title, parsedTable };
}

/**
 * Count rows in a markdown table (excluding header and separator)
 */
export function countTableRows(markdownTable: string): number {
  const lines = markdownTable
    .trim()
    .split("\n")
    .filter((line) => line.trim() && line.includes("|"));
  // Subtract 2 for header and separator rows
  return Math.max(0, lines.length - 2);
}

/**
 * Count columns in a markdown table
 */
export function countTableColumns(markdownTable: string): number {
  const lines = markdownTable
    .trim()
    .split("\n")
    .filter((line) => line.trim());
  if (lines.length === 0) return 0;

  // Count pipes in header row
  const headerLine = lines[0].trim();
  const withoutLeadingPipe = headerLine.startsWith("|")
    ? headerLine.slice(1)
    : headerLine;
  const withoutTrailingPipe = withoutLeadingPipe.endsWith("|")
    ? withoutLeadingPipe.slice(0, -1)
    : withoutLeadingPipe;

  return withoutTrailingPipe.split("|").length;
}

/**
 * Format table dimensions for display
 * @param rows - Number of data rows
 * @param cols - Number of columns
 * @returns Formatted string like "5 rows × 3 columns"
 */
export function formatTableDimensions(rows: number, cols: number): string {
  const rowText = rows === 1 ? "row" : "rows";
  const colText = cols === 1 ? "column" : "columns";
  return `${rows} ${rowText} × ${cols} ${colText}`;
}

/**
 * Convert markdown table to CSV format
 */
export function markdownTableToCSV(markdownTable: string): string {
  const parsed = parseMarkdownTable(markdownTable);
  const lines: string[] = [];

  // Add header row
  lines.push(parsed.headers.map((h) => escapeCSVCell(h.content)).join(","));

  // Add data rows
  for (const row of parsed.rows) {
    lines.push(row.map((cell) => escapeCSVCell(cell.content)).join(","));
  }

  return lines.join("\n");
}

/**
 * Escape a cell value for CSV
 */
function escapeCSVCell(value: string): string {
  // If contains comma, quote, or newline, wrap in quotes and escape internal quotes
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}
