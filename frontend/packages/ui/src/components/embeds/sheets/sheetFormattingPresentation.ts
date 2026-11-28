import type { SheetBorderSide, SheetCellStyle, SheetFormatting } from "./sheetFormattingTypes";

const COLOR = /^#[0-9a-f]{6}$/i;
const FONT = /^[A-Za-z0-9][A-Za-z0-9 -]{0,63}$/;
const BORDER_WIDTH = { thin: 1, medium: 2, thick: 3, dashed: 1, dotted: 1, double: 3 } as const;
const SIDES: SheetBorderSide[] = ["top", "right", "bottom", "left"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function sheetPixels(value: unknown, minimum: number, maximum: number): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum && value <= maximum
    ? value : undefined;
}

/** Measure actual row heights because wrapped text can grow past the requested minimum. */
export function watchSheetRows(table: HTMLTableElement, receive: (offsets: number[]) => void) {
  const update = () => {
    let offset = 0;
    receive(Array.from(table.rows, (row) => {
      const top = offset;
      offset += row.getBoundingClientRect().height;
      return top;
    }));
  };
  const observer = new ResizeObserver(update);
  observer.observe(table);
  update();
  return { update, destroy: () => observer.disconnect() };
}

/** Convert only allowlisted style values to CSS. Stored sheets may come from other clients. */
export function sheetCellCss(style: SheetCellStyle | undefined): string | undefined {
  if (!style || typeof style !== "object") return undefined;
  const rules: string[] = [];
  if (typeof style.backgroundColor === "string" && COLOR.test(style.backgroundColor)) {
    rules.push(`background-color:${style.backgroundColor}`);
  }
  if (typeof style.textColor === "string" && COLOR.test(style.textColor)) rules.push(`color:${style.textColor}`);
  if (typeof style.fontFamily === "string" && FONT.test(style.fontFamily)) {
    rules.push(`font-family:"${style.fontFamily}",sans-serif`);
  }
  const fontSize = sheetPixels(style.fontSize, 8, 96);
  if (fontSize) rules.push(`font-size:${fontSize}px`);
  if (typeof style.bold === "boolean") rules.push(`font-weight:${style.bold ? "bold" : "normal"}`);
  if (typeof style.italic === "boolean") rules.push(`font-style:${style.italic ? "italic" : "normal"}`);
  if (typeof style.underline === "boolean" || typeof style.strikethrough === "boolean") {
    const marks = [style.underline === true ? "underline" : "", style.strikethrough === true ? "line-through" : ""];
    rules.push(`text-decoration:${marks.filter(Boolean).join(" ") || "none"}`);
  }
  if (style.horizontalAlign && ["left", "center", "right"].includes(style.horizontalAlign)) {
    rules.push(`text-align:${style.horizontalAlign}`);
  }
  if (style.verticalAlign && ["top", "middle", "bottom"].includes(style.verticalAlign)) {
    rules.push(`vertical-align:${style.verticalAlign}`);
  }
  if (typeof style.wrap === "boolean") rules.push(`white-space:${style.wrap ? "normal" : "nowrap"}`);

  for (const side of SIDES) {
    const edge = style.borders?.[side];
    if (!edge || !Object.hasOwn(BORDER_WIDTH, edge.style) || typeof edge.color !== "string" || !COLOR.test(edge.color)) continue;
    const line = ["dashed", "dotted", "double"].includes(edge.style) ? edge.style : "solid";
    rules.push(`border-${side}:${BORDER_WIDTH[edge.style]}px ${line} ${edge.color}`);
  }
  return rules.length ? rules.join(";") : undefined;
}

function dateText(value: string, pattern: string): string {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!parts) return value;
  const [, year, month, day] = parts;
  const label = MONTHS[Number(month) - 1];
  if (!label) return value;
  if (pattern === "mm/dd/yyyy") return `${month}/${day}/${year}`;
  if (pattern === "dd/mm/yyyy") return `${day}/${month}/${year}`;
  if (pattern === "mmm d, yyyy") return `${label} ${Number(day)}, ${year}`;
  return value;
}

/** Format visible cell content without mutating the stored value or formula. */
export function displaySheetValue(value: string, style: SheetCellStyle | undefined): string {
  const format = style?.numberFormat;
  if (!format || !value.trim()) return value;
  if (format.kind === "date") return dateText(value, format.pattern);
  const isPercentText = format.kind === "percent" && value.endsWith("%");
  const raw = isPercentText ? value.slice(0, -1) : value;
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(raw.trim())) return value;
  const number = Number(raw) / (isPercentText ? 100 : 1);
  if (!Number.isFinite(number)) return value;
  const decimals = sheetPixels(format.decimals, 0, 10);
  const fraction = decimals === undefined ? {} : { minimumFractionDigits: decimals, maximumFractionDigits: decimals };
  if (format.kind === "currency" && typeof format.currency === "string" && /^[A-Z]{3}$/.test(format.currency)) {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: format.currency, ...fraction }).format(number);
  }
  return new Intl.NumberFormat(undefined, { style: format.kind === "percent" ? "percent" : "decimal", ...fraction }).format(number);
}

interface MergeCell { rowSpan: number; colSpan: number }

function coordinate(value: unknown): [number, number] | undefined {
  if (typeof value !== "string") return undefined;
  const match = /^([A-Z]{1,3})([1-9]\d{0,3})$/.exec(value);
  if (!match) return undefined;
  let column = 0;
  for (const letter of match[1]) column = column * 26 + letter.charCodeAt(0) - 64;
  return [Number(match[2]) - 1, column - 1];
}

/** Draw merges inside the visible grid, clipping any range that extends beyond its preview. */
export function visibleSheetMerges(formatting: SheetFormatting | undefined, rows: number, columns: number) {
  const cells = new Map<string, MergeCell | null>();
  if (!Array.isArray(formatting?.merges)) return cells;
  for (const merge of formatting.merges.slice(0, 256)) {
    const start = coordinate(merge?.start);
    const end = coordinate(merge?.end);
    if (!start || !end) continue;
    const [top, left] = start;
    const bottom = Math.min(rows - 1, end[0]);
    const right = Math.min(columns - 1, end[1]);
    if (top > bottom || left > right || (top === bottom && left === right)) continue;
    const keys: string[] = [];
    for (let row = top; row <= bottom; row++) {
      for (let column = left; column <= right; column++) keys.push(`${row}:${column}`);
    }
    if (keys.some((key) => cells.has(key))) continue;
    cells.set(keys[0], { rowSpan: bottom - top + 1, colSpan: right - left + 1 });
    for (const key of keys.slice(1)) cells.set(key, null);
  }
  return cells;
}
