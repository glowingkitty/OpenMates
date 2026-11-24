/**
 * TipTap atom node `rawBlock` for live documents: a block the editor cannot model (raw HTML
 * the core keeps verbatim). It renders the HTML read-only through the docs sanitizer and is
 * never editable here; the attribute `html` is what the core stores.
 */
import { Node } from '@tiptap/core';
import { sanitizeDocumentHtml } from './docsEmbedContent';

export const RawBlock = Node.create({
  name: 'rawBlock',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: false,
  addAttributes() {
    return { html: { default: '' } };
  },
  parseHTML() {
    return [{ tag: 'div[data-raw-block]', getAttrs: (el) => ({ html: (el as HTMLElement).innerHTML }) }];
  },
  renderHTML() {
    return ['div', { 'data-raw-block': '', 'data-testid': 'docs-raw-block' }];
  },
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement('div');
      dom.setAttribute('data-raw-block', '');
      dom.setAttribute('data-testid', 'docs-raw-block');
      dom.contentEditable = 'false';
      dom.innerHTML = sanitizeDocumentHtml(String(node.attrs.html ?? ''));
      return { dom };
    };
  },
});
