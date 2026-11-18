/**
 * frontend/packages/ui/src/components/embeds/slides/slidesTemplates.ts
 *
 * Built-in slide templates. A template supplies fonts, colour tokens and named
 * layouts whose slots give default positions to elements that carry no x/y/w/h.
 * Colour and font values live only here; slide components read them through
 * `templateStyleVars` / `resolveColor` and never hard-code a brand colour.
 * `builtin:plain` carries the app design tokens; every other template (built-in or
 * `library:`) is the deck's own `<theme>` laid over Plain per token
 * (`resolveTemplate`), so a deck renders the same wherever it travels.
 */

import type { ElementBox, Slide, SlideElement, TextElement, TextRole } from './slidesMarkup';
import type { DeckTheme, ThemeColorToken } from './slidesMarkup';
import { CANVAS_WIDTH, DEFAULT_TEMPLATE, THEME_COLOR_TOKENS } from './slidesMarkup';

export interface TextSlot {
  box: (height: number) => Required<ElementBox>;
  size: number;
  weight: string;
  align: 'left' | 'center' | 'right';
  italic?: boolean;
  colorToken: string;
}

export interface SlideTemplate {
  id: string;
  fonts: { heading: string; body: string };
  /** Colour token -> CSS colour. Values reference the app design tokens. */
  colors: Record<string, string>;
  /** layout -> role -> ordered slots (the nth element with that role takes the nth slot). */
  layouts: Record<string, Partial<Record<TextRole, TextSlot[]>>>;
  defaultLayout: string;
  /** Box for elements that have no position and no matching slot. */
  contentBox: (height: number) => Required<ElementBox>;
}

const MARGIN = 120;
const fill = (x: number, y: number, w: number, h: number): Required<ElementBox> => ({ x, y, w, h });

const titleTop: TextSlot = {
  box: () => fill(MARGIN, 80, CANVAS_WIDTH - 2 * MARGIN, 150),
  size: 68, weight: 'bold', align: 'left', colorToken: 'foreground'
};
const bodyMain: TextSlot = {
  box: (height) => fill(MARGIN, 280, CANVAS_WIDTH - 2 * MARGIN, height - 400),
  size: 40, weight: 'normal', align: 'left', colorToken: 'foreground'
};
const columnSlot = (index: number): TextSlot => ({
  box: (height) => fill(MARGIN + index * 880, 280, 800, height - 400),
  size: 38, weight: 'normal', align: 'left', colorToken: 'foreground'
});
const centered = (top: number, h: number, size: number, bold: boolean, token: string): TextSlot => ({
  box: (height) => fill(MARGIN + 40, Math.round(height * top), CANVAS_WIDTH - 2 * MARGIN - 80, h),
  size, weight: bold ? 'bold' : 'normal', align: 'center', colorToken: token
});

const PLAIN_LAYOUTS: SlideTemplate['layouts'] = {
    title: {
      title: [centered(0.3, 220, 104, true, 'foreground')],
      subtitle: [centered(0.55, 120, 48, false, 'muted')],
      body: [bodyMain], caption: [centered(0.8, 80, 32, false, 'muted')]
    },
    'title-and-content': {
      title: [titleTop], subtitle: [{ ...bodyMain, size: 44, colorToken: 'muted' }],
      body: [bodyMain], caption: [{ ...bodyMain, box: (h) => fill(MARGIN, h - 110, 1680, 60), size: 28, colorToken: 'muted' }]
    },
    section: {
      title: [centered(0.38, 200, 92, true, 'accent')],
      subtitle: [centered(0.6, 120, 44, false, 'muted')],
      body: [bodyMain]
    },
    'two-column': {
      title: [titleTop], subtitle: [{ ...bodyMain, size: 44, colorToken: 'muted' }],
      body: [columnSlot(0), columnSlot(1)]
    },
    /** Text on the left; the picture is placed explicitly on the right half. */
    image: {
      title: [titleTop], subtitle: [{ ...bodyMain, size: 44, colorToken: 'muted', box: (h) => fill(MARGIN, 280, 800, h - 400) }],
      body: [{ ...bodyMain, size: 38, box: (h) => fill(MARGIN, 280, 800, h - 400) }],
      caption: [{ ...bodyMain, box: (h) => fill(MARGIN, h - 110, 800, 60), size: 28, colorToken: 'muted' }]
    },
    quote: {
      title: [titleTop],
      quote: [{ ...centered(0.28, 360, 64, false, 'foreground'), italic: true }],
      caption: [centered(0.7, 80, 34, false, 'muted')],
      body: [bodyMain]
    },
    closing: {
      title: [centered(0.34, 220, 96, true, 'accent')],
      subtitle: [centered(0.58, 120, 46, false, 'muted')],
      body: [centered(0.58, 200, 40, false, 'foreground')],
      caption: [centered(0.82, 80, 32, false, 'muted')]
    }
};
PLAIN_LAYOUTS.content = PLAIN_LAYOUTS['title-and-content'];

export const PLAIN_TEMPLATE: SlideTemplate = {
  id: 'builtin:plain',
  fonts: {
    heading: 'var(--font-primary)',
    body: 'var(--font-primary)'
  },
  colors: {
    background: 'var(--color-grey-0)',
    foreground: 'var(--color-font-primary)',
    accent: 'var(--color-primary-start)',
    'accent-2': 'var(--color-primary-end)',
    muted: 'var(--color-font-secondary)',
    surface: 'var(--color-grey-20)'
  },
  defaultLayout: 'title-and-content',
  contentBox: (height) => fill(MARGIN, 280, CANVAS_WIDTH - 2 * MARGIN, height - 400),
  layouts: PLAIN_LAYOUTS
};

const TEMPLATES: Record<string, SlideTemplate> = { [DEFAULT_TEMPLATE]: PLAIN_TEMPLATE };

export function getTemplate(id: string): SlideTemplate {
  return TEMPLATES[id] ?? PLAIN_TEMPLATE;
}

const FONT_STACK_FALLBACK = 'var(--font-primary)';

function fontStack(name: string): string {
  return /\s/.test(name) ? `'${name}', ${FONT_STACK_FALLBACK}` : `${name}, ${FONT_STACK_FALLBACK}`;
}

/**
 * Template a deck renders with: Plain's tokens with the deck theme's values laid
 * over them, per token (a theme without a value keeps Plain's value).
 */
export function resolveTemplate(id: string, theme?: DeckTheme | null): SlideTemplate {
  const base = getTemplate(id);
  if (!theme) return base;
  const colors = { ...base.colors };
  for (const token of THEME_COLOR_TOKENS) {
    const value = theme.colors[token];
    if (value) colors[token] = value;
  }
  return {
    ...base,
    colors,
    fonts: {
      heading: theme.heading ? fontStack(theme.heading) : base.fonts.heading,
      body: theme.body ? fontStack(theme.body) : base.fonts.body
    }
  };
}

/**
 * Theme from an untrusted object (the core's DeckView `theme`): accepts the nested
 * `{heading, body, colors}` shape or flat token keys; anything else is dropped.
 */
export function readThemeValue(raw: unknown): DeckTheme | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const source = raw as Record<string, unknown>;
  const nested = source.colors && typeof source.colors === 'object' ? (source.colors as Record<string, unknown>) : source;
  const hex = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
  const colors: Partial<Record<ThemeColorToken, string>> = {};
  for (const token of THEME_COLOR_TOKENS) {
    // The core's DeckView uses snake case (`accent_2`); the markup attribute is `accent-2`.
    const value = nested[token] ?? nested[token.replace(/-/g, '_')];
    if (typeof value === 'string' && hex.test(value)) colors[token] = value.toLowerCase();
  }
  const theme: DeckTheme = { colors };
  if (typeof source.heading === 'string' && source.heading) theme.heading = source.heading;
  if (typeof source.body === 'string' && source.body) theme.body = source.body;
  return theme.heading || theme.body || Object.keys(colors).length > 0 ? theme : undefined;
}

/** CSS colour for a template token, `#hex` value or nothing. */
export function resolveColor(template: SlideTemplate, value: string | undefined): string | undefined {
  if (!value) return undefined;
  return template.colors[value] ?? (value.startsWith('#') ? value : undefined);
}

export function resolveFont(template: SlideTemplate, value: string | undefined, fallback: 'heading' | 'body'): string {
  if (value === 'heading' || value === 'body') return template.fonts[value];
  return value ?? template.fonts[fallback];
}

/** CSS custom properties carrying the template onto the canvas element. */
export function templateStyleVars(template: SlideTemplate): string {
  const colors = Object.entries(template.colors).map(([token, css]) => `--slide-color-${token}:${css}`);
  return [...colors, `--slide-font-heading:${template.fonts.heading}`, `--slide-font-body:${template.fonts.body}`].join(';');
}

export interface PlacedElement {
  element: SlideElement;
  box: Required<ElementBox>;
  /** Slot typography for text elements that took a layout slot. */
  slot?: TextSlot;
}

/** Fill missing coordinates of every element from the slide's layout slots. */
export function placeElements(slide: Slide, template: SlideTemplate, height: number): PlacedElement[] {
  const layout = template.layouts[slide.layout ?? ''] ?? template.layouts[template.defaultLayout];
  const used: Partial<Record<TextRole, number>> = {};
  return slide.elements.map((element) => {
    const given = element.box;
    const complete = given.x !== undefined && given.y !== undefined && given.w !== undefined && given.h !== undefined;
    let fallback = template.contentBox(height);
    let slot: TextSlot | undefined;
    if (element.type === 'text') {
      const role: TextRole = (element as TextElement).role ?? 'body';
      const index = used[role] ?? 0;
      used[role] = index + 1;
      const slots = layout[role] ?? [];
      slot = slots[Math.min(index, slots.length - 1)] ?? layout.body?.[0];
      if (slot) fallback = slot.box(height);
    }
    return {
      element,
      slot,
      box: complete
        ? (given as Required<ElementBox>)
        : { x: given.x ?? fallback.x, y: given.y ?? fallback.y, w: given.w ?? fallback.w, h: given.h ?? fallback.h }
    };
  });
}
