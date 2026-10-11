// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { describe, expect, it } from 'vitest';
import { requiresInitialDiagramSnapshot, resolveDiagramVersionView } from './diagramHtmlHistory';

describe('diagram history seed', () => {
  it('reuses the immutable generated first revision and only seeds missing legacy history', () => {
    expect(requiresInitialDiagramSnapshot(1, [{ version_number: 1, has_snapshot: true }])).toBe(false);
    expect(requiresInitialDiagramSnapshot(1, [])).toBe(true);
    expect(requiresInitialDiagramSnapshot(1, [{ version_number: 1, has_snapshot: false }])).toBe(true);
    expect(requiresInitialDiagramSnapshot(2, [])).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('shows historical source read-only while preserving the canonical head for edit and restore', () => {
    expect(resolveDiagramVersionView(2, '<html>head</html>', { version: 1, source: '<html>first</html>' }))
      .toEqual({ source: '<html>first</html>', historical: true, canEdit: false, pending: false, unavailable: false });
    expect(resolveDiagramVersionView(2, '<html>head</html>', { version: 1, source: null }))
      .toEqual({ source: '<html>head</html>', historical: true, canEdit: false, pending: true, unavailable: false });
    expect(resolveDiagramVersionView(2, '<html>head</html>', { version: 1, source: null, failed: true }))
      .toEqual({ source: '<html>head</html>', historical: true, canEdit: false, pending: false, unavailable: true });
    expect(resolveDiagramVersionView(2, '<html>head</html>', { version: 2, source: null }))
      .toEqual({ source: '<html>head</html>', historical: false, canEdit: true, pending: false, unavailable: false });
  });
});
