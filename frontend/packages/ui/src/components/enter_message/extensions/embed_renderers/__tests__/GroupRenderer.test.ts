// frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/__tests__/GroupRenderer.test.ts
// Unit coverage for grouped embed renderer fallbacks.
// These tests guard the public example/shared-chat rendering path without
// mounting real Svelte components, IndexedDB records, or network-backed embeds.
// Architecture: docs/specs/code-image-to-html/spec.yml

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { EmbedNodeAttributes } from '../../../../../message_parsing/types';
import GenericAppSkillEmbedPreview from '../../../../embeds/app_skill/GenericAppSkillEmbedPreview.svelte';
import InteractiveQuestionContainer from '../../../../interactive_questions/InteractiveQuestionContainer.svelte';
import { GroupRenderer } from '../GroupRenderer';

type MountCall = [unknown, { props: Record<string, unknown> }];

const svelteMountMocks = vi.hoisted(() => ({
  mount: vi.fn(() => ({ destroy: vi.fn() })),
  unmount: vi.fn(),
}));

const embedResolverMocks = vi.hoisted(() => ({
  resolveEmbed: vi.fn(),
  decodeToonContent: vi.fn(),
}));

const fullscreenControllerMocks = vi.hoisted(() => ({
  dispatchEmbedFullscreen: vi.fn(),
  resolveEmbedFullscreenTarget: vi.fn(),
}));

vi.mock('svelte', async (importOriginal) => {
  const actual = await importOriginal<typeof import('svelte')>();

  return {
    ...actual,
    mount: svelteMountMocks.mount,
    unmount: svelteMountMocks.unmount,
  };
});

vi.mock('../../../../../services/embedResolver', () => embedResolverMocks);

vi.mock('../../../../../services/embedFullscreenController', () => fullscreenControllerMocks);

vi.mock('../../../../../services/embedFullscreenResolver', () => ({
  hasFullscreenComponent: vi.fn(() => true),
  resolveRegistryKey: vi.fn((type: string) => type),
}));

describe('GroupRenderer', () => {
  beforeEach(() => {
    svelteMountMocks.mount.mockClear();
    svelteMountMocks.unmount.mockClear();
    fullscreenControllerMocks.dispatchEmbedFullscreen.mockClear();
    fullscreenControllerMocks.resolveEmbedFullscreenTarget.mockClear();
    embedResolverMocks.resolveEmbed.mockReset();
    embedResolverMocks.decodeToonContent.mockReset();
    embedResolverMocks.resolveEmbed.mockResolvedValue(null);
    embedResolverMocks.decodeToonContent.mockResolvedValue(null);

    Object.defineProperty(globalThis, 'CSS', {
      configurable: true,
      value: {
        escape: (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, '\\$&'),
      },
    });
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
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
    expect(
      content.querySelector('.embed-unified-container[data-embed-type="app-skill-use"]'),
    ).toBeNull();
    expect(content.textContent).not.toContain('Skill: code | image_to_html');
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('uses the input image thumbnail and opens the generated code child fullscreen', async () => {
    embedResolverMocks.resolveEmbed.mockImplementation(async (embedId: string) => {
      if (embedId === 'parent-skill') {
        return {
          embed_id: 'parent-skill',
          type: 'app_skill_use',
          status: 'finished',
          content: 'parent-content',
          embed_ids: ['generated-code'],
          createdAt: 1,
          updatedAt: 1,
        };
      }
      if (embedId === 'input-image') {
        return {
          embed_id: 'input-image',
          type: 'image',
          status: 'finished',
          content: 'input-image-content',
          createdAt: 1,
          updatedAt: 1,
        };
      }
      if (embedId === 'generated-code') {
        return {
          embed_id: 'generated-code',
          type: 'code',
          status: 'finished',
          content: 'code-content',
          createdAt: 1,
          updatedAt: 1,
        };
      }
      return null;
    });
    embedResolverMocks.decodeToonContent.mockImplementation(async (content: string) => {
      if (content === 'parent-content') {
        return {
          app_id: 'code',
          skill_id: 'image_to_html',
          status: 'finished',
          provider: 'Gemini',
          result_count: 1,
          input_embed_ids: 'input-image',
          output_embed_ids: 'generated-code',
          embed_ids: 'generated-code',
        };
      }
      if (content === 'input-image-content') {
        return { src: '/store-examples/screenshot-to-html-pricing-card.svg' };
      }
      if (content === 'code-content') {
        return { type: 'code', language: 'html', code: '<!DOCTYPE html>' };
      }
      return null;
    });

    const renderer = new GroupRenderer();
    const container = document.createElement('div');
    const content = document.createElement('div');
    container.appendChild(content);

    await renderer.render({
      attrs: {
        id: 'app-skill-group',
        type: 'app-skill-use-group',
        status: 'finished',
        contentRef: '',
        groupedItems: [
          {
            id: 'parent-skill',
            type: 'app-skill-use',
            status: 'finished',
            contentRef: 'embed:parent-skill',
            app_id: 'code',
            skill_id: 'image_to_html',
          },
        ],
        groupCount: 1,
      },
      container,
      content,
    });

    const genericCall = (svelteMountMocks.mount.mock.calls as unknown as MountCall[]).find(
      ([component]) => component === GenericAppSkillEmbedPreview,
    );
    expect(genericCall).toBeDefined();
    expect(genericCall?.[1]).toEqual(
      expect.objectContaining({
        props: expect.objectContaining({
          previewImageUrl: '/store-examples/screenshot-to-html-pricing-card.svg',
        }),
      }),
    );

    await (genericCall?.[1].props.onFullscreen as () => Promise<void>)();

    expect(fullscreenControllerMocks.dispatchEmbedFullscreen).toHaveBeenCalledWith(
      expect.objectContaining({
        embedId: 'generated-code',
        embedType: 'code-code',
        embedData: expect.objectContaining({ embed_id: 'generated-code' }),
        decodedContent: expect.objectContaining({ language: 'html' }),
        attrs: undefined,
      }),
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('renders historical interactive_question code embeds as interactive question cards', async () => {
    const renderer = new GroupRenderer();
    const container = document.createElement('div');
    const content = document.createElement('div');
    container.appendChild(content);
    const payload = {
      id: 'question-1',
      type: 'choice',
      question: 'Pick one',
      options: [{ id: 'a', text: 'A' }],
    };

    await renderer.render({
      attrs: {
        id: 'historical-question-embed',
        type: 'code-code',
        status: 'finished',
        contentRef: 'embed:historical-question-embed',
      },
      container,
      content,
      embedData: {
        embed_id: 'historical-question-embed',
        type: 'code-code',
        status: 'finished',
      },
      decodedContent: {
        language: 'interactive_question',
        filename: 'Code snippet',
        code: JSON.stringify(payload),
      },
    });

    expect(svelteMountMocks.mount).toHaveBeenCalledWith(
      InteractiveQuestionContainer,
      expect.objectContaining({
        props: expect.objectContaining({
          payload,
          chatId: '',
        }),
      }),
    );
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('renders read-mode interactive_question code fences as interactive question cards', async () => {
    const renderer = new GroupRenderer();
    const container = document.createElement('div');
    const content = document.createElement('div');
    container.appendChild(content);
    const payload = {
      id: 'question-2',
      type: 'choice',
      question: 'Pick one',
      options: [{ id: 'a', text: 'A' }],
    };

    await renderer.render({
      attrs: {
        id: 'read-mode-question-embed',
        type: 'code-code',
        status: 'finished',
        contentRef: 'stream:read-mode-question-embed',
        language: 'interactive_question',
        code: JSON.stringify(payload),
      },
      container,
      content,
    });

    expect(svelteMountMocks.mount).toHaveBeenCalledWith(
      InteractiveQuestionContainer,
      expect.objectContaining({
        props: expect.objectContaining({
          payload,
          chatId: '',
        }),
      }),
    );
  });
});
