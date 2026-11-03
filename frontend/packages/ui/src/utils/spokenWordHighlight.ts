// Dims the not-yet-spoken words of a message with the CSS Custom Highlight API.
// The rendered DOM is never mutated, so editors, selection and streaming are
// unaffected. Browsers without `CSS.highlights` show the reply undimmed.
//
// Words are whitespace-separated tokens of readable text, matching how the
// realtime speech turn counts words in its spoken source. Code blocks and
// non-editable embeds are not spoken and are skipped.

export const UNSPOKEN_HIGHLIGHT_NAME = 'assistant-speech-unspoken';

const SKIPPED_SELECTOR = 'pre, code, [contenteditable="false"]';
const BLOCK_SELECTOR = 'p, li, blockquote, h1, h2, h3, h4, h5, h6, td, th';
const rangesByRoot = new Map<Element, Range>();

type HighlightRegistry = { set(name: string, value: unknown): void; delete(name: string): void };
function registry(): { highlights: HighlightRegistry; Highlight: new (...ranges: Range[]) => unknown } | null {
  const css = (globalThis as { CSS?: { highlights?: HighlightRegistry } }).CSS;
  const Highlight = (globalThis as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight;
  return css?.highlights && Highlight ? { highlights: css.highlights, Highlight } : null;
}

function sync(): void {
  const api = registry();
  if (!api) return;
  if (rangesByRoot.size === 0) api.highlights.delete(UNSPOKEN_HIGHLIGHT_NAME);
  else api.highlights.set(UNSPOKEN_HIGHLIGHT_NAME, new api.Highlight(...rangesByRoot.values()));
}

/** Range from the start of word `words` (0-based) to the end of `root`'s text, or null. */
export function unspokenRange(root: Element, words: number): Range | null {
  const document = root.ownerDocument;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => node.parentElement?.closest(SKIPPED_SELECTOR) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  let seen = 0;
  let inWord = false;
  let block: Element | null = null;
  let last: Text | null = null;
  let start: { node: Text; offset: number } | null = null;
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    last = node;
    if (start) continue;
    const nodeBlock = node.parentElement?.closest(BLOCK_SELECTOR) ?? null;
    if (nodeBlock !== block) { inWord = false; block = nodeBlock; }
    const text = node.data;
    for (let index = 0; index < text.length; index++) {
      const space = /\s/.test(text[index]);
      if (!space && !inWord) {
        if (seen === words) { start = { node, offset: index }; break; }
        seen++;
      }
      inWord = !space;
    }
  }
  if (!start || !last) return null;
  const range = document.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(last, last.data.length);
  return range;
}

/** Dim unspoken words under `root`; `words === null` releases it to full opacity. */
export function setSpokenWords(root: Element, words: number | null): void {
  const range = words === null ? null : unspokenRange(root, words);
  if (range) rangesByRoot.set(root, range);
  else if (!rangesByRoot.delete(root)) return;
  sync();
}

export function spokenWordHighlightSupported(): boolean { return registry() !== null; }
