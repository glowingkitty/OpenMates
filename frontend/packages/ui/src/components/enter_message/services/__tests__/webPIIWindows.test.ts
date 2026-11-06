import { describe, expect, it } from 'vitest';
import { buildWebPIIWindows, mergeWebPIIWindowEntities, WEB_PII_WINDOW_STRIDE, WEB_PII_WINDOW_UNITS } from '../webPIIWindows';
import type { WebPIIEntity } from '../webPIIMatches';

const entity = (label: string, text: string, original: string, confidence = 1): WebPIIEntity => {
  const start = text.indexOf(original);
  return { label, original, start, end: start + original.length, confidence };
};

describe('web PII model windows', () => {
  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('keeps short and empty texts as one window over the full text', () => {
    expect(buildWebPIIWindows('')).toEqual([{ start: 0, end: 0 }]);
    const short = 'Hallo Herr Neumann, mein Name ist Markus Behrens.';
    expect(buildWebPIIWindows(short)).toEqual([{ start: 0, end: short.length }]);
    const boundary = Array.from({ length: WEB_PII_WINDOW_UNITS }, (_, i) => `w${i}`).join(' ');
    expect(buildWebPIIWindows(boundary)).toEqual([{ start: 0, end: boundary.length }]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('covers long text with half-overlapping windows that end exactly at the text end', () => {
    const words = Array.from({ length: 40 }, (_, i) => `wort${i}`);
    const text = words.join(' ');
    const windows = buildWebPIIWindows(text);
    expect(windows).toHaveLength(4);
    expect(windows[0].start).toBe(0);
    expect(windows[windows.length - 1].end).toBe(text.length);
    windows.forEach((window, index) => {
      expect(text.slice(window.start, window.end).split(' ')).toHaveLength(Math.min(WEB_PII_WINDOW_UNITS, 40 - index * WEB_PII_WINDOW_STRIDE));
    });
    for (let i = 1; i < windows.length; i++) expect(windows[i].start).toBeLessThan(windows[i - 1].end);
    // Every word is fully contained in at least one window.
    for (const word of words) {
      const at = text.indexOf(word);
      expect(windows.some(w => w.start <= at && w.end >= at + word.length)).toBe(true);
    }
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('never splits a whitespace-separated phone number or email across every window', () => {
    const filler = Array.from({ length: 30 }, (_, i) => `wort${i}`);
    const text = [...filler.slice(0, 11), 'Rufen', 'Sie', '+49', '151', '23456789', 'an', ...filler.slice(11)].join(' ');
    const phone = '+49 151 23456789';
    const at = text.indexOf(phone);
    expect(buildWebPIIWindows(text).some(w => w.start <= at && w.end >= at + phone.length)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('cuts whitespace-free runs into bounded units without splitting surrogate pairs', () => {
    // The leading ASCII char puts every 64-unit boundary in the middle of a surrogate pair.
    const text = 'a' + '😀'.repeat(2000);
    const windows = buildWebPIIWindows(text);
    expect(windows.length).toBeGreaterThan(1);
    for (const window of windows) {
      const piece = text.slice(window.start, window.end);
      expect(piece).not.toMatch(/^[\udc00-\udfff]/);
      expect(piece).not.toMatch(/[\ud800-\udbff]$/);
    }
    expect(windows[0].start).toBe(0);
    expect(windows[windows.length - 1].end).toBe(text.length);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it('merges duplicate and edge-truncated window detections by keeping the longest span', () => {
    const text = 'Mail an m.behrens@example.org und Stefan Albrecht';
    const full = entity('EMAIL', text, 'm.behrens@example.org');
    const truncated = entity('EMAIL', text, 'behrens@example');
    const given = entity('GIVEN_NAME', text, 'Stefan');
    const surname = entity('SURNAME', text, 'Albrecht');
    const duplicateSurname = { ...surname, label: 'GIVEN_NAME' };
    expect(mergeWebPIIWindowEntities([truncated, full, given, surname, duplicateSurname, full])).toEqual([full, given, surname]);
    expect(mergeWebPIIWindowEntities([])).toEqual([]);
  });
});
