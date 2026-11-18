/**
 * Pure HTML cleanup for the manual document editor.
 *
 * Browsers' contenteditable output varies (<b>/<i>, <div> paragraphs, <font>,
 * inline styles). `cleanEditedHtml` normalises that into the document tags the
 * viewer renders and runs the shared sanitizer, so saved HTML only contains
 * allowed tags. It is used for both loading and saving.
 */
import { countDocWords, sanitizeDocumentHtml } from './docsEmbedContent';

const RENAMES: Record<string, string> = { b: 'strong', i: 'em', div: 'p' };

/** Span kinds that carry meaning (embed and wiki links) and must survive unwrapping. */
function isMeaningfulSpan(el: Element): boolean {
  return Array.from(el.attributes).some((attr) => attr.name.startsWith('data-'));
}

function replaceTag(el: Element, tag: string): void {
  const next = el.ownerDocument.createElement(tag);
  while (el.firstChild) next.appendChild(el.firstChild);
  el.replaceWith(next);
}

function unwrap(el: Element): void {
  while (el.firstChild) el.parentNode?.insertBefore(el.firstChild, el);
  el.remove();
}

/** Normalise editor output and sanitize it; returns the HTML to store. */
export function cleanEditedHtml(html: string): string {
  const template = document.createElement('template');
  template.innerHTML = html;
  const root = template.content;
  // Deepest elements first so replaced/unwrapped parents keep their children.
  const elements = Array.from(root.querySelectorAll('*')).reverse();
  for (const el of elements) {
    el.removeAttribute('style');
    const tag = el.tagName.toLowerCase();
    if (tag === 'font' || (tag === 'span' && !isMeaningfulSpan(el))) unwrap(el);
    else if (RENAMES[tag]) replaceTag(el, RENAMES[tag]);
  }
  // Empty blocks left behind by Enter presses at the end of the document.
  for (const el of Array.from(root.querySelectorAll('p'))) {
    // A list or heading wrapped in a paragraph (Chromium's list command, renamed divs) is invalid HTML.
    if (el.querySelector('ul,ol,h1,h2,h3,h4,h5,h6,p,blockquote,table')) unwrap(el);
    else if (!el.textContent?.trim() && !el.querySelector('img,br')) el.remove();
    else if (!el.textContent?.trim() && el.children.length === 1 && el.firstElementChild?.tagName === 'BR') el.remove();
  }
  return sanitizeDocumentHtml(template.innerHTML).trim();
}

/** Fields describing stored artifacts of the old text (DOCX, PDF, page images). */
const STALE_ARTIFACT_FIELDS = [
  'screenshot_s3_keys', 'preview_page_urls', 'docx_s3_key', 'pdf_s3_key', 'aes_key', 'docx_model', 'page_count',
] as const;

/**
 * New head content object of an edited document: the existing content with the
 * edited `html`, its word count and the new version; the artifacts of the old
 * text are dropped so viewers and downloads use the edited HTML.
 */
export function buildEditedContent(
  base: Record<string, unknown>,
  html: string,
  version: number
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...base };
  for (const field of STALE_ARTIFACT_FIELDS) delete next[field];
  return { ...next, html, word_count: countDocWords(html), version_number: version };
}
