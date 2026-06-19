// frontend/packages/ui/src/components/embeds/code/ApplicationEmbedPreview.test.ts
// Unit coverage for temporarily disabled application embed registration and text output.
// The package does not currently use a Svelte component mounting harness for
// embed previews, so this test verifies the compile-time registry and the
// copied/exported text representation that shares the same application schema.
// Architecture: docs/specs/application-embeds/spec.yml

import { describe, expect, it } from 'vitest';
import {
  EMBED_FULLSCREEN_COMPONENTS,
  EMBED_PREVIEW_COMPONENTS,
  EMBED_RENDERER_MAP,
} from '../../../data/embedRegistry.generated';
import { renderEmbedAsText } from '../../../data/embedTextRenderers';

describe('application embed registry', () => {
  it('does not register application preview, fullscreen, or message renderer entries while disabled', () => {
    expect(EMBED_PREVIEW_COMPONENTS['code-application']).toBeUndefined();
    expect(EMBED_FULLSCREEN_COMPONENTS['code-application']).toBeUndefined();
    expect(EMBED_RENDERER_MAP['code-application']).toBeUndefined();
  });
});

describe('application embed text rendering', () => {
  it('renders manifest metadata and child file refs without DOM snapshots', () => {
    const result = renderEmbedAsText('code-application', {
      name: 'Recipe Manager',
      framework: 'Svelte',
      runtime: 'Node',
      rendered_dom_snapshot: '<main>should not be stored or rendered</main>',
      file_refs: [
        { path: 'package.json' },
        { path: 'src/App.svelte' },
        { path: 'src/main.ts' },
      ],
    });

    expect(result).toContain('**Application**');
    expect(result).toContain('Recipe Manager');
    expect(result).toContain('Svelte · Node · 3 files');
    expect(result).toContain('src/App.svelte');
    expect(result).not.toContain('rendered_dom_snapshot');
    expect(result).not.toContain('should not be stored or rendered');
  });
});
