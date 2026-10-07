/* eslint-disable no-control-regex -- Terminal sanitization intentionally matches escape and control bytes. */
/** Terminal cell geometry. User text is sanitized before any trusted styling. */
import type {TuiPointerAction} from './tuiPointer.js';
const segments = new Intl.Segmenter(undefined, { granularity: "grapheme" });
export function stripAnsi(value: string): string { return value.replace(/\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))/g, ""); }
export function terminalText(value: string): string {
  return stripAnsi(value).replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, "").replace(/\t/g, "  ");
}
function graphemeWidth(value: string): number {
  if (/^[\p{Mark}\p{Cf}]+$/u.test(value)) return 0;
  const cp = value.codePointAt(0) ?? 0;
  if (/\p{Extended_Pictographic}|\p{Regional_Indicator}|\u20e3/u.test(value)) return 2;
  return cp >= 0x1100 && (cp <= 0x115f || cp === 0x2329 || cp === 0x232a ||
    (cp >= 0x2e80 && cp <= 0xa4cf && cp !== 0x303f) || (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xfe10 && cp <= 0xfe19) ||
    (cp >= 0xfe30 && cp <= 0xfe6f) || (cp >= 0xff01 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6) || (cp >= 0x20000 && cp <= 0x3fffd)) ? 2 : 1;
}
export function cells(value: string): number {
  return [...segments.segment(stripAnsi(value))].reduce((n, item) => n + graphemeWidth(item.segment), 0);
}
export function truncateCells(value: string, width: number, ellipsis = "…"): string {
  const clean = terminalText(value).replace(/\n/g, " ");
  if (cells(clean) <= width) return clean;
  const available = Math.max(0, width - cells(ellipsis));
  let result = "", used = 0;
  for (const { segment } of segments.segment(clean)) {
    const size = graphemeWidth(segment);
    if (used + size > available) break;
    result += segment; used += size;
  }
  return width > 0 ? result + (cells(ellipsis) <= width ? ellipsis : "") : "";
}
export function padCells(value: string, width: number): string {
  const trimmed = truncateCells(value, width);
  return trimmed + " ".repeat(Math.max(0, width - cells(trimmed)));
}
/** Crop a horizontal viewport without splitting wide graphemes or adding ellipses. */
export function sliceCells(value: string, start: number, width: number): string {
  start = Math.max(0, Math.floor(start)); width = Math.max(0, Math.floor(width));
  const end = start + width;
  let position = 0, result = "";
  for (const { segment } of segments.segment(terminalText(value).replace(/\n/g, " "))) {
    const size = graphemeWidth(segment), next = position + size;
    if (next > start && position < end) {
      result += position >= start && next <= end ? segment : " ".repeat(Math.min(end, next) - Math.max(start, position));
    }
    position = next;
    if (position >= end) break;
  }
  return result + " ".repeat(Math.max(0, width - cells(result)));
}
export function wrapCells(value: string, width: number): string[] {
  width = Math.max(1, width);
  const result: string[] = [];
  for (const line of terminalText(value).split("\n")) {
    let text = "", used = 0;
    for (const { segment } of segments.segment(line)) {
      const size = graphemeWidth(segment);
      if (size > width) { if (text) result.push(text); result.push("?"); text = ""; used = 0; continue; }
      if (used + size > width) { result.push(text); text = ""; used = 0; }
      text += segment; used += size;
    }
    result.push(text);
  }
  return result;
}
export function eraseGrapheme(value: string): string {
  const items = [...segments.segment(value)];
  return items.length ? value.slice(0, items[items.length - 1].index) : "";
}
export function moveGraphemeCursor(value: string, cursor: number, direction: -1 | 1): number {
  const boundaries = [...segments.segment(value)].map((item) => item.index);
  boundaries.push(value.length);
  return direction < 0 ? boundaries.filter((index) => index < cursor).at(-1) ?? 0
    : boundaries.find((index) => index > cursor) ?? value.length;
}

export type TuiColorMode = "none" | "ansi16" | "ansi256" | "truecolor";
export type TuiSpan = { text: string; background?: string; color?: string; bold?: boolean; action?:TuiPointerAction };
/** Trusted rendering metadata, kept separate from untrusted terminal text. */
export type TuiLine = string | {
  text: string;
  action?:TuiPointerAction;
  background?: string;
  spans?: TuiSpan[];
  color?: string;
  bold?: boolean;
  inset?: number;
};
export const lineText = (line: TuiLine): string => typeof line === "string" ? line : line.text;
const rgb = (hex: string): number[] => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
function colorSequence(color: number[], mode: TuiColorMode, background: boolean): string {
  if (mode === "none") return "";
  if (mode === "truecolor") return `\x1b[${background ? 48 : 38};2;${color.join(";")}m`;
  if (mode === "ansi256") {
    const level = (v: number) => Math.round(v / 255 * 5);
    return `\x1b[${background ? 48 : 38};5;${16 + 36 * level(color[0]) + 6 * level(color[1]) + level(color[2])}m`;
  }
  const [r, g, b] = color;
  const index = (r > 100 ? 1 : 0) + (g > 100 ? 2 : 0) + (b > 100 ? 4 : 0);
  return `\x1b[${(background ? 40 : 30) + index}m`;
}
export function foreground(value: string, color: string, mode: TuiColorMode, bold = false): string {
  return mode === "none" ? value : `${bold ? "\x1b[1m" : ""}${colorSequence(rgb(color), mode, false)}${value}\x1b[0m`;
}
export function backgroundLine(value: string, width: number, color: string, mode: TuiColorMode, bold = false, textColor?: string): string {
  const line = padCells(value, width);
  if (mode === "none") return line;
  const foreground = textColor ? colorSequence(rgb(textColor), mode, false)
    : mode === "ansi16" ? "\x1b[97m" : colorSequence([255,255,255], mode, false);
  return `${bold ? "\x1b[1m" : ""}${foreground}${colorSequence(rgb(color), mode, true)}${line}\x1b[0m`;
}
