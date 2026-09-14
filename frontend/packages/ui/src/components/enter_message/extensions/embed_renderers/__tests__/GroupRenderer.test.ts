// frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/__tests__/GroupRenderer.test.ts
// Unit coverage for grouped embed renderer fallbacks.
// These tests guard the public example/shared-chat rendering path without
// mounting real Svelte components, IndexedDB records, or network-backed embeds.
// Architecture: docs/specs/code-image-to-html/spec.yml

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { EmbedNodeAttributes } from '../../../../../message_parsing/types';
import GenericAppSkillEmbedPreview from '../../../../embeds/app_skill/GenericAppSkillEmbedPreview.svelte';
import WebsiteEmbedPreview from "../../../../embeds/web/WebsiteEmbedPreview.svelte";
import WebSearchEmbedPreview from '../../../../embeds/web/WebSearchEmbedPreview.svelte';
import InteractiveQuestionContainer from '../../../../interactive_questions/InteractiveQuestionContainer.svelte';
import EmbedsMapView from '../../../../embeds/EmbedsMapView.svelte';
import { GroupRenderer } from '../GroupRenderer';
import { disposeEmbedTree } from '../mountedEmbedLifecycle';

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
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('routes a saved results-view code embed through eligibility instead of a code card', async () => {
    const renderer = new GroupRenderer();
    const container = document.createElement('div');
    const content = document.createElement('div');
    container.append(content);
    await renderer.render({
      attrs: { id: 'legacy-results', type: 'code-code', status: 'finished', contentRef: 'embed:legacy-results' },
      container, content,
      embedData: { embed_id: 'legacy-results', type: 'code-code', status: 'finished' },
      decodedContent: { language: 'Embeds_results_view', code: 'title: News locations\nembeds:' },
    });
    expect(svelteMountMocks.mount).toHaveBeenCalledWith(EmbedsMapView, expect.objectContaining({
      props: expect.objectContaining({ title: 'News locations', embedRefs: [], sourceRefs: [] }),
    }));
    expect(svelteMountMocks.mount).toHaveBeenCalledTimes(1);
  });

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

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.surface.semantic-parity
  it('passes nested workflow news images and legacy aliases to the website card and fullscreen', async () => {
    const image = 'https://example.org/article.jpg';
    for (const imageFields of [
      { thumbnail: { original: image, src: 'https://example.org/small.jpg' } },
      { thumbnail: { src: image } },
      { thumbnail_src: image },
      { preview_image_url: image },
      { image_url: image },
    ]) {
      const renderer = new GroupRenderer();
      const open = vi.spyOn(renderer as unknown as { openFullscreen: (...args: unknown[]) => void }, 'openFullscreen').mockImplementation(() => {});
      const container = document.createElement('div');
      const content = document.createElement('div');
      container.append(content);
      await renderer.render({
        attrs: { id: 'workflow-news-result', type: 'web-website', status: 'finished', contentRef: 'embed:workflow-news-result' },
        container, content,
        decodedContent: { url: 'https://example.org/article', title: 'An article', description: 'Article summary', ...imageFields },
      });
      expect(svelteMountMocks.mount).toHaveBeenLastCalledWith(WebsiteEmbedPreview, expect.objectContaining({
        props: expect.objectContaining({ image, status: 'finished' }),
      }));
      const props = (svelteMountMocks.mount.mock.calls as unknown as MountCall[]).at(-1)![1].props;
      (props.onFullscreen as (metadata: Record<string, unknown>) => void)({});
      expect(open.mock.calls.at(-1)?.[2]).toEqual(expect.objectContaining({ image }));
    }
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.surface.semantic-parity
  it('keeps website fallback article images proxied and omits images for text-only results', async () => {
    for (const imageFields of [{ thumbnail: { src: 'https://example.org/article.jpg' } }, {}]) {
      const renderer = new GroupRenderer();
      const container = document.createElement('div');
      const content = document.createElement('div');
      container.append(content);
      svelteMountMocks.mount.mockImplementationOnce(() => { throw new Error('Test mount failure'); });
      await renderer.render({
        attrs: { id: 'fallback-news-result', type: 'web-website', status: 'finished', contentRef: 'embed:fallback-news-result' },
        container, content,
        decodedContent: { url: 'https://example.org/article', title: 'An article', ...imageFields },
      });
      const image = content.querySelector<HTMLImageElement>('img.og-image');
      if ('thumbnail' in imageFields) {
        expect(image).not.toBeNull();
        const source = new URL(image!.src);
        expect(source.pathname).toBe('/api/v1/image');
        expect(source.searchParams.get('url')).toBe(imageFields.thumbnail!.src);
      } else expect(image).toBeNull();
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('releases the current group observer and handlers when its message is disposed', () => {
    const observers: Array<{ observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }> = [];
    vi.stubGlobal('ResizeObserver', class {
      observe = vi.fn();
      disconnect = vi.fn();
      constructor() { observers.push(this); }
    });
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 42));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    const wrapper = document.createElement('div');
    const scroll = document.createElement('div');
    wrapper.append(scroll);
    for (let index = 0; index < 2; index += 1) {
      const card = document.createElement('div');
      card.className = 'embed-group-item';
      scroll.append(card);
    }
    document.body.append(wrapper);
    const removeListener = vi.spyOn(scroll, 'removeEventListener');
    try {
      const renderer = new GroupRenderer() as unknown as {
        syncGroupScrollIndicator: (wrapper: HTMLElement, scroll: HTMLElement) => void;
      };
      renderer.syncGroupScrollIndicator(wrapper, scroll);
      renderer.syncGroupScrollIndicator(wrapper, scroll);
      expect(observers).toHaveLength(2);
      expect(observers[0].disconnect).toHaveBeenCalledOnce();
      expect(observers[1].observe).toHaveBeenCalledTimes(3);
      expect(observers[1].disconnect).not.toHaveBeenCalled();
      disposeEmbedTree(wrapper);
      expect(observers[1].disconnect).toHaveBeenCalledOnce();
      expect(removeListener).toHaveBeenCalledWith('wheel', expect.any(Function));
      expect(removeListener).toHaveBeenCalledWith('scroll', expect.any(Function));
      expect(cancelAnimationFrame).toHaveBeenCalledWith(42);
      renderer.syncGroupScrollIndicator(wrapper, scroll);
      expect(observers).toHaveLength(2);
    } finally {
      wrapper.remove();
      vi.unstubAllGlobals();
    }
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

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity,chats.surface.semantic-parity
  it('mounts decoded web search parents as finished when cached group status is stale processing', async () => {
    embedResolverMocks.resolveEmbed.mockResolvedValue({
      embed_id: 'web-parent',
      type: 'app_skill_use',
      status: 'processing',
      content: 'web-parent-content',
      embed_ids: ['child-1', 'child-2'],
      createdAt: 1,
      updatedAt: 1,
    });
    embedResolverMocks.decodeToonContent.mockResolvedValue({
      app_id: 'web',
      skill_id: 'search',
      query: 'Berlin AI events',
      provider: 'Brave Search',
      embed_ids: 'child-1|child-2',
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
            id: 'web-parent',
            type: 'app-skill-use',
            status: 'processing',
            contentRef: 'embed:web-parent',
            app_id: 'web',
            skill_id: 'search',
          },
        ],
        groupCount: 1,
      },
      container,
      content,
    });

    expect(svelteMountMocks.mount).toHaveBeenCalledWith(
      WebSearchEmbedPreview,
      expect.objectContaining({
        props: expect.objectContaining({
          id: 'web-parent',
          query: 'Berlin AI events',
          provider: 'Brave Search',
          status: 'finished',
          resultCount: 2,
          childEmbedIds: ['child-1', 'child-2'],
        }),
      }),
    );
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
