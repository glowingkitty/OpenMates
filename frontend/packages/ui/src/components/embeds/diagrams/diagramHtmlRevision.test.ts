// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { describe, expect, it } from 'vitest';
import { buildUnifiedDiff } from '../../../utils/embedUnifiedDiff';
import { applyVersionPatch } from '../../../utils/embedVersionReconstruction';
import { classifyDiagramRevisionBroadcast, reconcileCommittedDiagramRevision } from './diagramHtmlReceipt';

describe('diagram revision transport', () => {
  it.each([
    ['<text>before</text>', '<text>after</text>'],
    ['<html>\n<body>\n<svg/>\n</body>\n</html>', '<html>\n<body>\n<svg><text>edit</text></svg>\n</body>\n</html>'],
    ['prefix\nold\nsuffix', 'prefix\nnew\nsuffix'],
    ['first\nlast', 'first\nlast\n'],
    ['first\nlast\n', 'first\nlast'],
  ])('reconstructs the exact canonical source from a revision patch', (before, after) => {
    expect(applyVersionPatch(before, buildUnifiedDiff(before, after, 1, 2))).toBe(after);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('keeps an acknowledged save successful when local cache reconciliation fails', async () => {
    let calls = 0;
    const synchronized = await reconcileCommittedDiagramRevision(async () => {
      calls++;
      throw new Error('IndexedDB unavailable');
    });
    expect(synchronized).toBe(false);
    expect(calls).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('defers broadcasts during the atomic save while preserving other-device conflicts', () => {
    expect(classifyDiagramRevisionBroadcast(true, true)).toBe('defer');
    expect(classifyDiagramRevisionBroadcast(false, true)).toBe('conflict');
    expect(classifyDiagramRevisionBroadcast(false, false)).toBe('refresh');
  });
});
