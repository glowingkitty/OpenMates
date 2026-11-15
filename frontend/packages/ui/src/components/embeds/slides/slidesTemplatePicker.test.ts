/**
 * Unit tests for the template picker helpers (option order, Updated detection, core theme).
 */
import { describe, expect, it } from 'vitest';
import { buildTemplateOptions, isTemplateUpdated, toCoreTheme } from './slidesTemplatePicker';

const library = (embedId: string, accent: string) => ({
  embedId, title: `Club ${embedId}`, savedAt: 1,
  markup: `<deck title="Club" aspect="16:9" template="library:${embedId}" kind="template"><theme accent="${accent}" accent-2="#facc15"/><slide id="s1"><text id="e1" x="0" y="0" w="100" h="100">Hi</text></slide></deck>`
});

describe('template picker helpers', () => {
  // contract-test: supporting surface=gui.web assertions=slides.templates.apply-to-deck
  it('lists built-in designs first, then library templates', () => {
    const options = buildTemplateOptions([library('abc', '#4ade80'), { ...library('empty', '#fff'), markup: ' ' }]);
    const sources = options.map((o) => o.source);
    expect(sources.indexOf('library')).toBe(sources.lastIndexOf('builtin') + 1);
    expect(options.filter((o) => o.source === 'library').map((o) => o.id)).toEqual(['library:abc']);
    expect(options[0].id.startsWith('builtin:')).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=slides.templates.apply-to-deck
  it('marks a followed library template Updated only when its theme differs from the deck', () => {
    const option = buildTemplateOptions([library('abc', '#4ade80')]).find((o) => o.id === 'library:abc')!;
    const same = { colors: { accent: '#4ade80', 'accent-2': '#facc15' } as Record<string, string> };
    expect(isTemplateUpdated('library:abc', same, option)).toBe(false);
    expect(isTemplateUpdated('library:abc', { colors: { accent: '#111111' } }, option)).toBe(true);
    expect(isTemplateUpdated('builtin:plain', { colors: {} }, option)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=slides.templates.apply-to-deck
  it('converts a parsed theme to the flat core theme; no theme clears it', () => {
    expect(toCoreTheme(undefined)).toBeNull();
    expect(toCoreTheme({ heading: 'Georgia', colors: { 'accent-2': '#facc15' } })).toMatchObject({
      heading: 'Georgia', body: null, accent: null, accent_2: '#facc15'
    });
  });
});
