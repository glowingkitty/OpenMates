/**
 * frontend/packages/ui/src/components/embeds/slides/slidesEmbedText.ts
 *
 * Text-only renderer for the slides-deck embed type (copy, markdown export).
 * Title, then per slide: number, text, notes and "[image]" / "[video]" /
 * "[interactive block]" markers. Parsing needs DOMParser; in contexts without
 * one (workers) only the title and slide count are returned.
 */

import { str } from '../../../data/embedTextRenderers';
import { inlineToPlainText, parseSlidesMarkup, type SlideElement } from './slidesMarkup';

function elementText(element: SlideElement): string | null {
  switch (element.type) {
    case 'text':
      return inlineToPlainText(element.content) || null;
    case 'image':
      return '[image]';
    case 'video':
      return '[video]';
    case 'block':
      return '[interactive block]';
    case 'link':
      return `${element.label} (${element.href})`;
    case 'todo':
      if (element.hidden) return null;
      return [element.title, ...element.items.map((item) => `- [${item.done ? 'x' : ' '}] ${item.label}`)]
        .filter(Boolean)
        .join('\n');
    case 'notepad':
      if (element.hidden) return null;
      return [element.title, element.text].filter(Boolean).join('\n') || null;
    default:
      return null;
  }
}

/** slides-deck: slide deck embed */
export function renderSlidesDeck(c: Record<string, unknown>): string {
  const title = str(c.title) ?? '';
  const count = typeof c.slide_count === 'number' ? c.slide_count : 0;
  const header = `**Presentation**${title ? ` — ${title}` : ''}`;
  const markup = str(c.slides_markup);
  if (!markup || typeof DOMParser === 'undefined') {
    return count ? `${header}\n${count} slides` : header;
  }
  const parsed = parseSlidesMarkup(markup);
  if (!parsed.ok) return count ? `${header}\n${count} slides` : header;
  const lines = [header];
  parsed.deck.slides.forEach((slide, index) => {
    lines.push('', `Slide ${index + 1}`);
    for (const element of slide.elements) {
      const rendered = elementText(element);
      if (rendered) lines.push(rendered);
    }
    if (slide.notes) lines.push(`Notes: ${slide.notes}`);
  });
  return lines.join('\n');
}
