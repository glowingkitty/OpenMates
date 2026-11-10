/**
 * frontend/packages/ui/src/components/embeds/slides/slidesEditorView.ts
 *
 * View helpers of the slides editor. The deck itself lives in the Rust core
 * (deckDocumentClient.ts); this file only turns the core's DeckView into what the
 * existing renderer (SlideCanvas) draws and computes the in-progress rectangle of a
 * drag. Nothing here changes a deck: every change is a typed operation sent to the
 * core, which validates and clamps it (live-collab.core.one-shared-model).
 */

import type { DeckElementModel, DeckSlideModel } from '../../../services/rustCore/deckDocument/deckDocumentTypes';
import { parseInlineMarkup, type ElementBox, type Slide, type SlideElement, type SlideTransition } from './slidesMarkup';
import { resolveColor, resolveFont, type PlacedElement, type SlideTemplate } from './slidesTemplates';

/** A rectangle in canvas units (the canvas is 1920 wide). */
export interface CanvasBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';
export const RESIZE_HANDLES: readonly ResizeHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

/** Smallest box a resize drag shows (canvas units). */
export const MIN_BOX = 20;

/** View-only overrides while the user drags or types. */
export interface RenderOverrides {
  /** In-progress rectangle of the element being dragged. */
  drag?: { elementId: string; box: CanvasBox } | null;
  /** Element whose text is being typed in an overlay; drawn empty underneath. */
  typingId?: string | null;
}

function box(element: DeckElementModel): ElementBox {
  const out: ElementBox = {};
  if (element.x !== null) out.x = element.x;
  if (element.y !== null) out.y = element.y;
  if (element.w !== null) out.w = element.w;
  if (element.h !== null) out.h = element.h;
  return out;
}

function stringContent(element: DeckElementModel): string {
  const content = element.content;
  return content.type === 'empty' || content.type === 'items' ? '' : content.value;
}

function numberAttribute(value: string | undefined): number | undefined {
  if (value === undefined) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function videoSource(src: string): { provider: 'embed' | 'youtube' | 'vimeo'; ref: string } | null {
  for (const provider of ['embed', 'youtube', 'vimeo'] as const) {
    if (src.startsWith(`${provider}:`)) return { provider, ref: src.slice(provider.length + 1) };
  }
  return null;
}

/** Renderer element for one core element (attribute strings to typed fields). */
function renderElement(element: DeckElementModel, typing: boolean): SlideElement | null {
  const a = element.attributes;
  const base = {
    id: element.id,
    box: box(element),
    animate: a.animate as SlideElement['animate'],
    step: numberAttribute(a.step) ?? 0
  };
  switch (element.kind) {
    case 'text':
      return {
        ...base,
        type: 'text',
        role: a.role as Extract<SlideElement, { type: 'text' }>['role'],
        font: a.font,
        size: numberAttribute(a.size),
        color: a.color,
        align: a.align as Extract<SlideElement, { type: 'text' }>['align'],
        weight: a.weight,
        content: typing ? [] : parseInlineMarkup(stringContent(element))
      };
    case 'image': {
      const src = a.src ?? '';
      if (!src.startsWith('embed:')) return null;
      return { ...base, type: 'image', ref: src.slice('embed:'.length), alt: a.alt ?? '', fit: a.fit === 'contain' ? 'contain' : 'cover' };
    }
    case 'video': {
      const source = videoSource(a.src ?? '');
      return source ? { ...base, type: 'video', ...source, alt: a.alt ?? '' } : null;
    }
    case 'shape':
      return {
        ...base,
        type: 'shape',
        kind: (a.kind ?? 'rect') as Extract<SlideElement, { type: 'shape' }>['kind'],
        fill: a.fill,
        stroke: a.stroke
      };
    case 'notepad':
      return { ...base, type: 'notepad', title: a.title ?? '', text: stringContent(element), hidden: a.hidden === 'true' };
    case 'todo':
      return {
        ...base,
        type: 'todo',
        title: a.title ?? '',
        hidden: a.hidden === 'true',
        items: element.content.type === 'items' ? element.content.value.map((item) => ({ done: item.done, label: item.text })) : []
      };
    case 'link': {
      const href = a.href ?? '';
      return { ...base, type: 'link', href, label: stringContent(element) || href };
    }
    case 'block':
      return { ...base, type: 'block', title: a.title ?? '', body: stringContent(element) };
    default:
      return null;
  }
}

/** The renderer's slide for a core slide, with the editor's view-only overrides. */
export function toRenderSlide(slide: DeckSlideModel, overrides: RenderOverrides = {}): Slide {
  const elements: SlideElement[] = [];
  for (const element of slide.elements) {
    const rendered = renderElement(element, overrides.typingId === element.id);
    if (!rendered) continue;
    if (overrides.drag && overrides.drag.elementId === element.id) rendered.box = { ...overrides.drag.box };
    elements.push(rendered);
  }
  return {
    id: slide.id,
    layout: slide.layout ?? undefined,
    transition: (slide.transition ?? 'none') as SlideTransition,
    elements,
    notes: slide.notes
  };
}

/** Elements the editor can select: everything drawn (hidden notepads/to-dos are not drawn). */
export function selectable(placed: PlacedElement[]): PlacedElement[] {
  return placed.filter(
    (entry) => !((entry.element.type === 'notepad' || entry.element.type === 'todo') && entry.element.hidden)
  );
}

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/**
 * In-progress rectangle of a move or resize drag. `dx`/`dy` are canvas units. Kept
 * inside the canvas so the preview matches what the core will store; the core clamps
 * the committed `set_geometry` again and its answer is what stays on screen.
 */
export function dragBox(
  start: CanvasBox,
  handle: ResizeHandle | 'move',
  dx: number,
  dy: number,
  canvas: { width: number; height: number }
): CanvasBox {
  if (handle === 'move') {
    return {
      x: Math.round(clamp(start.x + dx, 0, Math.max(canvas.width - start.w, 0))),
      y: Math.round(clamp(start.y + dy, 0, Math.max(canvas.height - start.h, 0))),
      w: start.w,
      h: start.h
    };
  }
  let left = start.x;
  let top = start.y;
  let right = start.x + start.w;
  let bottom = start.y + start.h;
  if (handle.includes('w')) left = clamp(start.x + dx, 0, right - MIN_BOX);
  if (handle.includes('e')) right = clamp(start.x + start.w + dx, left + MIN_BOX, canvas.width);
  if (handle.includes('n')) top = clamp(start.y + dy, 0, bottom - MIN_BOX);
  if (handle.includes('s')) bottom = clamp(start.y + start.h + dy, top + MIN_BOX, canvas.height);
  return { x: Math.round(left), y: Math.round(top), w: Math.round(right - left), h: Math.round(bottom - top) };
}

export function sameBox(a: CanvasBox, b: CanvasBox): boolean {
  return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
}

/** Effective typography of a placed text element (own attributes, else its layout slot). */
export interface EffectiveTextStyle {
  size: number;
  weight: string;
  align: string;
  color: string | undefined;
  italic: boolean;
  font: string;
}

export function effectiveTextStyle(entry: PlacedElement, template: SlideTemplate): EffectiveTextStyle | null {
  const element = entry.element;
  if (element.type !== 'text') return null;
  const slot = entry.slot;
  return {
    size: element.size ?? slot?.size ?? 40,
    weight: element.weight ?? slot?.weight ?? 'normal',
    align: element.align ?? slot?.align ?? 'left',
    color: resolveColor(template, element.color ?? slot?.colorToken),
    italic: !!slot?.italic,
    font: resolveFont(template, element.font, element.role === 'title' ? 'heading' : 'body')
  };
}

/** True when a keyboard event belongs to a field with its own editing (and undo). */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || typeof (target as HTMLElement).tagName !== 'string') return false;
  const element = target as HTMLElement;
  return element.isContentEditable || /^(input|textarea|select)$/i.test(element.tagName);
}
