// contract-test-file: infrastructure
import { describe, expect, it } from 'vitest';
import { EMBED_PREVIEW_COMPONENTS, EMBED_PREVIEW_COMPONENT_PRESENTATION, CONTENT_EMBED_CATALOG } from '../data/embedRegistry.generated';
import { getComponentPreviewPresentation, getEmbedPreviewPresentation } from './embedPreviewPresentation';

describe('embed preview presentation', () => {
  it('defaults unknown, synthetic and direct content to corner presentation', () => {
    for (const type of [undefined, '', 'document', 'code', 'sheet', 'listing', 'event', 'unknown']) {
      expect(getEmbedPreviewPresentation(type)).toBe('content');
    }
  });
  it('uses actual direct types before colliding execution skill routes', () => {
    expect(getEmbedPreviewPresentation('hosting_domain', 'app:hosting:search_domains')).toBe('content');
    expect(getEmbedPreviewPresentation('icon_result', 'app:design:search_icons')).toBe('content');
    expect(getEmbedPreviewPresentation('generated_audio', 'app:audio:generate')).toBe('content');
  });
  it('classifies known and unregistered execution routes without skill allowlists', () => {
    expect(getEmbedPreviewPresentation('app_skill_use')).toBe('execution');
    expect(getEmbedPreviewPresentation('app-skill-use', 'app:web:search')).toBe('execution');
    expect(getEmbedPreviewPresentation(undefined, 'app:future:unknown_skill')).toBe('execution');
    expect(getEmbedPreviewPresentation('app:future:unknown_skill')).toBe('execution');
    expect(getEmbedPreviewPresentation(undefined, 'app:code:*')).toBe('content');
    expect(getEmbedPreviewPresentation('app-skill-use', 'app:code:*')).toBe('execution');
  });
  it('honors durable self-content routes such as Remotion video compositions', () => {
    expect(getEmbedPreviewPresentation('app_skill_use', 'app:videos:create')).toBe('content');
    expect(getEmbedPreviewPresentation('app:videos:create')).toBe('content');
    expect(getEmbedPreviewPresentation('app_skill_use', 'app:videos:search')).toBe('execution');
  });
  it('classifies component preview paths and defaults unmapped components to content', () => {
    expect(getComponentPreviewPresentation('embeds/code/CodeEmbedPreview')).toBe('content');
    expect(getComponentPreviewPresentation('/dev/preview/embeds/docs/DocsEmbedPreview')).toBe('content');
    expect(getComponentPreviewPresentation('sheets/SheetEmbedPreview.svelte')).toBe('content');
    expect(getComponentPreviewPresentation('web/WebSearchEmbedPreview')).toBe('execution');
    expect(getComponentPreviewPresentation('videos/VideoCreateEmbedPreview')).toBe('content');
    expect(getComponentPreviewPresentation('unknown/Preview')).toBe('content');
  });
  it('covers every registered component and prefers content when routes share it', () => {
    const durable = new Set(CONTENT_EMBED_CATALOG.filter(item => item.source === 'self').map(item => item.registryKey));
    for (const path of new Set(Object.values(EMBED_PREVIEW_COMPONENTS))) {
      const keys = Object.keys(EMBED_PREVIEW_COMPONENTS).filter(key => EMBED_PREVIEW_COMPONENTS[key] === path);
      const expected = keys.some(key => !key.startsWith('app:') || durable.has(key)) ? 'content' : 'execution';
      expect(EMBED_PREVIEW_COMPONENT_PRESENTATION[path], path).toBe(expected);
    }
  });
});
