import { afterEach, expect, it, vi } from 'vitest';
import { animateWorkspacePane, workspacePaneMotion } from '../workspacePaneMotion';

afterEach(() => vi.unstubAllGlobals());

// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.fullscreen-route-motion
it('retains the completed closing frame until asynchronous navigation explicitly releases it', async () => {
  vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
  const animation = {
    finished: Promise.resolve(), playState: 'finished', playbackRate: 1,
    currentTime: 0, cancel: vi.fn(), reverse: vi.fn(),
  };
  const node = { animate: vi.fn(() => animation) } as unknown as HTMLElement;
  const release = await animateWorkspacePane(node, false);
  // Navigation may still be awaiting a draft/composer reset after the visual close.
  await Promise.resolve();
  expect(animation.cancel).not.toHaveBeenCalled();
  expect(node.animate).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({
    duration: 320, easing: 'cubic-bezier(0.32, 0, 0.2, 1)', fill: 'both',
  }));
  release();
  expect(animation.cancel).toHaveBeenCalledOnce();
  release();
  expect(animation.cancel).toHaveBeenCalledOnce();
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.fullscreen-route-motion
it('replaces a retained closing frame when a new pane opens', async () => {
  vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
  const closing = { finished: Promise.resolve(), playState: 'finished', playbackRate: 1, currentTime: 0, cancel: vi.fn(), reverse: vi.fn() };
  const opening = { ...closing, cancel: vi.fn(), reverse: vi.fn() };
  const node = { animate: vi.fn().mockReturnValueOnce(closing).mockReturnValueOnce(opening) } as unknown as HTMLElement;
  const releaseClosing = await animateWorkspacePane(node, false);
  await animateWorkspacePane(node, true);
  expect(closing.cancel).toHaveBeenCalledOnce();
  expect(opening.cancel).toHaveBeenCalledOnce();
  releaseClosing();
  expect(closing.cancel).toHaveBeenCalledOnce();
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.fullscreen-route-motion
it('respects reduced motion without allocating or retaining an animation', async () => {
  vi.stubGlobal('window', { matchMedia: () => ({ matches: true }) });
  const node = { animate: vi.fn() } as unknown as HTMLElement;
  const release = await animateWorkspacePane(node, false);
  release();
  expect(node.animate).not.toHaveBeenCalled();
  expect(workspacePaneMotion().duration).toBe(0);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.fullscreen-route-motion
it('keeps the final closing frame when an unfinished opening is reversed', async () => {
  vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
  let finish!: () => void;
  const animation = {
    finished: new Promise<void>(resolve => { finish = resolve; }), playState: 'running',
    playbackRate: 1, currentTime: 80, cancel: vi.fn(), reverse: vi.fn(),
  };
  const node = { animate: vi.fn(() => animation) } as unknown as HTMLElement;
  const opening = animateWorkspacePane(node, true);
  const closing = animateWorkspacePane(node, false);
  expect(animation.reverse).toHaveBeenCalledOnce();
  expect(node.animate).toHaveBeenCalledOnce();
  finish();
  await opening;
  const release = await closing;
  expect(animation.cancel).not.toHaveBeenCalled();
  release();
  expect(animation.cancel).toHaveBeenCalledOnce();
});
