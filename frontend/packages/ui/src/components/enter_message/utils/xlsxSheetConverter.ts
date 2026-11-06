// frontend/packages/ui/src/components/enter_message/utils/xlsxSheetConverter.ts
//
// Converts an uploaded .xlsx workbook into one sheet-embed markdown table per
// visible worksheet. Formulas the sheet formula engine supports are kept (and
// rewritten to its data-row coordinates); everything else (macros, charts,
// pivots, images, styling, unsupported formulas ...) is dropped and reported in
// `removed` so the UI can tell the user. Nothing in the workbook is executed.
//
// Coordinates: the engine counts DATA rows (the first row below the header is
// row 1) and columns start at A, so Excel row R becomes R - headerRow.
// Architecture: components/embeds/sheets/sheetFormulaEngine.ts

import JSZip from "jszip";

export type XlsxRemovedFeature =
  | "formatting"
  | "conditional_formatting"
  | "merged_cells"
  | "charts"
  | "images"
  | "pivot_tables"
  | "macros"
  | "external_links"
  | "comments"
  | "unsupported_formulas"
  | "hidden_sheets"
  | "sheet_limit";

export interface ConvertedXlsxSheet {
  name: string;
  markdown: string;
  rowCount: number;
  colCount: number;
}

export interface ConvertedXlsxWorkbook {
  sheets: ConvertedXlsxSheet[];
  removed: XlsxRemovedFeature[];
}

/** Keep in sync with FUNCTIONS in components/embeds/sheets/sheetFormulaEngine.ts. */
export const SUPPORTED_SHEET_FUNCTIONS: ReadonlySet<string> = new Set([
  "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "ABS", "SQRT", "POWER", "MOD", "ROUND",
  "ROUNDUP", "ROUNDDOWN", "CEILING", "FLOOR", "AND", "OR", "NOT", "TRUE", "FALSE",
  "CONCAT", "IF", "IFERROR",
]);

const MAX_SHEETS = 10;
const CELL_RE = /<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g;
const REF_RE = /(?<![A-Za-z0-9_.!'$])(\$?)([A-Za-z]{1,3})(\$?)(\d+)(?![A-Za-z0-9_(])/g;
const BUILTIN_DATE_FORMATS = new Set([
  14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50,
  51, 52, 53, 54, 55, 56, 57, 58,
]);

function decodeXml(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, code: string) => String.fromCodePoint(Number(code)))
    .replace(/&amp;/g, "&");
}

function attr(attrs: string, name: string): string | null {
  const match = attrs.match(new RegExp(`(?:^|\\s)${name}="([^"]*)"`));
  return match ? decodeXml(match[1]) : null;
}

function textOf(xml: string): string {
  return Array.from(xml.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g))
    .map((m) => decodeXml(m[1]))
    .join("");
}

function colToIndex(letters: string): number {
  return letters.toUpperCase().split("").reduce((acc, ch) => acc * 26 + ch.charCodeAt(0) - 64, 0) - 1;
}

function indexToCol(index: number): string {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

// ── Number formats ──────────────────────────────────────────────────────────

type CellKind = "date" | "time" | "percent" | "plain";

function classifyFormat(numFmtId: number, code: string | undefined): CellKind {
  if (numFmtId === 9 || numFmtId === 10) return "percent";
  if (BUILTIN_DATE_FORMATS.has(numFmtId)) return numFmtId >= 18 && numFmtId <= 21 ? "time" : "date";
  if (!code) return "plain";
  const stripped = code.replace(/"[^"]*"/g, "").replace(/\[[^\]]*\]/g, "").replace(/\\./g, "");
  if (stripped.includes("%")) return "percent";
  if (/[yd]/i.test(stripped)) return "date";
  if (/[hs]/i.test(stripped)) return "time";
  return "plain";
}

interface StyleInfo {
  kinds: CellKind[];
  filled: boolean[];
}

function parseStyles(stylesXml: string | undefined): StyleInfo {
  const info: StyleInfo = { kinds: [], filled: [] };
  if (!stylesXml) return info;
  const customCodes = new Map<number, string>();
  for (const m of stylesXml.matchAll(/<numFmt\b([^>]*?)\/?>/g)) {
    const id = attr(m[1], "numFmtId");
    const code = attr(m[1], "formatCode");
    if (id !== null && code !== null) customCodes.set(Number(id), code);
  }
  const xfBlock = stylesXml.match(/<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/)?.[1] ?? "";
  for (const m of xfBlock.matchAll(/<xf\b([^>]*?)(?:\/>|>)/g)) {
    const numFmtId = Number(attr(m[1], "numFmtId") ?? 0);
    info.kinds.push(classifyFormat(numFmtId, customCodes.get(numFmtId)));
    info.filled.push(Number(attr(m[1], "fillId") ?? 0) >= 2);
  }
  return info;
}

function serialToText(serial: number, kind: "date" | "time", date1904: boolean): string {
  const epoch = date1904 ? Date.UTC(1904, 0, 1) : Date.UTC(1899, 11, 30);
  const d = new Date(epoch + Math.round(serial * 86400000));
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  if (kind === "time") return time;
  const day = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  return time === "00:00" ? day : `${day} ${time}`;
}

function cleanNumber(raw: string): string {
  const n = Number(raw);
  return Number.isFinite(n) ? String(Number(n.toPrecision(15))) : raw;
}

// ── Formula translation ─────────────────────────────────────────────────────

/** Apply `fn` to the parts of a formula outside of "string literals". */
function mapOutsideStrings(formula: string, fn: (segment: string) => string): string {
  let out = "";
  let i = 0;
  while (i < formula.length) {
    if (formula[i] === '"') {
      let j = i + 1;
      while (j < formula.length) {
        if (formula[j] === '"') {
          if (formula[j + 1] === '"') { j += 2; continue; }
          break;
        }
        j++;
      }
      out += formula.slice(i, j + 1);
      i = j + 1;
    } else {
      let j = formula.indexOf('"', i);
      if (j === -1) j = formula.length;
      out += fn(formula.slice(i, j));
      i = j;
    }
  }
  return out;
}

/** Shift relative references (shared formulas): children reuse the master text. */
function shiftFormula(formula: string, dRow: number, dCol: number): string {
  return mapOutsideStrings(formula, (segment) =>
    segment.replace(REF_RE, (_m, absCol: string, col: string, absRow: string, row: string) => {
      const nextCol = absCol ? col : indexToCol(colToIndex(col) + dCol);
      const nextRow = absRow ? row : String(Number(row) + dRow);
      return `${absCol}${nextCol}${absRow}${nextRow}`;
    }),
  );
}

interface FormulaContext {
  headerRow: number;
  headerIsText: (colIndex: number) => boolean;
  isDateCell: (col: number, row: number) => boolean;
}

const RANGE_OR_REF_RE =
  /(?<![A-Za-z0-9_.!'$])(\$?[A-Za-z]{1,3}\$?\d+)(?![A-Za-z0-9_(])(?:\s*:\s*(\$?[A-Za-z]{1,3}\$?\d+)(?![A-Za-z0-9_(]))?/g;

/** Returns an engine formula ("=...") or null when it can't be represented. */
function translateFormula(source: string, ctx: FormulaContext): string | null {
  if (/[|{}@\n]/.test(source)) return null;
  let supported = true;
  const translated = mapOutsideStrings(source, (segment) => {
    if (/['![\]#]/.test(segment)) { supported = false; return segment; }
    for (const m of segment.matchAll(/([A-Za-z_][A-Za-z0-9_.]*)\s*\(/g)) {
      if (!SUPPORTED_SHEET_FUNCTIONS.has(m[1].toUpperCase())) supported = false;
    }
    const withoutRefs = segment
      .replace(/[A-Za-z_][A-Za-z0-9_.]*\s*\(/g, "(")
      .replace(RANGE_OR_REF_RE, "");
    // A leftover ":" means whole-column/row ranges (A:A, 1:1) the engine can't read.
    if (withoutRefs.includes(":")) supported = false;
    for (const name of withoutRefs.match(/(?<![0-9.])[A-Za-z_][A-Za-z0-9_.]*/g) ?? []) {
      if (!["TRUE", "FALSE"].includes(name.toUpperCase())) supported = false;
    }
    return segment.replace(RANGE_OR_REF_RE, (match: string, from: string, to: string | undefined) => {
      const start = rewriteRef(from, ctx, to !== undefined, to ?? null);
      const end = to === undefined ? null : rewriteRef(to, ctx, false, null);
      if (start === null || (to !== undefined && end === null)) { supported = false; return match; }
      return to === undefined ? start : `${start}:${end}`;
    });
  });
  return supported ? `=${translated.trim()}` : null;
}

/**
 * Rewrite one Excel A1 reference to engine coordinates. `isRangeStart` lets a
 * range that begins on the header row start at data row 1 (headers are text and
 * ignored by the supported aggregate functions).
 */
function rewriteRef(ref: string, ctx: FormulaContext, isRangeStart: boolean, otherEnd: string | null): string | null {
  const match = ref.match(/^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$/);
  if (!match) return null;
  const [, absCol, col, absRow, rowText] = match;
  const colIndex = colToIndex(col);
  const row = Number(rowText);
  let dataRow = row - ctx.headerRow;
  if (ctx.isDateCell(colIndex, row)) return null;
  if (dataRow < 1) {
    const otherRow = otherEnd ? Number(otherEnd.match(/(\d+)$/)?.[1] ?? 0) : 0;
    const spansData = isRangeStart && otherRow - ctx.headerRow >= 1;
    if (!spansData || !ctx.headerIsText(colIndex)) return null;
    dataRow = 1;
  }
  return `${absCol}${col.toUpperCase()}${absRow}${dataRow}`;
}

// ── Worksheet parsing ───────────────────────────────────────────────────────

interface RawCell {
  col: number;
  row: number;
  value: string;
  kind: CellKind;
  isText: boolean;
  formula: string | null;
  filled: boolean;
}

function readWorksheet(
  xml: string,
  sharedStrings: string[],
  styles: StyleInfo,
  date1904: boolean,
): { raw: RawCell[]; merged: boolean; conditional: boolean } {
  const raw: RawCell[] = [];
  const sheetData = xml.match(/<sheetData\b[^>]*>([\s\S]*?)<\/sheetData>/)?.[1] ?? "";
  const shared = new Map<string, { text: string; row: number; col: number }>();
  for (const m of sheetData.matchAll(CELL_RE)) {
    const attrs = m[1];
    const body = m[2] ?? "";
    const ref = attr(attrs, "r")?.match(/^([A-Za-z]+)(\d+)$/);
    if (!ref) continue;
    const col = colToIndex(ref[1]);
    const row = Number(ref[2]);
    const type = attr(attrs, "t");
    const styleIndex = Number(attr(attrs, "s") ?? 0);
    const kind = styles.kinds[styleIndex] ?? "plain";

    let value = "";
    let isText = false;
    const v = body.match(/<v\b[^>]*>([\s\S]*?)<\/v>/)?.[1];
    if (type === "inlineStr") {
      value = textOf(body);
      isText = true;
    } else if (type === "s") {
      value = sharedStrings[Number(v)] ?? "";
      isText = true;
    } else if (type === "str" || type === "e") {
      value = decodeXml(v ?? "");
      isText = true;
    } else if (type === "b") {
      value = v === "1" ? "TRUE" : "FALSE";
      isText = true;
    } else if (v !== undefined && v.trim() !== "") {
      const num = Number(v);
      if (kind === "date" || kind === "time") value = serialToText(num, kind, date1904);
      else if (kind === "percent") value = `${Number((num * 100).toPrecision(12))}%`;
      else value = cleanNumber(v);
    }

    let formula: string | null = null;
    const f = body.match(/<f\b([^>]*?)(?:\/>|>([\s\S]*?)<\/f>)/);
    if (f) {
      const fType = attr(f[1], "t");
      const si = attr(f[1], "si");
      let text = decodeXml(f[2] ?? "");
      if (fType === "array") {
        text = "{array}";
      } else if (fType === "shared" && si !== null) {
        if (text) shared.set(si, { text, row, col });
        else {
          const master = shared.get(si);
          if (master) text = shiftFormula(master.text, row - master.row, col - master.col);
        }
      }
      if (formula === null) formula = text || "";
    }
    raw.push({ col, row, value, kind, isText, formula, filled: styles.filled[styleIndex] === true });
  }
  return {
    raw,
    merged: /<mergeCell\b/.test(xml),
    conditional: /<conditionalFormatting\b/.test(xml),
  };
}

function toMarkdown(raw: RawCell[]): { result: ConvertedXlsxSheet; unsupported: boolean; filled: boolean } | null {
  const populated = raw.filter((c) => c.value.trim() !== "" || (c.formula ?? "") !== "");
  if (populated.length === 0) return null;

  const headerRow = Math.min(...populated.map((c) => c.row));
  const lastRow = Math.max(...populated.map((c) => c.row));
  const colCount = Math.max(...populated.map((c) => c.col)) + 1;
  const byPos = new Map<string, RawCell>();
  for (const cell of raw) byPos.set(`${cell.col}:${cell.row}`, cell);

  const headerIsText = (col: number) => {
    const cell = byPos.get(`${col}:${headerRow}`);
    return !cell || cell.isText || cell.value.trim() === "";
  };
  const ctx: FormulaContext = {
    headerRow,
    headerIsText,
    isDateCell: (col, row) => {
      const kind = byPos.get(`${col}:${row}`)?.kind;
      return kind === "date" || kind === "time";
    },
  };

  let unsupported = false;
  const escape = (text: string) => text.replace(/\|/g, "¦").replace(/\r?\n/g, " ").trim();
  const lines: string[] = [];
  for (let row = headerRow; row <= lastRow; row++) {
    const cells: string[] = [];
    for (let col = 0; col < colCount; col++) {
      const cell = byPos.get(`${col}:${row}`);
      let text = cell ? cell.value : "";
      if (cell && cell.formula) {
        const translated = row > headerRow ? translateFormula(cell.formula, ctx) : null;
        if (translated) text = translated;
        else unsupported = true;
      } else if (/^\s*=/.test(text)) {
        text = `'${text.trim()}`; // literal text that merely starts with "=" must not become a formula
      }
      cells.push(escape(text));
    }
    lines.push(`| ${cells.join(" | ")} |`);
    if (row === headerRow) lines.push(`| ${new Array(colCount).fill("---").join(" | ")} |`);
  }
  while (lines.length > 2 && /^\|(\s*\|)+$/.test(lines[lines.length - 1])) lines.pop();

  return {
    result: {
      name: "",
      markdown: lines.join("\n"),
      rowCount: lines.length - 2,
      colCount,
    },
    unsupported,
    filled: populated.some((c) => c.filled),
  };
}

// ── Workbook ────────────────────────────────────────────────────────────────

function resolveTarget(target: string): string {
  if (target.startsWith("/")) return target.slice(1);
  return `xl/${target.replace(/^\.\//, "")}`;
}

export async function convertXlsxWorkbook(buffer: ArrayBuffer): Promise<ConvertedXlsxWorkbook> {
  const zip = await JSZip.loadAsync(buffer);
  const removed = new Set<XlsxRemovedFeature>();
  const fileNames = Object.keys(zip.files);
  if (fileNames.some((n) => n.startsWith("xl/vbaProject"))) removed.add("macros");
  if (fileNames.some((n) => n.startsWith("xl/charts/"))) removed.add("charts");
  if (fileNames.some((n) => n.startsWith("xl/media/"))) removed.add("images");
  if (fileNames.some((n) => n.startsWith("xl/pivotTables/") || n.startsWith("xl/pivotCache/"))) removed.add("pivot_tables");
  if (fileNames.some((n) => n.startsWith("xl/externalLinks/"))) removed.add("external_links");
  if (fileNames.some((n) => /^xl\/(comments|threadedComments)/.test(n))) removed.add("comments");

  const workbookXml = (await zip.file("xl/workbook.xml")?.async("string")) ?? "";
  const relsXml = (await zip.file("xl/_rels/workbook.xml.rels")?.async("string")) ?? "";
  const sharedXml = await zip.file("xl/sharedStrings.xml")?.async("string");
  const styles = parseStyles(await zip.file("xl/styles.xml")?.async("string"));
  const date1904 = /<workbookPr\b[^>]*date1904="(1|true)"/.test(workbookXml);
  const sharedStrings = sharedXml
    ? Array.from(sharedXml.matchAll(/<si\b[^>]*>([\s\S]*?)<\/si>/g)).map((m) => textOf(m[1]))
    : [];

  const relTargets = new Map<string, string>();
  for (const m of relsXml.matchAll(/<Relationship\b([^>]*?)\/?>/g)) {
    const id = attr(m[1], "Id");
    const target = attr(m[1], "Target");
    if (id && target) relTargets.set(id, resolveTarget(target));
  }

  const declared = Array.from(workbookXml.matchAll(/<sheet\b([^>]*?)\/?>/g)).map((m) => ({
    name: attr(m[1], "name") ?? "Sheet",
    hidden: (attr(m[1], "state") ?? "visible") !== "visible",
    path: relTargets.get(attr(m[1], "r:id") ?? "") ?? "",
  }));
  if (declared.length === 0) declared.push({ name: "Sheet1", hidden: false, path: "xl/worksheets/sheet1.xml" });

  const sheets: ConvertedXlsxSheet[] = [];
  for (const sheet of declared) {
    if (sheet.hidden) { removed.add("hidden_sheets"); continue; }
    if (sheets.length >= MAX_SHEETS) { removed.add("sheet_limit"); continue; }
    const xml = await zip.file(sheet.path)?.async("string");
    if (!xml) continue;
    const parsed = readWorksheet(xml, sharedStrings, styles, date1904);
    if (parsed.merged) removed.add("merged_cells");
    if (parsed.conditional) removed.add("conditional_formatting");
    const table = toMarkdown(parsed.raw);
    if (!table) continue;
    if (table.unsupported) removed.add("unsupported_formulas");
    if (table.filled) removed.add("formatting");
    sheets.push({ ...table.result, name: sheet.name });
  }

  return { sheets, removed: Array.from(removed) };
}
