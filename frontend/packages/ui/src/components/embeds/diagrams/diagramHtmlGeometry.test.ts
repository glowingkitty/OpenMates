// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { describe, expect, it } from 'vitest';
import { diagramBoundsInTarget } from './diagramHtmlGeometry';
import { diagramEditorScript } from './diagramHtmlRuntime';

describe('diagram connector coordinate geometry', () => {
  it('cancels the SVG viewBox and stage scale before writing path coordinates', () => {
    const viewport = { a: 1.176, b: 0, c: 0, d: 1.176, e: 64, f: 92 };
    const node = { x: 120, y: 80, width: 100, height: 50 };
    const bounds = diagramBoundsInTarget(node, viewport, viewport);
    expect(bounds).not.toBeNull();
    expect(bounds!.right).toBeCloseTo(220);
    expect(bounds!.top + bounds!.height / 2).toBeCloseTo(105);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('maps a dragged component into a translated edge path group', () => {
    const nodeToScreen = { a: 2, b: 0, c: 0, d: 2, e: 180, f: 70 };
    const pathToScreen = { a: 2, b: 0, c: 0, d: 2, e: 100, f: 50 };
    const bounds = diagramBoundsInTarget({ x: 10, y: 20, width: 30, height: 40 }, nodeToScreen, pathToScreen);
    expect(bounds).toEqual({ left: 50, right: 80, top: 30, bottom: 70, width: 30, height: 40 });
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('handles rotation and refuses a singular target coordinate system', () => {
    const rotated = { a: 0, b: 1, c: -1, d: 0, e: 30, f: 10 };
    const identity = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
    expect(diagramBoundsInTarget({ x: 0, y: 0, width: 10, height: 20 }, rotated, identity))
      .toEqual({ left: 10, right: 30, top: 10, bottom: 20, width: 20, height: 10 });
    expect(diagramBoundsInTarget({ x: 0, y: 0, width: 10, height: 20 }, rotated,
      { a: 0, b: 0, c: 0, d: 0, e: 0, f: 0 })).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('bundles the geometry helper into the sandboxed editor runtime', () => {
    const script = diagramEditorScript('test-token');
    expect(script).toContain('function diagramBoundsInTarget');
    expect(script).not.toContain('getCTM()');
  });
});
