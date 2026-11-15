/**
 * Unit tests for the theme-over-Plain template resolver and the layout slots.
 */
import { describe, expect, it } from 'vitest';
import { PLAIN_TEMPLATE, readThemeValue, resolveTemplate } from './slidesTemplates';

describe('resolveTemplate', () => {
  // contract-test: supporting surface=gui.web assertions=slides.templates.library
  it('lays the theme over Plain per token', () => {
    const template = resolveTemplate('library:abc', { heading: 'Georgia', colors: { accent: '#1f9d55' } });
    expect(template.colors.accent).toBe('#1f9d55');
    expect(template.colors.background).toBe(PLAIN_TEMPLATE.colors.background);
    expect(template.fonts.heading).toContain('Georgia');
    expect(template.fonts.body).toBe(PLAIN_TEMPLATE.fonts.body);
  });

  // contract-test: supporting surface=gui.web assertions=slides.templates.built-in-set
  it('has slot layouts for every template layout', () => {
    for (const layout of ['title', 'section', 'content', 'two-column', 'image', 'quote', 'closing']) {
      expect(PLAIN_TEMPLATE.layouts[layout], layout).toBeDefined();
    }
    expect(PLAIN_TEMPLATE.layouts.content).toBe(PLAIN_TEMPLATE.layouts['title-and-content']);
  });

  // contract-test: supporting surface=gui.web assertions=slides.templates.library
  it('reads an untrusted core theme in nested or flat form and drops bad values', () => {
    expect(readThemeValue({ heading: 'Arial', colors: { accent: '#ABCDEF', muted: 'blue' } })).toEqual({
      heading: 'Arial', colors: { accent: '#abcdef' }
    });
    expect(readThemeValue({ background: '#fff' })).toEqual({ colors: { background: '#fff' } });
    expect(readThemeValue(null)).toBeUndefined();
    expect(readThemeValue({ accent: 'x' })).toBeUndefined();
  });
});

describe('readThemeValue with the core DeckView shape', () => {
  // contract-test: supporting surface=gui.web assertions=slides.templates.library
  it('reads the flat snake case keys of the wire fixture theme', () => {
    expect(readThemeValue({
      heading: 'Georgia', body: null, background: '#0b1220', foreground: '#f8fafc',
      accent: '#4ade80', accent_2: '#facc15', muted: null, surface: '#111827'
    })).toEqual({
      heading: 'Georgia',
      colors: { background: '#0b1220', foreground: '#f8fafc', accent: '#4ade80', 'accent-2': '#facc15', surface: '#111827' }
    });
    expect(readThemeValue({ colors: { 'accent-2': '#fff' } })).toEqual({ colors: { 'accent-2': '#fff' } });
  });
});
