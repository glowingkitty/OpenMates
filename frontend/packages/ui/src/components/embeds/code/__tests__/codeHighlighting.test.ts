// frontend/packages/ui/src/components/embeds/code/__tests__/codeHighlighting.test.ts
//
// Regression coverage for unsupported syntax-highlighting languages. Domain
// embed languages such as Atopile should render as escaped/autodetected code
// without letting highlight.js emit a console error in fullscreen views.
// PCB schematic embeds use this path in fullscreen, so a noisy highlighter
// failure can make the reported issue look like a broken embed renderer.

import { afterEach, describe, expect, it, vi } from 'vitest';

import { highlightToLines } from '../codeHighlighting';

describe('highlightToLines', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('falls back for unsupported Atopile without logging a highlight.js error', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const lines = highlightToLines('module App:\n    pass', 'atopile');

    expect(lines).toHaveLength(2);
    expect(lines.join('\n')).toContain('module');
    expect(consoleError).not.toHaveBeenCalledWith(
      expect.stringContaining("Could not find the language 'atopile'")
    );
  });
});
