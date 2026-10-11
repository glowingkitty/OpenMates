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
});
