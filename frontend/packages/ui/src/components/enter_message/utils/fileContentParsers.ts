// frontend/packages/ui/src/components/enter_message/utils/fileContentParsers.ts
//
// Lightweight client-side parsers for uploaded text-like files.
// These intentionally avoid heavy document dependencies: they support simple
// CSV/TSV, RFC822-style EML, and minimal Office Open XML extraction so PII
// redaction can happen before embed content leaves the browser.

import JSZip from "jszip";

export interface ParsedEmailFile {
  receiver: string;
  subject: string;
  content: string;
  footer: string;
}

const EML_HEADER_SEPARATOR = /\r?\n\r?\n/;
const XLSX_CELL_REF_RE = /^([A-Z]+)(\d+)$/i;

function escapeMarkdownCell(value: string): string {
  return value.replace(/\|/g, "\\|").replace(/\r?\n/g, " ").trim();
}

function parseDelimitedLine(line: string, delimiter: string): string[] {
  const cells: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
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

export function delimitedTextToMarkdownTable(text: string, delimiter: "," | "\t"): string {
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

function unfoldHeaders(rawHeaders: string): string[] {
  return rawHeaders
    .replace(/\r?\n[\t ]+/g, " ")
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0);
}

function getHeader(headers: string[], name: string): string {
  const prefix = `${name.toLowerCase()}:`;
  const line = headers.find((candidate) => candidate.toLowerCase().startsWith(prefix));
  return line ? line.slice(line.indexOf(":") + 1).trim() : "";
}

function decodeQuotedPrintable(value: string): string {
  return value
    .replace(/=\r?\n/g, "")
    .replace(/=([A-Fa-f0-9]{2})/g, (_, hex: string) =>
      String.fromCharCode(parseInt(hex, 16)),
    );
}

function stripHtml(html: string): string {
  return html
    .replace(/<br\s*\/?>(\s*)/gi, "\n")
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .trim();
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function getXmlDocument(xml: string): Document {
  return new DOMParser().parseFromString(xml, "application/xml");
}

function getElementsByLocalName(parent: ParentNode, localName: string): Element[] {
  return Array.from(parent.getElementsByTagName("*")).filter(
    (element) => element.localName === localName,
  );
}

function getDirectChildrenByLocalName(parent: Element | Document, localName: string): Element[] {
  return Array.from(parent.children).filter((element) => element.localName === localName);
}

function getTextFromDocxParagraph(paragraph: Element): string {
  const parts: string[] = [];
  for (const element of getElementsByLocalName(paragraph, "t")) {
    parts.push(element.textContent || "");
  }

  if (parts.length > 0) {
    return parts.join("");
  }

  return paragraph.textContent?.trim() || "";
}

export async function docxArrayBufferToHtml(buffer: ArrayBuffer): Promise<string> {
  const zip = await JSZip.loadAsync(buffer);
  const documentXml = await zip.file("word/document.xml")?.async("string");
  if (!documentXml) return "";

  const xml = getXmlDocument(documentXml);
  const paragraphs = getElementsByLocalName(xml, "p")
    .map(getTextFromDocxParagraph)
    .map((text) => text.trim())
    .filter(Boolean);

  if (paragraphs.length === 0) return "";
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
  const doc = getXmlDocument(xml);
  return getElementsByLocalName(doc, "si").map((item) =>
    getElementsByLocalName(item, "t").map((textNode) => textNode.textContent || "").join(""),
  );
}

function getFirstWorksheetPath(zip: JSZip, workbookXml: string | undefined): string {
  if (!workbookXml) return "xl/worksheets/sheet1.xml";

  const workbook = getXmlDocument(workbookXml);
  const firstSheet = getElementsByLocalName(workbook, "sheet")[0];
  const relationshipId = firstSheet?.getAttribute("r:id");
  if (!relationshipId) return "xl/worksheets/sheet1.xml";

  const relsXml = zip.file("xl/_rels/workbook.xml.rels");
  if (!relsXml) return "xl/worksheets/sheet1.xml";

  // Relationship resolution happens in the caller after async file loading.
  return relationshipId;
}

async function resolveWorksheetPath(zip: JSZip): Promise<string> {
  const workbookXml = await zip.file("xl/workbook.xml")?.async("string");
  const relationshipIdOrPath = getFirstWorksheetPath(zip, workbookXml);
  if (relationshipIdOrPath.startsWith("xl/")) return relationshipIdOrPath;

  const relsXml = await zip.file("xl/_rels/workbook.xml.rels")?.async("string");
  if (!relsXml) return "xl/worksheets/sheet1.xml";

  const rels = getXmlDocument(relsXml);
  const relationship = getElementsByLocalName(rels, "Relationship").find(
    (element) => element.getAttribute("Id") === relationshipIdOrPath,
  );
  const target = relationship?.getAttribute("Target") || "worksheets/sheet1.xml";
  return target.startsWith("/") ? target.slice(1) : `xl/${target.replace(/^\.\.\//, "")}`;
}

function getCellValue(cell: Element, sharedStrings: string[]): string {
  const type = cell.getAttribute("t");
  if (type === "inlineStr") {
    return getElementsByLocalName(cell, "t").map((textNode) => textNode.textContent || "").join("");
  }

  const value = getDirectChildrenByLocalName(cell, "v")[0]?.textContent || "";
  if (type === "s") {
    return sharedStrings[Number(value)] || "";
  }
  if (type === "b") {
    return value === "1" ? "TRUE" : "FALSE";
  }
  return value;
}

export async function xlsxArrayBufferToMarkdownTable(buffer: ArrayBuffer): Promise<string> {
  const zip = await JSZip.loadAsync(buffer);
  const sharedStrings = parseSharedStrings(await zip.file("xl/sharedStrings.xml")?.async("string"));
  const worksheetPath = await resolveWorksheetPath(zip);
  const sheetXml = await zip.file(worksheetPath)?.async("string");
  if (!sheetXml) return "";

  const sheet = getXmlDocument(sheetXml);
  const rows = getElementsByLocalName(sheet, "row").map((row) => {
    const cells: string[] = [];
    for (const cell of getDirectChildrenByLocalName(row, "c")) {
      const cellRef = cell.getAttribute("r") || "";
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

function extractMultipartBody(body: string, contentType: string): string {
  const boundaryMatch = contentType.match(/boundary="?([^";]+)"?/i);
  const boundary = boundaryMatch?.[1];
  if (!boundary) return body;

  const parts = body.split(`--${boundary}`);
  const textParts: Array<{ contentType: string; body: string }> = [];

  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed || trimmed === "--") continue;
    const separatorMatch = trimmed.match(EML_HEADER_SEPARATOR);
    if (!separatorMatch || separatorMatch.index === undefined) continue;
    const partHeaders = unfoldHeaders(trimmed.slice(0, separatorMatch.index));
    const partBody = trimmed.slice(separatorMatch.index + separatorMatch[0].length);
    textParts.push({
      contentType: getHeader(partHeaders, "Content-Type").toLowerCase(),
      body: partBody,
    });
  }

  const plain = textParts.find((part) => part.contentType.includes("text/plain"));
  if (plain) return plain.body;

  const html = textParts.find((part) => part.contentType.includes("text/html"));
  if (html) return stripHtml(html.body);

  return body;
}

export function parseEmlText(text: string): ParsedEmailFile {
  const separatorMatch = text.match(EML_HEADER_SEPARATOR);
  const headerText = separatorMatch?.index !== undefined ? text.slice(0, separatorMatch.index) : "";
  const bodyText = separatorMatch?.index !== undefined
    ? text.slice(separatorMatch.index + separatorMatch[0].length)
    : text;
  const headers = unfoldHeaders(headerText);
  const contentType = getHeader(headers, "Content-Type");
  const transferEncoding = getHeader(headers, "Content-Transfer-Encoding").toLowerCase();
  let body = extractMultipartBody(bodyText, contentType);

  if (transferEncoding === "quoted-printable" || body.includes("=\r\n") || body.includes("=\n")) {
    body = decodeQuotedPrintable(body);
  }
  if (contentType.toLowerCase().includes("text/html")) {
    body = stripHtml(body);
  }

  const from = getHeader(headers, "From");
  const to = getHeader(headers, "To");
  const cc = getHeader(headers, "Cc");
  const date = getHeader(headers, "Date");
  const subject = getHeader(headers, "Subject") || "Uploaded email";
  const footerParts = [from ? `From: ${from}` : "", cc ? `Cc: ${cc}` : "", date ? `Date: ${date}` : ""]
    .filter(Boolean)
    .join("\n");

  return {
    receiver: to,
    subject,
    content: body.trim(),
    footer: footerParts,
  };
}
