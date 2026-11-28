// @vitest-environment jsdom
// frontend/packages/ui/src/utils/__tests__/messageHighlights.test.ts
//
// Selection toolbar inputs: a clicked embed card (ProseMirror node selection)
// is not selected text, and embed card text never becomes part of a highlight.
// Production finding: the toolbar opened over an event card after it was clicked.

import { describe, expect, it } from 'vitest';
import { captureHighlightAnchor, isNodeSelectionRange } from '../messageHighlights';

function messageBody(): HTMLElement {
  const root = document.createElement('div');
  root.innerHTML = [
    '<p>The next edition takes place at the campus.</p>',
    '<div class="embed-preview-large-node" contenteditable="false"><span>Sat 30</span><strong>Example Conf 2027</strong></div>',
    '<p>A few other events follow.</p>',
  ].join('');
  document.body.replaceChildren(root);
  return root;
}

describe('message selection helpers', () => {
  // contract-test: supporting surface=gui.web assertions=message-highlights.selection-toolbar
  it('treats a range wrapping one embed card as a node selection', () => {
    const root = messageBody();
    const range = document.createRange();
    range.setStart(root, 1);
    range.setEnd(root, 2);
    expect(isNodeSelectionRange(range)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=message-highlights.selection-toolbar
  it('does not treat selected text as a node selection', () => {
    const root = messageBody();
    const text = root.querySelector('p')!.firstChild!;
    const range = document.createRange();
    range.setStart(text, 4);
    range.setEnd(text, 16);
    expect(isNodeSelectionRange(range)).toBe(false);
    expect(captureHighlightAnchor(root, range)?.exact).toBe('next edition');
  });

  // contract-test: supporting surface=gui.web assertions=message-highlights.selection-toolbar
  it('does not treat a range over a whole paragraph and its neighbours as a node selection', () => {
    const root = messageBody();
    const range = document.createRange();
    range.setStart(root, 0);
    range.setEnd(root, 3);
    expect(isNodeSelectionRange(range)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-highlights.selection-toolbar
  it('keeps large embed card text out of highlight anchors', () => {
    const root = messageBody();
    const cardRange = document.createRange();
    cardRange.selectNodeContents(root.querySelector('.embed-preview-large-node')!);
    expect(captureHighlightAnchor(root, cardRange)).toBeNull();

    const across = document.createRange();
    const first = root.querySelector('p')!.firstChild!;
    across.setStart(first, first.textContent!.indexOf('campus'));
    across.setEnd(root.querySelectorAll('p')[1].firstChild!, 5);
    const anchor = captureHighlightAnchor(root, across);
    expect(anchor?.exact).toBe('campus.A few');
    expect(anchor?.exact).not.toContain('Example Conf');
  });
});
