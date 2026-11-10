/**
 * Unit tests for the client slides parser. The hostile cases mirror
 * backend/tests/test_slides_markup.py (assertion
 * slides.security.host-rendered-and-isolated).
 */
import { describe, expect, it } from 'vitest';
import { parseSlidesMarkup, inlineToPlainText, type Deck, type SlideElement } from './slidesMarkup';

const VALID = `<deck title="Q3 results" aspect="16:9" template="builtin:plain">
  <slide layout="title-and-content" transition="fade">
    <text role="title" x="80" y="60" w="1200" h="120">Q3 <b>results</b></text>
    <image src="embed:revenue-chart" x="1000" y="220" w="800" h="500" alt="Revenue chart"/>
    <video src="youtube:abc123xyz" x="80" y="220" w="860" h="484"/>
    <shape kind="rect" fill="accent" x="0" y="1000" w="1920" h="80"/>
    <notepad title="Ideas" x="80" y="740" w="860" h="260"/>
    <todo title="Next" x="1000" y="760" w="800" h="240"><item done="false">Book venue</item></todo>
    <notes>Speaker notes.</notes>
  </slide>
  <slide>
    <text role="title">Second</text>
  </slide>
</deck>`;

function deckOf(source: string, partial = false): Deck {
  const result = parseSlidesMarkup(source, { partial });
  if (!('deck' in result)) throw new Error(`parse failed: ${result.reason}`);
  return result.deck;
}

function types(elements: SlideElement[]): string[] {
  return elements.map((element) => element.type);
}

describe('parseSlidesMarkup', () => {
  // contract-test: supporting surface=gui.web assertions=slides.format.positioned-elements
  it('parses a valid deck with stable ids and every element kind', () => {
    const deck = deckOf(VALID);
    expect([deck.title, deck.aspect, deck.height, deck.slides.length]).toEqual(['Q3 results', '16:9', 1080, 2]);
    const [first, second] = deck.slides;
    expect(first.id).toBe('s1');
    expect(second.id).toBe('s2');
    expect(first.layout).toBe('title-and-content');
    expect(first.transition).toBe('fade');
    expect(types(first.elements)).toEqual(['text', 'image', 'video', 'shape', 'notepad', 'todo']);
    expect(first.elements.map((element) => element.id)).toEqual(['e1', 'e2', 'e3', 'e4', 'e5', 'e6']);
    expect(first.notes).toBe('Speaker notes.');
    const title = first.elements[0];
    expect(title.type === 'text' && inlineToPlainText(title.content)).toBe('Q3 results');
    const image = first.elements[1];
    expect(image.type === 'image' && image.ref).toBe('revenue-chart');
    const todo = first.elements[5];
    expect(todo.type === 'todo' && todo.items).toEqual([{ done: false, label: 'Book venue' }]);
  });

  // contract-test: supporting surface=gui.web assertions=slides.format.positioned-elements
  it('clamps geometry to the canvas of the aspect', () => {
    const deck = deckOf('<deck aspect="4:3"><slide><shape kind="rect" x="1900" y="1400" w="900" h="900"/></slide></deck>');
    expect(deck.aspect).toBe('4:3');
    expect(deck.slides[0].elements[0].box).toEqual({ x: 1900, y: 1400, w: 20, h: 40 });
  });

  // contract-test: supporting surface=gui.web assertions=slides.format.positioned-elements
  it('keeps following siblings when void elements are not self-closed', () => {
    const deck = deckOf('<deck><slide><shape kind="rect"><text>after</text></slide></deck>');
    expect(types(deck.slides[0].elements)).toEqual(['shape', 'text']);
  });

  // contract-test: supporting surface=gui.web assertions=slides.security.host-rendered-and-isolated
  it('cleans a hostile deck', () => {
    const hostile = `<deck title="x">
      <slide onclick="steal()">
        <text role="title" onclick="steal()" style="x" data-x="1">Hi<script>evil()</script></text>
        <image src="https://evil.example/pixel.png" x="1" y="1" w="1" h="1"/>
        <image src="data:image/png;base64,AAAA"/>
        <script>alert(1)</script>
        <iframe src="https://evil.example"></iframe>
        <object data="x"></object>
        <marquee>unknown</marquee>
        <link href="javascript:alert(1)">bad</link>
        <link href="https://ok.example/page">ok</link>
        <video src="https://example.com/movie.mp4" x="5" y="5" w="50" h="50"/>
      </slide>
    </deck>`;
    const deck = deckOf(hostile);
    const elements = deck.slides[0].elements;
    expect(types(elements)).toEqual(['text', 'link', 'link']);
    const serialised = JSON.stringify(deck).toLowerCase();
    for (const forbidden of ['onclick', 'script', 'iframe', 'evil', 'style', 'data:', 'javascript', 'alert']) {
      expect(serialised, forbidden).not.toContain(forbidden);
    }
    const links = elements.filter((element) => element.type === 'link');
    expect(links.map((link) => link.type === 'link' && link.href)).toEqual([
      'https://ok.example/page',
      'https://example.com/movie.mp4'
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=slides.security.host-rendered-and-isolated
  it('rejects non-https links, credentials and non-embed image sources', () => {
    const deck = deckOf(`<deck><slide>
      <link href="http://plain.example">a</link>
      <link href="https://user:pw@host.example">b</link>
      <image src="embed:../../x"/>
      <video src="vimeo:abc"/>
    </slide></deck>`);
    expect(deck.slides[0].elements).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=slides.security.host-rendered-and-isolated
  it('keeps block bodies verbatim and opaque, cleaning only the attributes', () => {
    const body = '<script>alert("kept")</script>\n  <div onclick="x()">raw & <b>html</b></div>\n';
    const deck = deckOf(`<deck><slide><block x="1" y="2" w="300" h="200" onclick="x()">${body}</block></slide></deck>`);
    const block = deck.slides[0].elements[0];
    expect(block.type).toBe('block');
    expect(block.type === 'block' && block.body).toBe(body);
    expect(block.box).toEqual({ x: 1, y: 2, w: 300, h: 200 });
    expect(Object.keys(block)).not.toContain('onclick');
  });

  // contract-test: supporting surface=gui.web assertions=slides.security.host-rendered-and-isolated
  it('drops unterminated blocks', () => {
    const deck = deckOf('<deck><slide><text>a</text></slide><slide><block x="1">oops</slide></deck>');
    expect(deck.slides.flatMap((slide) => types(slide.elements))).toEqual(['text']);
  });

  // contract-test: supporting surface=gui.web assertions=slides.security.host-rendered-and-isolated
  it('limits inline formatting to whitelisted tags', () => {
    const deck = deckOf('<deck><slide><text>a <b>b</b> <a href="javascript:x">c</a><u onmouseover="x()">d</u><br/>e</text></slide></deck>');
    const text = deck.slides[0].elements[0];
    const json = JSON.stringify(text);
    expect(json).not.toContain('href');
    expect(json).not.toContain('onmouseover');
    expect(text.type === 'text' && text.content.some((node) => node.kind === 'br')).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=slides.format.positioned-elements
  it('rejects empty, oversized and slideless markup', () => {
    expect(parseSlidesMarkup('   ')).toEqual({ ok: false, reason: 'empty' });
    expect(parseSlidesMarkup('x'.repeat(1_000_001))).toEqual({ ok: false, reason: 'too-large' });
    expect(parseSlidesMarkup('<deck><text>no slide</text></deck>')).toEqual({ ok: false, reason: 'no-slide' });
  });

  // contract-test: supporting surface=gui.web assertions=slides.format.positioned-elements
  it('shows only completed slides while streaming', () => {
    const streaming = '<deck title="T"><slide><text>one</text></slide><slide><text>tw';
    expect(deckOf(streaming, true).slides.length).toBe(1);
    expect(deckOf('<deck title="T"><slide><text>on', true).slides.length).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=slides.security.host-rendered-and-isolated
  it('enforces the slide and element limits', () => {
    const many = `<deck>${'<slide><text>x</text></slide>'.repeat(205)}</deck>`;
    expect(deckOf(many).slides.length).toBe(200);
    const crowded = `<deck><slide>${'<shape kind="rect"/>'.repeat(205)}</slide></deck>`;
    expect(deckOf(crowded).slides[0].elements.length).toBe(200);
  });

  // contract-test: supporting surface=gui.web assertions=slides.format.positioned-elements
  it('falls back to defaults for invalid aspect and template', () => {
    const deck = deckOf('<deck aspect="21:9" template="evil:thing"><slide/></deck>');
    expect([deck.aspect, deck.template]).toEqual(['16:9', 'builtin:plain']);
  });
});
