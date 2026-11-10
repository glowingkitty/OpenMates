/**
 * frontend/packages/ui/src/components/embeds/slides/slidesTemplates.ts
 *
 * Built-in slide templates. A template supplies fonts, colour tokens and named
 * layouts whose slots give default positions to elements that carry no x/y/w/h.
 * Colour and font values live only here; slide components read them through
 * `templateStyleVars` / `resolveColor` and never hard-code a brand colour.
 * Only `builtin:plain` exists for now; `library:` templates arrive with the
 * template-library phase and fall back to it.
 */

import type { ElementBox, Slide, SlideElement, TextElement, TextRole } from './slidesMarkup';
import { CANVAS_WIDTH, DEFAULT_TEMPLATE } from './slidesMarkup';

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
  layouts: {
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
    quote: {
      title: [titleTop],
      quote: [{ ...centered(0.28, 360, 64, false, 'foreground'), italic: true }],
      caption: [centered(0.7, 80, 34, false, 'muted')],
      body: [bodyMain]
    }
  }
};

const TEMPLATES: Record<string, SlideTemplate> = { [DEFAULT_TEMPLATE]: PLAIN_TEMPLATE };

export function getTemplate(id: string): SlideTemplate {
  return TEMPLATES[id] ?? PLAIN_TEMPLATE;
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
