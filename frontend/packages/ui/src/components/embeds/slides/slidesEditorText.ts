/**
 * frontend/packages/ui/src/components/embeds/slides/slidesEditorText.ts
 *
 * DOM glue of the text box being typed in. `fillEditable` puts the box's current
 * content into a contenteditable element as real nodes (never HTML strings);
 * `editableToMarkup` reads what the browser's editing produced back as the inline
 * subset the core accepts (`b i u s br ul ol li`, escaped text). The core parses,
 * validates and normalises that markup on `set_text_content`; this file only
 * translates browser DOM (`strong`, `em`, `div` lines, `&nbsp;`) to that subset.
 * Live collaboration later replaces this with the Yjs rich-text mirror.
 */

import type { InlineNode } from './slidesMarkup';

const TAG_ALIASES: Record<string, string> = {
  b: 'b', strong: 'b',
  i: 'i', em: 'i',
  u: 'u', ins: 'u',
  s: 's', strike: 's', del: 's',
  ul: 'ul', ol: 'ol', li: 'li'
};
/** Elements a browser wraps a typed line in (Enter inside contenteditable). */
const LINE_TAGS = new Set(['div', 'p']);

/** Escapes plain text for inline markup. */
export function escapeInlineText(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Replaces the children of `root` with DOM nodes for `nodes`. */
export function fillEditable(root: HTMLElement, nodes: InlineNode[]): void {
  const doc = root.ownerDocument;
  const build = (parent: Node, list: InlineNode[]) => {
    for (const node of list) {
      if (node.kind === 'text') parent.appendChild(doc.createTextNode(node.text));
      else if (node.kind === 'br') parent.appendChild(doc.createElement('br'));
      else {
        const element = doc.createElement(node.tag);
        build(element, node.children);
        parent.appendChild(element);
      }
    }
  };
  root.replaceChildren();
  build(root, nodes);
}

function serialise(node: Node, out: string[]): void {
  if (node.nodeType === 3) {
    out.push(escapeInlineText((node.textContent ?? '').replace(/\u00a0/g, ' ')));
    return;
  }
  if (node.nodeType !== 1) return;
  const element = node as Element;
  const tag = element.localName.toLowerCase();
  if (tag === 'br') {
    out.push('<br/>');
    return;
  }
  if (LINE_TAGS.has(tag)) {
    // A line the browser started with Enter: break before it unless it opens the box.
    if (out.length > 0 && out[out.length - 1] !== '<br/>') out.push('<br/>');
    element.childNodes.forEach((child) => serialise(child, out));
    return;
  }
  const alias = TAG_ALIASES[tag];
  if (!alias) {
    element.childNodes.forEach((child) => serialise(child, out));
    return;
  }
  out.push(`<${alias}>`);
  element.childNodes.forEach((child) => serialise(child, out));
  out.push(`</${alias}>`);
}

/** Inline markup of the typed content; a trailing browser `<br>` is dropped. */
export function editableToMarkup(root: Node): string {
  const out: string[] = [];
  root.childNodes.forEach((child) => serialise(child, out));
  while (out.length > 0 && out[out.length - 1] === '<br/>') out.pop();
  return out.join('').trim();
}
