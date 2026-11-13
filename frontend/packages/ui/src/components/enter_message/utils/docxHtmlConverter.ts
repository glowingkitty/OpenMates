// frontend/packages/ui/src/components/enter_message/utils/docxHtmlConverter.ts
//
// Converts the body of an uploaded .docx into simple, sanitizer-friendly HTML
// for a docs-doc embed: headings, bold/italic/underline runs, bullet and
// numbered lists, tables and line breaks. Images, comments, headers/footers and
// macros are not read. The document is parsed as inert XML text only.

import JSZip from "jszip";

function decodeXml(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, code: string) => String.fromCodePoint(Number(code)))
    .replace(/&amp;/g, "&");
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function wAttr(xml: string, tag: string, name = "val"): string | null {
  const element = xml.match(new RegExp(`<w:${tag}\\b([^>]*?)/?>`));
  if (!element) return null;
  const value = element[1].match(new RegExp(`w:${name}="([^"]*)"`));
  return value ? value[1] : "";
}

function hasToggle(rPr: string, tag: string): boolean {
  const element = rPr.match(new RegExp(`<w:${tag}\\b([^>]*?)/?>`));
  if (!element) return false;
  const val = element[1].match(/w:val="([^"]*)"/)?.[1];
  return val === undefined || !["0", "false", "off", "none"].includes(val);
}

function runToHtml(runXml: string): string {
  const rPr = runXml.match(/<w:rPr\b[^>]*>([\s\S]*?)<\/w:rPr>/)?.[1] ?? "";
  let html = "";
  for (const m of runXml.matchAll(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>|<w:tab\b[^>]*\/>|<w:br\b[^>]*\/>/g)) {
    if (m[0].startsWith("<w:tab")) html += "&emsp;";
    else if (m[0].startsWith("<w:br")) html += "<br>";
    else html += escapeHtml(decodeXml(m[1]));
  }
  if (!html.replace(/<br>|&emsp;/g, "").trim()) return html;
  if (hasToggle(rPr, "b")) html = `<strong>${html}</strong>`;
  if (hasToggle(rPr, "i")) html = `<em>${html}</em>`;
  if (hasToggle(rPr, "u")) html = `<u>${html}</u>`;
  return html;
}

function paragraphInline(paragraphXml: string): string {
  return Array.from(paragraphXml.matchAll(/<w:r\b[^>]*>([\s\S]*?)<\/w:r>/g))
    .map((m) => runToHtml(m[1]))
    .join("")
    .replace(/<\/(strong|em|u)><\1>/g, "");
}

function headingLevel(styleId: string | null): number | null {
  if (!styleId) return null;
  if (/^title$/i.test(styleId)) return 1;
  const match = styleId.match(/^heading\s*([1-6])$/i);
  return match ? Number(match[1]) : null;
}

/** numId → true when the list is ordered (anything but "bullet"). */
function parseNumbering(xml: string | undefined): Map<string, boolean> {
  const ordered = new Map<string, boolean>();
  if (!xml) return ordered;
  const abstractOrdered = new Map<string, boolean>();
  for (const m of xml.matchAll(/<w:abstractNum\b([^>]*)>([\s\S]*?)<\/w:abstractNum>/g)) {
    const id = m[1].match(/w:abstractNumId="([^"]*)"/)?.[1];
    const format = m[2].match(/<w:numFmt\b[^>]*w:val="([^"]*)"/)?.[1];
    if (id !== undefined) abstractOrdered.set(id, format !== "bullet" && format !== "none");
  }
  for (const m of xml.matchAll(/<w:num\b([^>]*)>([\s\S]*?)<\/w:num>/g)) {
    const numId = m[1].match(/w:numId="([^"]*)"/)?.[1];
    const abstractId = m[2].match(/<w:abstractNumId\b[^>]*w:val="([^"]*)"/)?.[1];
    if (numId !== undefined && abstractId !== undefined) ordered.set(numId, abstractOrdered.get(abstractId) ?? false);
  }
  return ordered;
}

function tableToHtml(tableXml: string): string {
  const rows = Array.from(tableXml.matchAll(/<w:tr\b[^>]*>([\s\S]*?)<\/w:tr>/g)).map((row, rowIndex) => {
    const cells = Array.from(row[1].matchAll(/<w:tc\b[^>]*>([\s\S]*?)<\/w:tc>/g)).map((cell) => {
      const text = Array.from(cell[1].matchAll(/<w:p\b[^>]*>([\s\S]*?)<\/w:p>/g))
        .map((p) => paragraphInline(p[1]))
        .filter(Boolean)
        .join("<br>");
      const tag = rowIndex === 0 ? "th" : "td";
      return `<${tag}>${text}</${tag}>`;
    });
    return `<tr>${cells.join("")}</tr>`;
  });
  return rows.length ? `<table>${rows.join("")}</table>` : "";
}

export async function docxArrayBufferToHtml(buffer: ArrayBuffer): Promise<string> {
  const zip = await JSZip.loadAsync(buffer);
  const documentXml = await zip.file("word/document.xml")?.async("string");
  if (!documentXml) return "";
  const numbering = parseNumbering(await zip.file("word/numbering.xml")?.async("string"));
  const body = documentXml.match(/<w:body\b[^>]*>([\s\S]*)<\/w:body>/)?.[1] ?? documentXml;

  const blocks: string[] = [];
  let openList: { tag: "ul" | "ol"; items: string[] } | null = null;
  const closeList = () => {
    if (openList) blocks.push(`<${openList.tag}>${openList.items.map((i) => `<li>${i}</li>`).join("")}</${openList.tag}>`);
    openList = null;
  };

  for (const m of body.matchAll(/<w:tbl\b[^>]*>[\s\S]*?<\/w:tbl>|<w:p\b[^>]*>[\s\S]*?<\/w:p>/g)) {
    if (m[0].startsWith("<w:tbl")) {
      closeList();
      const table = tableToHtml(m[0]);
      if (table) blocks.push(table);
      continue;
    }
    const pPr = m[0].match(/<w:pPr\b[^>]*>([\s\S]*?)<\/w:pPr>/)?.[1] ?? "";
    const inline = paragraphInline(m[0]);
    const text = inline.replace(/<[^>]+>|&emsp;/g, "").trim();
    if (!text) continue;

    const numId = wAttr(pPr, "numId");
    if (numId && numId !== "0") {
      const tag = numbering.get(numId) ? "ol" : "ul";
      if (!openList || openList.tag !== tag) {
        closeList();
        openList = { tag, items: [] };
      }
      openList.items.push(inline);
      continue;
    }
    closeList();
    const level = headingLevel(wAttr(pPr, "pStyle"));
    blocks.push(level ? `<h${level}>${inline}</h${level}>` : `<p>${inline}</p>`);
  }
  closeList();
  return blocks.join("\n");
}
