/**
 * frontend/packages/ui/src/components/embeds/slides/slidesTemplatePicker.ts
 *
 * Pure helpers of the deck's template picker: the option list (built-in designs
 * first, then the saved library), the "Updated" detection (a library template
 * whose saved theme differs from the theme the deck carries) and the conversion
 * of a parsed theme to the Rust core's `set_theme` payload.
 */
import { BUILTIN_SLIDES_TEMPLATES } from './slidesBuiltinTemplates.generated';
import { THEME_COLOR_TOKENS, parseSlidesMarkup, type DeckTheme } from './slidesMarkup';
import type { DeckTheme as CoreTheme } from '../../../services/rustCore/deckDocument/deckDocumentTypes';
import type { SavedTemplate } from '../../../services/savedEmbedService';

export interface TemplateOption {
  /** `builtin:<id>` or `library:<embedId>`. */
  id: string;
  name: string;
  source: 'builtin' | 'library';
  markup: string;
}

/** Built-in designs first (generated order), then library templates (newest first, as listed). */
export function buildTemplateOptions(library: readonly SavedTemplate[]): TemplateOption[] {
  const builtin: TemplateOption[] = BUILTIN_SLIDES_TEMPLATES.map((t) => ({ id: t.id, name: t.name, source: 'builtin', markup: t.markup }));
  const own: TemplateOption[] = library
    .filter((t) => t.markup.trim() !== '')
    .map((t) => ({ id: `library:${t.embedId}`, name: t.title || t.embedId, source: 'library', markup: t.markup }));
  return [...builtin, ...own];
}

function themeKey(theme: DeckTheme | undefined): string {
  if (!theme) return '';
  const colors = THEME_COLOR_TOKENS.map((token) => `${token}=${theme.colors[token] ?? ''}`).join(';');
  return `${theme.heading ?? ''}|${theme.body ?? ''}|${colors}`.toLowerCase();
}

/** True when the theme of two decks resolves to the same fonts and colours. */
export function sameTheme(a: DeckTheme | undefined, b: DeckTheme | undefined): boolean {
  return themeKey(a) === themeKey(b);
}

/**
 * The deck follows `library:<id>` and that saved template's theme now differs
 * from the deck's own theme: the picker offers it with an "Updated" badge.
 */
export function isTemplateUpdated(deckTemplate: string, deckTheme: DeckTheme | undefined, option: TemplateOption): boolean {
  if (option.source !== 'library' || deckTemplate !== option.id) return false;
  const parsed = parseSlidesMarkup(option.markup);
  return parsed.ok && !sameTheme(deckTheme, parsed.deck.theme);
}

/** Core `set_theme` payload of a parsed theme; `undefined` (plain built-in) clears the theme. */
export function toCoreTheme(theme: DeckTheme | undefined): CoreTheme | null {
  if (!theme) return null;
  const color = (token: (typeof THEME_COLOR_TOKENS)[number]) => theme.colors[token] ?? null;
  return {
    heading: theme.heading ?? null, body: theme.body ?? null,
    background: color('background'), foreground: color('foreground'), accent: color('accent'),
    accent_2: color('accent-2'), muted: color('muted'), surface: color('surface')
  };
}
