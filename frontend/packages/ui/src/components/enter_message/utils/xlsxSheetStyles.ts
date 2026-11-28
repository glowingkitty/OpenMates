/** Translate the supported subset of OOXML cell styles into sheet presentation fields. */
import type {
  SheetBorder, SheetBorderSide, SheetCellStyle, SheetNumberFormat,
} from "../../embeds/sheets/sheetFormattingTypes";

type ReadAttribute = (xml: string, name: string) => string | null;
type ReadColor = (attrs: string) => string | undefined;

export interface XlsxCellStyle {
  formatId: number;
  code?: string;
  style: SheetCellStyle;
  hasUnsupportedStyle: boolean;
}

const borders: ReadonlySet<string> = new Set(["thin", "medium", "thick", "dashed", "dotted", "double"]);
const sides: SheetBorderSide[] = ["top", "right", "bottom", "left"];
const dates = ["yyyy-mm-dd", "mm/dd/yyyy", "dd/mm/yyyy", "mmm d, yyyy"] as const;
const THEME_COLORS = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"];
const INDEXED_COLORS = ["000000", "FFFFFF", "FF0000", "00FF00", "0000FF", "FFFF00", "FF00FF", "00FFFF"];

function elements(xml: string, name: string): Array<{ attrs: string; body: string }> {
  return Array.from(xml.matchAll(new RegExp(
    `<(?:[\\w.-]+:)?${name}\\b([^>]*?)(?:\\/>|>([\\s\\S]*?)<\\/(?:[\\w.-]+:)?${name}>)`, "g",
  )), ([, attrs, body]) => ({ attrs, body: body ?? "" }));
}

function group(xml: string, parent: string, child: string) {
  return elements(elements(xml, parent)[0]?.body ?? "", child);
}

function themeColors(xml: string, read: ReadAttribute): Array<string | null> {
  const scheme = elements(xml, "clrScheme")[0]?.body ?? "";
  return THEME_COLORS.map((key) => {
    const entry = elements(scheme, key)[0]?.body ?? "";
    return read(elements(entry, "srgbClr")[0]?.attrs ?? "", "val")
      ?? read(elements(entry, "sysClr")[0]?.attrs ?? "", "lastClr");
  });
}

function tintColor(hex: string, tint: number): string {
  const rgb = (hex.match(/../g) ?? []).map((channel) => Number.parseInt(channel, 16) / 255);
  const low = Math.min(...rgb);
  const high = Math.max(...rgb);
  const chroma = high - low;
  const lightness = (high + low) / 2;
  const nextLightness = tint < 0 ? lightness * (1 + tint) : lightness + (1 - lightness) * tint;
  const saturation = chroma === 0 ? 0 : chroma / (1 - Math.abs(2 * lightness - 1));
  const nextChroma = (1 - Math.abs(2 * nextLightness - 1)) * saturation;
  return rgb.map((channel) => {
    const mix = chroma === 0 ? 0 : (channel - low) / chroma * nextChroma;
    return Math.round((mix + nextLightness - nextChroma / 2) * 255).toString(16).padStart(2, "0");
  }).join("");
}

function colorReader(xml: string, theme: string, read: ReadAttribute): ReadColor {
  const themed = themeColors(theme, read);
  const indexed = group(xml, "indexedColors", "rgbColor").map(({ attrs }) => read(attrs, "rgb"));
  return (attrs) => {
    const themeIndex = read(attrs, "theme");
    const colorIndex = read(attrs, "indexed");
    const index = colorIndex === null ? -1 : Number(colorIndex);
    const base = read(attrs, "rgb")
      ?? (themeIndex === null ? undefined : themed[Number(themeIndex)])
      ?? indexed[index]
      ?? (index >= 0 && index < 16 ? INDEXED_COLORS[index % 8] : undefined);
    if (!base || !/^(?:[A-F0-9]{2})?[A-F0-9]{6}$/i.test(base)) return undefined;
    const rgb = base.slice(-6);
    const tint = Number(read(attrs, "tint"));
    return `#${tint && Math.abs(tint) <= 1 ? tintColor(rgb, tint).toUpperCase() : rgb}`;
  };
}

function numberFormat(id: number, code?: string): SheetNumberFormat | undefined {
  if (id === 9 || id === 10) return { kind: "percent", decimals: id === 9 ? 0 : 2 };
  if (id === 14) return { kind: "date", pattern: "mm/dd/yyyy" };
  if (id === 15) return { kind: "date", pattern: "mmm d, yyyy" };
  if (id >= 5 && id <= 8) return { kind: "currency", currency: "USD", decimals: id <= 6 ? 0 : 2 };
  if (id >= 1 && id <= 4) return { kind: "number", decimals: id % 2 ? 0 : 2 };
  if (!code) return undefined;

  const positive = code.split(";")[0].replaceAll("\\", "").toLowerCase();
  const date = dates.find((pattern) => positive === pattern);
  if (date) return { kind: "date", pattern: date };
  const decimals = positive.match(/\.([0#]{1,10})(?![0#])/)?.[1].length ?? 0;
  if (/^[#,0]+(?:\.[0#]+)?%$/.test(positive)) return { kind: "percent", decimals };
  if (/^[#,0]+(?:\.[0#]+)?$/.test(positive)) return { kind: "number", decimals };

  const currency = positive.match(/\[\$([a-z]{3})(?:-[\da-f]+)?\]/)?.[1].toUpperCase();
  const symbol = positive.match(/[$€£¥]/)?.[0];
  const currencyBySymbol: Record<string, string> = { $: "USD", "€": "EUR", "£": "GBP", "¥": "JPY" };
  const currencyCode = currency ?? (symbol ? currencyBySymbol[symbol] : undefined);
  if (currencyCode && /0/.test(positive)) return { kind: "currency", currency: currencyCode, decimals };
}

function readFont(xml: string, read: ReadAttribute, color: ReadColor): SheetCellStyle {
  const style: SheetCellStyle = {};
  const enabled = (tag: string) => {
    const attrs = elements(xml, tag)[0]?.attrs;
    return attrs !== undefined && !["0", "false"].includes(read(attrs, "val") ?? "");
  };
  if (enabled("b")) style.bold = true;
  if (enabled("i")) style.italic = true;
  if (enabled("u")) style.underline = true;
  if (enabled("strike")) style.strikethrough = true;
  style.textColor = color(elements(xml, "color")[0]?.attrs ?? "");
  const family = read(elements(xml, "name")[0]?.attrs ?? "", "val");
  if (family && /^[A-Za-z0-9][A-Za-z0-9 -]{0,63}$/.test(family)) style.fontFamily = family;
  const size = Math.round(Number(read(elements(xml, "sz")[0]?.attrs ?? "", "val")) * 4 / 3);
  if (size >= 8 && size <= 96) style.fontSize = size;
  return style;
}

function readBorders(xml: string, read: ReadAttribute, color: ReadColor): SheetCellStyle["borders"] {
  const result: NonNullable<SheetCellStyle["borders"]> = {};
  for (const side of sides) {
    const edge = elements(xml, side)[0];
    if (!edge) continue;
    const style = read(edge.attrs, "style");
    if (style && borders.has(style)) {
      result[side] = {
        style: style as SheetBorder["style"],
        color: color(elements(edge.body, "color")[0]?.attrs ?? "") ?? "#000000",
      };
    }
  }
  return Object.keys(result).length ? result : undefined;
}

export function readXlsxStyles(xml: string, theme: string, read: ReadAttribute): XlsxCellStyle[] {
  const readColor = colorReader(xml, theme, read);
  const customCodes = new Map(group(xml, "numFmts", "numFmt").map(({ attrs }) => [
    Number(read(attrs, "numFmtId")), read(attrs, "formatCode") ?? "",
  ]));
  const fonts = group(xml, "fonts", "font");
  const fills = group(xml, "fills", "fill");
  const edges = group(xml, "borders", "border");
  return group(xml, "cellXfs", "xf").map(({ attrs, body }) => {
    const formatId = Number(read(attrs, "numFmtId") ?? 0);
    const code = customCodes.get(formatId);
    const fontId = Number(read(attrs, "fontId") ?? 0);
    const fillId = Number(read(attrs, "fillId") ?? 0);
    const borderId = Number(read(attrs, "borderId") ?? 0);
    const style = fontId ? readFont(fonts[fontId]?.body ?? "", read, readColor) : {};
    style.numberFormat = numberFormat(formatId, code);

    const fill = elements(fills[fillId]?.body ?? "", "patternFill")[0];
    if (fill && read(fill.attrs, "patternType") === "solid") {
      style.backgroundColor = readColor(elements(fill.body, "fgColor")[0]?.attrs ?? "");
    }
    if (borderId) style.borders = readBorders(edges[borderId]?.body ?? "", read, readColor);
    const alignment = elements(body, "alignment")[0]?.attrs ?? "";
    const horizontal = read(alignment, "horizontal");
    if (horizontal === "left" || horizontal === "center" || horizontal === "right") {
      style.horizontalAlign = horizontal;
    }
    const vertical = read(alignment, "vertical");
    if (vertical === "top" || vertical === "bottom") style.verticalAlign = vertical;
    if (vertical === "center") style.verticalAlign = "middle";
    if (read(alignment, "wrapText") === "1" || read(alignment, "wrapText") === "true") style.wrap = true;

    const hasUnsupportedStyle = (fillId >= 2 && !style.backgroundColor)
      || (formatId !== 0 && !style.numberFormat)
      || (fontId > 0 && !fonts[fontId])
      || (borderId > 0 && !style.borders)
      || Boolean(horizontal && !style.horizontalAlign && horizontal !== "general")
      || Boolean(vertical && !style.verticalAlign)
      || Boolean(read(alignment, "textRotation") && read(alignment, "textRotation") !== "0");
    return {
      formatId, code, hasUnsupportedStyle,
      style: Object.fromEntries(Object.entries(style).filter(([, value]) => value !== undefined)),
    };
  });
}
