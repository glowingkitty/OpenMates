/**
 * Overlapping word windows for the local PII model.
 *
 * The model is context-fragile: in a longer sentence it can return no entity at
 * all for names it detects reliably in a short one (for example every name in
 * "Hallo Herr X, mein Name ist Y, ich arbeite bei <company>"), always with
 * confidence 1.0, so no confidence threshold recovers them. Scanning short
 * overlapping windows and merging the results restores that recall. Measured on
 * a labelled German/English corpus: whole text 22/26 expected items, 16-word
 * windows 26/26 with no false positives.
 */
import type { WebPIIEntity } from './webPIIMatches';

export const WEB_PII_WINDOW_UNITS = 16;
export const WEB_PII_WINDOW_STRIDE = WEB_PII_WINDOW_UNITS / 2;
/** Whitespace-free runs (CJK text, keys, URLs) are cut into units of at most this many UTF-16 code units. */
const MAX_UNIT_CHARS = 64;

export interface WebPIIWindow { start: number; end: number }

const isLowSurrogate = (code: number) => code >= 0xdc00 && code <= 0xdfff;

function splitUnits(text: string): WebPIIWindow[] {
  const units: WebPIIWindow[] = [];
  for (const run of text.matchAll(/\S+/g)) {
    const runStart = run.index;
    const runEnd = runStart + run[0].length;
    let start = runStart;
    while (start < runEnd) {
      let end = Math.min(start + MAX_UNIT_CHARS, runEnd);
      // Never cut a surrogate pair in half.
      if (end < runEnd && isLowSurrogate(text.charCodeAt(end))) end++;
      units.push({ start, end });
      start = end;
    }
  }
  return units;
}

/** Windows cover the whole text; every unit lies in at least two windows (except at the edges). Short texts yield one window over the full text. */
export function buildWebPIIWindows(text: string): WebPIIWindow[] {
  const units = splitUnits(text);
  if (units.length <= WEB_PII_WINDOW_UNITS) return [{ start: 0, end: text.length }];
  const windows: WebPIIWindow[] = [];
  for (let first = 0; ; first += WEB_PII_WINDOW_STRIDE) {
    const last = Math.min(first + WEB_PII_WINDOW_UNITS, units.length) - 1;
    windows.push({ start: units[first].start, end: units[last].end });
    if (last === units.length - 1) return windows;
  }
}

/** Overlapping windows report the same entity several times, sometimes cut at a window edge: keep the longest and drop whatever it overlaps. */
export function mergeWebPIIWindowEntities(entities: WebPIIEntity[]): WebPIIEntity[] {
  const kept: WebPIIEntity[] = [];
  for (const entity of [...entities].sort((a, b) => (b.end - b.start) - (a.end - a.start))) {
    if (!kept.some(other => entity.start < other.end && entity.end > other.start)) kept.push(entity);
  }
  return kept.sort((a, b) => a.start - b.start || b.end - a.end);
}
