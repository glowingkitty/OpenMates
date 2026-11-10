/**
 * Unit tests for the slides editor view helpers: DeckView (the core's committed wire
 * fixture) to renderer slide, the in-progress drag rectangle, and the contenteditable
 * DOM to inline markup glue. Deck changes themselves are the core's and are tested in
 * packages/openmates-rust (deck_operations_tests.rs, deck_handles_tests.rs).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { DeckView } from '../../../services/rustCore/deckDocument/deckDocumentTypes';
import { dragBox, effectiveTextStyle, isTypingTarget, toRenderSlide } from './slidesEditorView';
import { editableToMarkup, escapeInlineText, fillEditable } from './slidesEditorText';
import { parseInlineMarkup, parseSlidesMarkup } from './slidesMarkup';
import { getTemplate, placeElements } from './slidesTemplates';
import { normalisedEditorDeck } from './slidesPreviewFixture';

const fixture = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../../../../packages/openmates-rust/src/client/shared_items/deck_wire_fixture.json'), 'utf8')
) as { view: DeckView };

const CANVAS = { width: 1920, height: 1080 };

describe('toRenderSlide', () => {
  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('maps every element kind of the core view to the renderer model', () => {
    const slide = toRenderSlide(fixture.view.slides[0]);
    expect(slide.id).toBe('s1');
    expect(slide.transition).toBe('fade');
    expect(slide.notes).toBe('Speaker notes\nsecond line & more.');
    expect(slide.elements.map((element) => element.type)).toEqual([
      'text', 'image', 'video', 'shape', 'notepad', 'todo', 'link', 'block'
    ]);
    const [text, image, video, shape, notepad, todo, link, block] = slide.elements;
    expect(text).toMatchObject({ role: 'title', font: 'Georgia', size: 64, color: '#ff8800', align: 'center', weight: 'bold', step: 1, animate: 'fade' });
    expect(text.box).toEqual({ x: 80, y: 60, w: 1200, h: 120 });
    expect(text.type === 'text' && text.content[0]).toEqual({ kind: 'text', text: 'Q3 ' });
    expect(image).toMatchObject({ ref: 'revenue-chart', alt: 'Revenue chart', fit: 'cover' });
    expect(video).toMatchObject({ provider: 'youtube', ref: 'abc123' });
    expect(shape).toMatchObject({ kind: 'rect', fill: 'accent', stroke: '#000' });
    expect(notepad).toMatchObject({ title: 'Ideas', text: '', hidden: false });
    expect(todo).toMatchObject({ items: [{ done: false, label: 'Book venue' }, { done: true, label: 'Send <invite>' }] });
    expect(link).toMatchObject({ href: 'https://example.com/a?b=1', label: 'Source', box: {} });
    expect(block.type === 'block' && block.body).toContain('<script>');
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('renders the same inline nodes as the viewer parser for the same text', () => {
    const viewer = parseSlidesMarkup(normalisedEditorDeck);
    expect(viewer.ok).toBe(true);
    if (!viewer.ok) return;
    const viewerText = viewer.deck.slides[1].elements[1];
    const fromCore = parseInlineMarkup('<ul><li>Revenue up <b>18%</b></li><li>Two new regions</li></ul>');
    expect(viewerText.type === 'text' && viewerText.content).toEqual(fromCore);
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('applies the drag rectangle and empties the box being typed in', () => {
    const source = fixture.view.slides[0];
    const slide = toRenderSlide(source, { drag: { elementId: 'e2', box: { x: 1, y: 2, w: 3, h: 4 } }, typingId: 'e1' });
    expect(slide.elements[1].box).toEqual({ x: 1, y: 2, w: 3, h: 4 });
    expect(slide.elements[0].type === 'text' && slide.elements[0].content).toEqual([]);
    // The core's view object is never mutated.
    expect(source.elements[1].x).toBe(1000);
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('gives layout-placed text its slot typography', () => {
    const viewer = parseSlidesMarkup(normalisedEditorDeck);
    if (!viewer.ok) throw new Error('fixture parses');
    const template = getTemplate('builtin:plain');
    const placed = placeElements(viewer.deck.slides[0], template, 1080);
    expect(effectiveTextStyle(placed[0], template)).toMatchObject({ size: 104, weight: 'bold', align: 'center' });
    expect(placed[0].box.w).toBeGreaterThan(0);
  });
});

describe('dragBox', () => {
  const start = { x: 100, y: 100, w: 400, h: 200 };

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('moves by the canvas delta and stays inside the canvas', () => {
    expect(dragBox(start, 'move', 50.4, -20.6, CANVAS)).toEqual({ x: 150, y: 79, w: 400, h: 200 });
    expect(dragBox(start, 'move', -500, 5000, CANVAS)).toEqual({ x: 0, y: 880, w: 400, h: 200 });
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('resizes from each handle with the opposite edge fixed', () => {
    expect(dragBox(start, 'se', 100, 50, CANVAS)).toEqual({ x: 100, y: 100, w: 500, h: 250 });
    expect(dragBox(start, 'nw', 50, 50, CANVAS)).toEqual({ x: 150, y: 150, w: 350, h: 150 });
    expect(dragBox(start, 'n', 0, -150, CANVAS)).toEqual({ x: 100, y: 0, w: 400, h: 300 });
    expect(dragBox(start, 'e', 5000, 0, CANVAS)).toEqual({ x: 100, y: 100, w: 1820, h: 200 });
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('never collapses below the minimum size', () => {
    expect(dragBox(start, 'w', 1000, 0, CANVAS).w).toBe(20);
    expect(dragBox(start, 's', 0, -1000, CANVAS).h).toBe(20);
  });
});

describe('text box DOM glue', () => {
  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('round-trips inline content through the editable element', () => {
    const root = document.createElement('div');
    const markup = 'Q3 <b>results</b> &amp; <i>more</i><br/><ul><li>one</li><li>two &lt;3</li></ul>';
    fillEditable(root, parseInlineMarkup(markup));
    expect(root.querySelector('b')?.textContent).toBe('results');
    expect(editableToMarkup(root)).toBe(markup);
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('maps browser editing DOM to the inline subset', () => {
    const root = document.createElement('div');
    root.append('First');
    const line = document.createElement('div');
    const strong = document.createElement('strong');
    strong.textContent = 'bold\u00a0line';
    const span = document.createElement('span');
    span.textContent = ' <x>';
    line.append(strong, span);
    root.append(line, document.createElement('br'));
    expect(editableToMarkup(root)).toBe('First<br/><b>bold line</b> &lt;x&gt;');
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('escapes plain text for new text boxes', () => {
    expect(escapeInlineText('a < b & c > d')).toBe('a &lt; b &amp; c &gt; d');
  });

  // contract-test: supporting surface=gui.web assertions=slides.editor.direct-manipulation
  it('recognises fields that keep their own undo', () => {
    const editable = document.createElement('div');
    editable.contentEditable = 'true';
    document.body.append(editable);
    expect(isTypingTarget(document.createElement('textarea'))).toBe(true);
    expect(isTypingTarget(document.createElement('button'))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
    editable.remove();
  });
});
