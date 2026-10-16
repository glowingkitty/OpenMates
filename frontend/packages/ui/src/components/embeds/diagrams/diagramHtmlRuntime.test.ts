// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { describe, expect, it, vi } from 'vitest';
import { diagramEditorScript } from './diagramHtmlRuntime';

describe('diagram editor iframe runtime', () => {
  it('starts as a self-contained script and acknowledges the validated edit token', () => {
    const script = diagramEditorScript('ready-token');
    expect(script).not.toContain('__name(');
    expect(script).not.toContain('__OM_DIAGRAM_TOKEN__');
    expect(script).not.toContain('__OM_DIAGRAM_BOUNDS__');

    const postMessage = vi.fn();
    const frameDocument = {
      createElement: () => ({ dataset: {}, textContent: '' }),
      head: { append: vi.fn() },
      addEventListener: vi.fn(),
    };
    const frameWindow = { addEventListener: vi.fn() };
    new Function('document', 'window', 'parent', script)(frameDocument, frameWindow, { postMessage });
    expect(postMessage).toHaveBeenCalledWith({ channel: 'openmates-diagram-editor-v1', token: 'ready-token', kind: 'ready' }, '*');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('undo restores the primary diagram when a decorative SVG comes first', () => {
    const frameDocument = new DOMParser().parseFromString(
      '<html><head><title>Decorated</title></head><body><svg data-om-decorative="true" viewBox="0 0 10 10"><path d="M 0,0 H 10"/></svg><svg data-om-diagram="flow" viewBox="0 0 100 100"><text data-om-text="label" data-om-editable="text">Original</text></svg></body></html>',
      'text/html'
    );
    const decorativeBefore = frameDocument.querySelector('svg[data-om-decorative]')?.outerHTML;
    const postMessage = vi.fn();
    new Function('document', 'window', 'parent', 'DOMParser', diagramEditorScript('undo-token'))(
      frameDocument, { addEventListener: vi.fn() }, { postMessage }, DOMParser
    );

    frameDocument.querySelector('text[data-om-text="label"]')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    const input = frameDocument.querySelector<HTMLInputElement>('[data-om-editor-input]');
    expect(input).not.toBeNull();
    input!.value = 'Edited';
    input!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(frameDocument.querySelector('svg[data-om-diagram] text')?.textContent).toBe('Edited');

    frameDocument.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true }));
    expect(frameDocument.querySelector('svg[data-om-diagram] text')?.textContent).toBe('Original');
    expect(frameDocument.querySelector('svg[data-om-decorative]')?.outerHTML).toBe(decorativeBefore);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('moves a sequence participant column without collapsing separate message rows', () => {
    const frameDocument = new DOMParser().parseFromString(
      '<html><head><title>Sequence</title></head><body><svg data-om-diagram="sequence" viewBox="0 0 240 220">' +
      '<line data-om-owner="actor-a" x1="50" x2="50" y1="20" y2="200"/>' +
      '<rect x="46" y="70" width="8" height="30"/>' +
      '<g data-om-edge="first" data-om-from="actor-a" data-om-to="actor-b" data-om-from-side="right" data-om-to-side="left"><path data-om-path d="M 50 100 H 150"/></g>' +
      '<g data-om-edge="second" data-om-from="actor-a" data-om-to="actor-b" data-om-from-side="right" data-om-to-side="left"><path data-om-path d="M 50 160 H 150"/></g>' +
      '<g data-om-edge="rounded-q" data-om-from="actor-a" data-om-to="actor-b" data-om-from-side="right" data-om-to-side="left"><path data-om-path d="M 50 170 H 80 Q 88 170 88 178 V 190 H 150"/></g>' +
      '<g data-om-edge="rounded-a" data-om-from="actor-a" data-om-to="actor-b" data-om-from-side="right" data-om-to-side="left"><path data-om-path d="M 50 180 H 80 A 8 8 0 0 1 88 188 V 206 H 150"/></g>' +
      '<g data-om-component="actor-a" data-om-editable="true"><rect x="30" y="0" width="40" height="20"/></g>' +
      '<g data-om-component="actor-b" data-om-editable="true"><rect x="130" y="0" width="40" height="20"/></g>' +
      '</svg></body></html>', 'text/html'
    );
    const svg = frameDocument.querySelector('svg')!;
    const translation = (element: Element) => {
      let x = 0;
      for (let node: Element | null = element; node; node = node.parentElement) {
        x += Number(/translate\(\s*([+-]?\d+(?:\.\d+)?)/.exec(node.getAttribute('transform') ?? '')?.[1] ?? 0);
      }
      return x;
    };
    for (const element of [svg, ...Array.from(svg.querySelectorAll('*'))]) {
      Object.assign(element, {
        getScreenCTM: () => {
          const e = translation(element);
          return { a: 1, b: 0, c: 0, d: 1, e, f: 0, inverse: () => ({ a: 1, b: 0, c: 0, d: 1, e: -e, f: 0 }) };
        },
        getBBox: () => {
          const shape = element.localName === 'g' ? element.querySelector('rect')! : element;
          if (shape.localName === 'line') {
            const x = Number(shape.getAttribute('x1')), y = Number(shape.getAttribute('y1'));
            return { x, y, width: 0, height: Number(shape.getAttribute('y2')) - y };
          }
          return { x: Number(shape.getAttribute('x')), y: Number(shape.getAttribute('y')),
            width: Number(shape.getAttribute('width')), height: Number(shape.getAttribute('height')) };
        },
      });
      if (element.localName === 'path') Object.assign(element, {
        getTotalLength: () => 100,
        getPointAtLength: (distance: number) => {
          const path = element.getAttribute('d')!;
          const [, startX, startY] = /M\s*([\d.]+)[,\s]+([\d.]+)/.exec(path)!;
          const endX = Number([...path.matchAll(/H\s*([\d.]+)/g)].at(-1)?.[1] ?? startX);
          const endY = Number([...path.matchAll(/V\s*([\d.]+)/g)].at(-1)?.[1] ?? startY);
          return distance <= 0 ? { x: Number(startX), y: Number(startY) }
            : distance >= 100 ? { x: endX, y: endY }
              : { x: (Number(startX) + endX) / 2, y: (Number(startY) + endY) / 2 };
        },
      });
    }
    const actor = svg.querySelector<SVGGElement>('g[data-om-component="actor-a"]')!;
    Object.assign(actor, { setPointerCapture: vi.fn() });
    class TestPoint {
      constructor(public x: number, public y: number) {}
      matrixTransform(matrix: { e: number; f: number }) { return new TestPoint(this.x + matrix.e, this.y + matrix.f); }
    }
    new Function('document', 'window', 'parent', 'DOMParser', 'DOMPoint', diagramEditorScript('sequence-token'))(
      frameDocument, { addEventListener: vi.fn() }, { postMessage: vi.fn() }, DOMParser, TestPoint
    );
    const pointer = (type: string, target: Element, x: number, y: number) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperties(event, { clientX: { value: x }, clientY: { value: y }, pointerId: { value: 1 } });
      target.dispatchEvent(event);
    };
    pointer('pointerdown', actor.querySelector('rect')!, 50, 10);
    pointer('pointermove', actor.querySelector('rect')!, 70, 60);
    pointer('pointerup', actor.querySelector('rect')!, 70, 60);

    const first = svg.querySelector('g[data-om-edge="first"] path')!.getAttribute('d')!;
    const second = svg.querySelector('g[data-om-edge="second"] path')!.getAttribute('d')!;
    expect(first).toMatch(/^M 70,100 /);
    expect(second).toMatch(/^M 70,160 /);
    const roundedQ = svg.querySelector('g[data-om-edge="rounded-q"] path')!.getAttribute('d')!;
    const roundedA = svg.querySelector('g[data-om-edge="rounded-a"] path')!.getAttribute('d')!;
    expect(roundedQ).toBe('M 70,170 H 80 Q 88 170 88 178 V 190 H 150');
    expect(roundedA).toBe('M 70,180 H 80 A 8 8 0 0 1 88 188 V 206 H 150');
    expect(roundedQ.match(/\bM\b/g)).toHaveLength(1);
    expect(roundedA.match(/\bM\b/g)).toHaveLength(1);
    expect(actor.getAttribute('transform')).toBe('translate(20 0)');
    expect(svg.querySelector('line[data-om-owner="actor-a"]')?.getAttribute('transform')).toBe('translate(20 0)');
    expect(svg.querySelector('rect[x="46"]')?.getAttribute('transform')).toBe('translate(20 0)');

    frameDocument.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true }));
    expect(frameDocument.querySelector('g[data-om-edge="first"] path')?.getAttribute('d')).toBe('M 50 100 H 150');
    expect(frameDocument.querySelector('g[data-om-edge="second"] path')?.getAttribute('d')).toBe('M 50 160 H 150');
    expect(frameDocument.querySelector('g[data-om-edge="rounded-q"] path')?.getAttribute('d')).toBe('M 50 170 H 80 Q 88 170 88 178 V 190 H 150');
    expect(frameDocument.querySelector('g[data-om-edge="rounded-a"] path')?.getAttribute('d')).toBe('M 50 180 H 80 A 8 8 0 0 1 88 188 V 206 H 150');
    expect(frameDocument.querySelector('line[data-om-owner="actor-a"]')?.hasAttribute('transform')).toBe(false);
  });
});
