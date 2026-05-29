// frontend/packages/ui/src/components/enter_message/utils/fileContentParsers.ts
//
// Lightweight client-side parsers for uploaded text-like files.
// These intentionally avoid heavy document dependencies: they support simple
// CSV/TSV and RFC822-style EML extraction so PII redaction can happen before
// embed content leaves the browser.
// Complex binary formats remain unsupported here unless parsed by a small,
// explicitly reviewed dependency or the existing upload pipeline.

export interface ParsedEmailFile {
  receiver: string;
  subject: string;
  content: string;
  footer: string;
}

const EML_HEADER_SEPARATOR = /\r?\n\r?\n/;

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
