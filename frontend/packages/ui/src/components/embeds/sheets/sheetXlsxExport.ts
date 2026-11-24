/** Encode display formatting as ordinary OOXML cell styles and layout. */
import type { SheetBorderSide, SheetCellStyle, SheetFormatting, SheetNumberFormat } from "./sheetFormattingTypes";
import { sheetPixels } from "./sheetFormattingPresentation";

const RGB = /^#[a-f0-9]{6}$/i;
const SIDES: SheetBorderSide[] = ["left", "right", "top", "bottom"];
const BORDER_STYLES = new Set(["thin", "medium", "thick", "dashed", "dotted", "double"]);

function argb(value: unknown): string | undefined {
  return typeof value === "string" && RGB.test(value) ? `FF${value.slice(1).toUpperCase()}` : undefined;
}

function formatCode(format: SheetNumberFormat | undefined): string | undefined {
  if (!format) return undefined;
  if (format.kind === "date") {
    return ["yyyy-mm-dd", "mm/dd/yyyy", "dd/mm/yyyy", "mmm d, yyyy"].includes(format.pattern)
      ? format.pattern : undefined;
  }
  const decimals = sheetPixels(format.decimals, 0, 10) ?? (format.kind === "currency" ? 2 : 0);
  const number = `#,##0${decimals ? "." + "0".repeat(decimals) : ""}`;
  if (format.kind === "percent") return `${number}%`;
  if (format.kind === "currency" && typeof format.currency === "string" && /^[A-Z]{3}$/.test(format.currency)) {
    return `[$${format.currency}]${number}`;
  }
  return format.kind === "number" ? number : undefined;
}

export function xlsxNumericValue(value: string, format: SheetNumberFormat | undefined): number | undefined {
  if (format?.kind === "date") {
    const iso = /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : undefined;
    if (!iso) return undefined;
    const date = new Date(`${iso}T00:00:00Z`);
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== iso) return undefined;
    const serial = (date.getTime() - Date.UTC(1899, 11, 30)) / 86400000;
    return serial < 61 ? serial - 1 : serial;
  }
  const percentage = format?.kind === "percent" && value.endsWith("%");
  const raw = percentage ? value.slice(0, -1) : value;
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw.trim())) return undefined;
  const numeric = Number(raw) / (percentage ? 100 : 1);
  return Number.isFinite(numeric) ? numeric : undefined;
}

export function xlsxSheetLayout(
  formatting: SheetFormatting | undefined,
  columns: string[],
  rowCount: number,
  columnLabel: (index: number) => string,
) {
  const frozenColumns = sheetPixels(formatting?.frozenColumns, 0, columns.length) ?? 0;
  const frozenRows = sheetPixels(formatting?.frozenRows, 0, rowCount) ?? 0;
  const activePane = frozenRows && frozenColumns ? "bottomRight" : frozenRows ? "bottomLeft" : "topRight";
  const pane = frozenRows || frozenColumns
    ? `<sheetViews><sheetView workbookViewId="0"><pane${frozenColumns ? ` xSplit="${frozenColumns}"` : ""}${frozenRows ? ` ySplit="${frozenRows}"` : ""} topLeftCell="${columnLabel(frozenColumns)}${frozenRows + 1}" activePane="${activePane}" state="frozen"/></sheetView></sheetViews>`
    : "";
  const colXml = columns.map((letter, index) => {
    const width = sheetPixels(formatting?.columnWidths?.[letter], 24, 1200);
    return width ? `<col min="${index + 1}" max="${index + 1}" width="${(width - 5) / 7}" customWidth="1"/>` : "";
  }).join("");
  const mergeXml = Array.isArray(formatting?.merges) ? formatting.merges.slice(0, 256).filter((merge) => (
    /^[A-Z]{1,3}[1-9]\d{0,3}$/.test(merge?.start) && /^[A-Z]{1,3}[1-9]\d{0,3}$/.test(merge?.end)
  )).map(({ start, end }) => `<mergeCell ref="${start}:${end}"/>`) : [];
  return {
    pane,
    columns: colXml ? `<cols>${colXml}</cols>` : "",
    merges: mergeXml.length ? `<mergeCells count="${mergeXml.length}">${mergeXml.join("")}</mergeCells>` : "",
    rowHeight: (row: number) => {
      const height = sheetPixels(formatting?.rowHeights?.[String(row)], 16, 600);
      return height ? ` ht="${height * 3 / 4}" customHeight="1"` : "";
    },
  };
}

export function createXlsxStyles(escapeXml: (value: string) => string) {
  const fonts = ['<font><sz val="11"/><name val="Calibri"/></font>', '<font><b/><sz val="11"/><name val="Calibri"/></font>'];
  const fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>'];
  const borders = ["<border><left/><right/><top/><bottom/><diagonal/></border>"];
  const formats: string[] = [];
  const styles = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'];
  const indexes = new Map<string, number>();

  function styleId(style: SheetCellStyle | undefined, heading: boolean): number {
    if (!style || typeof style !== "object") return heading ? 1 : 0;
    const key = `${heading}:${JSON.stringify(style)}`;
    const existing = indexes.get(key);
    if (existing !== undefined) return existing;
    const color = argb(style.textColor);
    const family = typeof style.fontFamily === "string" && /^[A-Za-z0-9][A-Za-z0-9 -]{0,63}$/.test(style.fontFamily)
      ? style.fontFamily : "Calibri";
    const size = sheetPixels(style.fontSize, 8, 96);
    const fontId = fonts.push(
      `<font>${(style.bold ?? heading) ? "<b/>" : ""}${style.italic === true ? "<i/>" : ""}${style.underline === true ? "<u/>" : ""}${style.strikethrough === true ? "<strike/>" : ""}<sz val="${size ? size * 3 / 4 : 11}"/>${color ? `<color rgb="${color}"/>` : ""}<name val="${family}"/></font>`,
    ) - 1;
    const fill = argb(style.backgroundColor);
    const fillId = fill
      ? fills.push(`<fill><patternFill patternType="solid"><fgColor rgb="${fill}"/><bgColor indexed="64"/></patternFill></fill>`) - 1
      : 0;
    const edges = SIDES.map((side) => {
      const edge = style.borders?.[side];
      const rgb = argb(edge?.color);
      return edge && rgb && BORDER_STYLES.has(edge.style)
        ? `<${side} style="${edge.style}"><color rgb="${rgb}"/></${side}>`
        : `<${side}/>`;
    }).join("");
    const borderId = style.borders ? borders.push(`<border>${edges}<diagonal/></border>`) - 1 : 0;
    const code = formatCode(style.numberFormat);
    const numFmtId = code ? formats.push(code) - 1 + 164 : 0;
    const horizontal = ["left", "center", "right"].includes(style.horizontalAlign ?? "")
      ? ` horizontal="${style.horizontalAlign}"` : "";
    const vertical = style.verticalAlign === "middle" ? ' vertical="center"'
      : style.verticalAlign === "top" || style.verticalAlign === "bottom" ? ` vertical="${style.verticalAlign}"` : "";
    const alignment = horizontal + vertical + (style.wrap === true ? ' wrapText="1"' : "");
    const index = styles.push(
      `<xf numFmtId="${numFmtId}" fontId="${fontId}" fillId="${fillId}" borderId="${borderId}" xfId="0" applyFont="1"${fillId ? ' applyFill="1"' : ""}${borderId ? ' applyBorder="1"' : ""}${numFmtId ? ' applyNumberFormat="1"' : ""}${alignment ? ` applyAlignment="1"><alignment${alignment}/></xf>` : "/>"}`,
    ) - 1;
    indexes.set(key, index);
    return index;
  }

  function xml(): string {
    const custom = formats.map((code, index) => `<numFmt numFmtId="${index + 164}" formatCode="${escapeXml(code)}"/>`).join("");
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
      + (custom ? `<numFmts count="${formats.length}">${custom}</numFmts>` : "")
      + `<fonts count="${fonts.length}">${fonts.join("")}</fonts>`
      + `<fills count="${fills.length}">${fills.join("")}</fills>`
      + `<borders count="${borders.length}">${borders.join("")}</borders>`
      + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
      + `<cellXfs count="${styles.length}">${styles.join("")}</cellXfs>`
      + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
  }
  return { styleId, xml };
}
