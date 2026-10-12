// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { describe, expect, it, vi } from 'vitest';
import { diagramMeasureScript, nextDiagramPresentationHeight, readDiagramMeasurement } from './diagramHtmlMeasure';

describe('diagram artboard measurement', () => {
  it('reports complete rendered content only after fonts settle', async () => {
    let finishFonts!: () => void;
    const fontsReady = new Promise<void>((resolve) => { finishFonts = resolve; });
    const postMessage = vi.fn();
    const demandLayout = vi.fn(() => 700);
    const document = {
      fonts: { ready: fontsReady },
      body: { scrollHeight: 728, getBoundingClientRect: () => ({ bottom: 728 }), get offsetHeight() { return demandLayout(); } },
      documentElement: { scrollHeight: 700, getBoundingClientRect: () => ({ bottom: 700 }) },
    };
    const window = { innerWidth: 1040, innerHeight: 700, addEventListener: vi.fn() };
    const ResizeObserver = class { observe = vi.fn(); };
    const queueMicrotask = (callback: () => void) => { callback(); };
    const script = diagramMeasureScript('measure-token');
    expect(script).not.toContain('diagramMeasureRuntime(__OM_DIAGRAM_TOKEN__);');
    new Function('document', 'window', 'parent', 'ResizeObserver', 'queueMicrotask', script)(
      document, window, { postMessage }, ResizeObserver, queueMicrotask
    );
    expect(demandLayout).toHaveBeenCalledOnce();
    expect(postMessage).not.toHaveBeenCalled();
    finishFonts();
    await fontsReady;
    await Promise.resolve();
    expect(postMessage).toHaveBeenCalledWith({
      channel: 'openmates-diagram-measure-v1', kind: 'measure', token: 'measure-token',
      height: 728, width: 1040, viewportHeight: 700,
    }, '*');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('accepts only the current bounded message and grows until stable', () => {
    const message = { channel: 'openmates-diagram-measure-v1', kind: 'measure', token: 'current',
      height: 728, width: 1040, viewportHeight: 700 };
    expect(readDiagramMeasurement(message, 'current', 1040, 700)).toBe(728);
    expect(readDiagramMeasurement(message, 'old', 1040, 700)).toBeNull();
    expect(readDiagramMeasurement({ ...message, width: 1024 }, 'current', 1040, 700)).toBeNull();
    expect(readDiagramMeasurement({ ...message, viewportHeight: 728 }, 'current', 1040, 700)).toBeNull();
    expect(readDiagramMeasurement({ ...message, height: Number.NaN }, 'current', 1040, 700)).toBeNull();
    expect(nextDiagramPresentationHeight(700, 700, 728, 0)).toEqual({ height: 728, ready: false, error: false });
    expect(nextDiagramPresentationHeight(700, 728, 728, 1)).toEqual({ height: 728, ready: true, error: false });
    expect(nextDiagramPresentationHeight(700, 728, 4097, 1)).toEqual({ height: 728, ready: false, error: true });
    expect(nextDiagramPresentationHeight(700, 728, 740, 3)).toEqual({ height: 728, ready: false, error: true });
  });
});
