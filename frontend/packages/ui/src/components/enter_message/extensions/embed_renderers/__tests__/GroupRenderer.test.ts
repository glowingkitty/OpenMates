// frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/__tests__/GroupRenderer.test.ts
// Unit coverage for grouped embed renderer fallbacks.
// These tests guard the public example/shared-chat rendering path without
// mounting real Svelte components, IndexedDB records, or network-backed embeds.
// Architecture: docs/specs/code-image-to-html/spec.yml

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { EmbedNodeAttributes } from '../../../../../message_parsing/types';
import GenericAppSkillEmbedPreview from '../../../../embeds/app_skill/GenericAppSkillEmbedPreview.svelte';
import { GroupRenderer } from '../GroupRenderer';

const svelteMountMocks = vi.hoisted(() => ({
  mount: vi.fn(() => ({ destroy: vi.fn() })),
  unmount: vi.fn(),
}));

vi.mock('svelte', async (importOriginal) => {
  const actual = await importOriginal<typeof import('svelte')>();

  return {
    ...actual,
    mount: svelteMountMocks.mount,
    unmount: svelteMountMocks.unmount,
  };
});

describe('GroupRenderer', () => {
  beforeEach(() => {
    svelteMountMocks.mount.mockClear();
    svelteMountMocks.unmount.mockClear();

    Object.defineProperty(globalThis, 'CSS', {
      configurable: true,
      value: {
        escape: (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, '\\$&'),
      },
    });
  });

  it('mounts the generic app-skill card for unknown app skills in groups', async () => {
    const renderer = new GroupRenderer();
    const container = document.createElement('div');
    const content = document.createElement('div');
    container.appendChild(content);

    const groupedItem: EmbedNodeAttributes = {
      id: 'image-to-html-run',
      type: 'app-skill-use',
      status: 'finished',
      contentRef: '',
      app_id: 'code',
      skill_id: 'image_to_html',
      provider: 'OpenMates',
      query: 'Convert this screenshot into HTML',
    };

    await renderer.render({
      attrs: {
        id: 'app-skill-group',
        type: 'app-skill-use-group',
        status: 'finished',
        contentRef: '',
        groupedItems: [groupedItem],
        groupCount: 1,
      },
      container,
      content,
    });

    expect(svelteMountMocks.mount).toHaveBeenCalledWith(
      GenericAppSkillEmbedPreview,
      expect.objectContaining({
        props: expect.objectContaining({
          appId: 'code',
          skillId: 'image_to_html',
          status: 'finished',
          provider: 'OpenMates',
          isMobile: false,
        }),
      }),
    );
    expect(content.querySelector('[data-embed-type="app-skill-use"]')).toBeNull();
    expect(content.textContent).not.toContain('Skill: code | image_to_html');
  });
});
