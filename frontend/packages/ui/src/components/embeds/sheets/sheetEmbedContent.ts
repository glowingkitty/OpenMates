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

// ═══════════════════════════════════════════════════════════════════════════════
// TSV export — tab-separated values for clipboard paste into Excel/Google Sheets
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Convert headers + rows to TSV (tab-separated values) string.
 * TSV is the format Excel and Google Sheets expect when pasting from clipboard.
 * Tabs inside cell content are replaced with spaces to avoid column misalignment.
 */
export function tableToTSV(headers: TableCell[], rows: TableCell[][]): string {
  const lines: string[] = [];
  lines.push(headers.map((h) => h.content.replace(/\t/g, " ")).join("\t"));
  for (const row of rows) {
    lines.push(row.map((cell) => cell.content.replace(/\t/g, " ")).join("\t"));
  }
  return lines.join("\n");
}

// ═══════════════════════════════════════════════════════════════════════════════
// XLSX export — minimal Office Open XML generator, zero external dependencies.
//
// An .xlsx file is a ZIP archive containing XML files:
//   [Content_Types].xml       — declares part types
//   _rels/.rels               — package relationships
//   xl/workbook.xml           — workbook with sheet list
//   xl/_rels/workbook.xml.rels — workbook relationships
//   xl/styles.xml             — cell styles (bold header row)
//   xl/worksheets/sheet1.xml  — the actual cell data
//   xl/sharedStrings.xml      — string table for cell values
//
// We build the ZIP using the browser-native CompressionStream (deflate-raw)
// with a manual ZIP container. All modern browsers support this API.
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Generate an .xlsx Blob from headers and data rows.
 * Uses the browser-native CompressionStream API for deflate compression.
 */
export async function tableToXlsx(
  headers: TableCell[],
  rows: TableCell[][],
  sheetName = "Sheet1",
): Promise<Blob> {
  // 1. Build shared string table (all unique cell values)
  const sharedStrings: string[] = [];
  const stringIndex = new Map<string, number>();

  function getStringIndex(value: string): number {
    let idx = stringIndex.get(value);
    if (idx === undefined) {
      idx = sharedStrings.length;
      sharedStrings.push(value);
      stringIndex.set(value, idx);
    }
    return idx;
  }

  // Index all header and data cell values
  for (const h of headers) getStringIndex(h.content);
  for (const row of rows) {
    for (const cell of row) getStringIndex(cell.content);
  }

  // 2. Build sheet XML
  const sheetXml = buildSheetXml(headers, rows, getStringIndex);

  // 3. Build shared strings XML
  const sharedStringsXml = buildSharedStringsXml(sharedStrings);

  // 4. Build all required OOXML parts
  const files: Record<string, string> = {
    "[Content_Types].xml": contentTypesXml(),
    "_rels/.rels": relsXml(),
    "xl/workbook.xml": workbookXml(sheetName),
    "xl/_rels/workbook.xml.rels": workbookRelsXml(),
    "xl/styles.xml": stylesXml(),
    "xl/worksheets/sheet1.xml": sheetXml,
    "xl/sharedStrings.xml": sharedStringsXml,
  };

  // 5. Create ZIP archive
  return await createZipBlob(files);
}

/**
 * Convert a column index (0-based) to Excel column letter(s).
 * 0 → A, 1 → B, …, 25 → Z, 26 → AA, 27 → AB, etc.
 */
function colIndexToLetter(index: number): string {
  let result = "";
  let n = index;
  while (n >= 0) {
    result = String.fromCharCode((n % 26) + 65) + result;
    n = Math.floor(n / 26) - 1;
  }
  return result;
}

/** XML-escape special characters in cell content */
function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Build the worksheet XML with cell references pointing to shared strings.
 * Header row uses style index 1 (bold). Data rows use style index 0 (default).
 */
function buildSheetXml(
  headers: TableCell[],
  rows: TableCell[][],
  getStringIndex: (value: string) => number,
): string {
  const colCount = headers.length;
  const lastCol = colIndexToLetter(colCount - 1);
  const lastRow = rows.length + 1; // +1 for header row

  let xml =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"' +
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n' +
    `<dimension ref="A1:${lastCol}${lastRow}"/>\n` +
    "<sheetData>\n";

  // Header row (row 1) with bold style (s="1")
  xml += '<row r="1">\n';
  for (let c = 0; c < colCount; c++) {
    const ref = `${colIndexToLetter(c)}1`;
    const si = getStringIndex(headers[c].content);
    xml += `<c r="${ref}" t="s" s="1"><v>${si}</v></c>\n`;
  }
  xml += "</row>\n";

  // Data rows (row 2+)
  for (let r = 0; r < rows.length; r++) {
    const rowNum = r + 2;
    xml += `<row r="${rowNum}">\n`;
    for (let c = 0; c < colCount; c++) {
      const ref = `${colIndexToLetter(c)}${rowNum}`;
      const cellContent = rows[r][c]?.content ?? "";
      const si = getStringIndex(cellContent);
      xml += `<c r="${ref}" t="s"><v>${si}</v></c>\n`;
    }
    xml += "</row>\n";
  }

  xml += "</sheetData>\n</worksheet>";
  return xml;
}

/** Build the shared strings XML table */
function buildSharedStringsXml(strings: string[]): string {
  let xml =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    `<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="${strings.length}" uniqueCount="${strings.length}">\n`;
  for (const s of strings) {
    xml += `<si><t>${escapeXml(s)}</t></si>\n`;
  }
  xml += "</sst>";
  return xml;
}

/** [Content_Types].xml — declares the MIME types for each part */
function contentTypesXml(): string {
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
    '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>' +
    "</Types>"
  );
}

/** Package-level relationships */
function relsXml(): string {
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
    "</Relationships>"
  );
}

/** Workbook XML listing the sheets */
function workbookXml(sheetName: string): string {
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"' +
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
    `<sheets><sheet name="${escapeXml(sheetName)}" sheetId="1" r:id="rId1"/></sheets>` +
    "</workbook>"
  );
}

/** Workbook relationships — links sheet and shared strings */
function workbookRelsXml(): string {
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>' +
    "</Relationships>"
  );
}

/**
 * Minimal styles.xml — defines two cell formats:
 *   index 0 = default (normal text)
 *   index 1 = bold (for header row)
 */
function stylesXml(): string {
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    "<fonts>" +
    '<font><sz val="11"/><name val="Calibri"/></font>' +
    '<font><b/><sz val="11"/><name val="Calibri"/></font>' +
    "</fonts>" +
    '<fills><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>' +
    "<borders><border/></borders>" +
    '<cellStyleXfs count="1"><xf/></cellStyleXfs>' +
    "<cellXfs>" +
    "<xf/>" +
    '<xf fontId="1" applyFont="1"/>' +
    "</cellXfs>" +
    "</styleSheet>"
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Minimal ZIP archive builder using browser-native CompressionStream
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Create a ZIP Blob from a map of file paths → UTF-8 string content.
 * Uses STORE method (no compression) for maximum compatibility. The files
 * are small XML so compression savings are negligible.
 */
async function createZipBlob(files: Record<string, string>): Promise<Blob> {
  const encoder = new TextEncoder();
  const entries: Array<{
    name: Uint8Array;
    data: Uint8Array;
    crc: number;
    offset: number;
  }> = [];

  const parts: Uint8Array[] = [];
  let offset = 0;

  // Write local file headers + file data
  for (const [path, content] of Object.entries(files)) {
    const nameBytes = encoder.encode(path);
    const dataBytes = encoder.encode(content);
    const crc = crc32(dataBytes);

    // Local file header (30 bytes + name + data)
    const header = new Uint8Array(30 + nameBytes.length);
    const view = new DataView(header.buffer);
    view.setUint32(0, 0x04034b50, true); // local file header signature
    view.setUint16(4, 20, true); // version needed (2.0)
    view.setUint16(6, 0, true); // general purpose bit flag
    view.setUint16(8, 0, true); // compression method: STORE
    view.setUint16(10, 0, true); // last mod time
    view.setUint16(12, 0, true); // last mod date
    view.setUint32(14, crc, true); // crc-32
    view.setUint32(18, dataBytes.length, true); // compressed size
    view.setUint32(22, dataBytes.length, true); // uncompressed size
    view.setUint16(26, nameBytes.length, true); // file name length
    view.setUint16(28, 0, true); // extra field length
    header.set(nameBytes, 30);

    entries.push({ name: nameBytes, data: dataBytes, crc, offset });
    parts.push(header);
    parts.push(dataBytes);
    offset += header.length + dataBytes.length;
  }

  // Write central directory
  const centralStart = offset;
  for (const entry of entries) {
    const cdHeader = new Uint8Array(46 + entry.name.length);
    const cdView = new DataView(cdHeader.buffer);
    cdView.setUint32(0, 0x02014b50, true); // central directory header signature
    cdView.setUint16(4, 20, true); // version made by
    cdView.setUint16(6, 20, true); // version needed
    cdView.setUint16(8, 0, true); // flags
    cdView.setUint16(10, 0, true); // compression: STORE
    cdView.setUint16(12, 0, true); // last mod time
    cdView.setUint16(14, 0, true); // last mod date
    cdView.setUint32(16, entry.crc, true); // crc-32
    cdView.setUint32(20, entry.data.length, true); // compressed size
    cdView.setUint32(24, entry.data.length, true); // uncompressed size
    cdView.setUint16(28, entry.name.length, true); // file name length
    cdView.setUint16(30, 0, true); // extra field length
    cdView.setUint16(32, 0, true); // file comment length
    cdView.setUint16(34, 0, true); // disk number start
    cdView.setUint16(36, 0, true); // internal file attributes
    cdView.setUint32(38, 0, true); // external file attributes
    cdView.setUint32(42, entry.offset, true); // relative offset of local header
    cdHeader.set(entry.name, 46);
    parts.push(cdHeader);
    offset += cdHeader.length;
  }

  const centralSize = offset - centralStart;

  // End of central directory record (22 bytes)
  const eocd = new Uint8Array(22);
  const eocdView = new DataView(eocd.buffer);
  eocdView.setUint32(0, 0x06054b50, true); // end of central dir signature
  eocdView.setUint16(4, 0, true); // disk number
  eocdView.setUint16(6, 0, true); // disk with central dir
  eocdView.setUint16(8, entries.length, true); // entries on this disk
  eocdView.setUint16(10, entries.length, true); // total entries
  eocdView.setUint32(12, centralSize, true); // central directory size
  eocdView.setUint32(16, centralStart, true); // central directory offset
  eocdView.setUint16(20, 0, true); // comment length
  parts.push(eocd);

  return new Blob(parts as BlobPart[], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

/**
 * CRC-32 implementation (ISO 3309 / ITU-T V.42).
 * Used for ZIP local file headers and central directory entries.
 */
function crc32(data: Uint8Array): number {
  // Build CRC table on first call (lazy singleton)
  if (!crc32Table) {
    crc32Table = new Uint32Array(256);
    for (let i = 0; i < 256; i++) {
      let c = i;
      for (let j = 0; j < 8; j++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      crc32Table[i] = c;
    }
  }

  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc = crc32Table[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** Lazy-initialized CRC-32 lookup table */
let crc32Table: Uint32Array | null = null;
