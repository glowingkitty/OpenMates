// Verify that fenced code previews produced by the write-mode parser become
// stored embed references in the composer node view. The persistence promise
// remains pending in this test so dispatch order is observable. Legacy code
// previews and unrelated preview types remain covered by the same path.
// This guards the reference sent with an encrypted Team chat message.

import { describe, expect, it, vi } from 'vitest';
import { parseEmbedNodes } from '../../../../message_parsing/embedParsing';

const { createCodeEmbed, createDocEmbed } = vi.hoisted(() => ({
  createCodeEmbed: vi.fn(),
  createDocEmbed: vi.fn(),
}));

vi.mock('../embed_renderers', () => ({
  embedRenderers: {},
  getEmbedRenderer: () => ({ render: () => undefined }),
}));
vi.mock('../embed_renderers/mountedEmbedLifecycle', () => ({
  disposeEmbedTree: vi.fn(),
  isEmbedTargetDisposed: () => false,
}));
vi.mock('../../../../message_parsing/groupHandlers', () => ({ groupHandlerRegistry: {} }));
vi.mock('../../embedHandlers', () => ({ cancelUpload: vi.fn(), deleteDraftEmbed: vi.fn() }));
vi.mock('../../services/codeEmbedService', () => ({ createCodeEmbed, createDocEmbed }));

import { Embed, waitForCodeDocPreviewUpgrades } from '../Embed';

function mountPreview(attrs: Record<string, unknown>) {
  let currentAttrs = attrs;
  const setNodeMarkup = vi.fn((
    _pos: number, _type: unknown, nextAttrs: Record<string, unknown>,
  ) => nextAttrs);
  const dispatch = vi.fn((nextAttrs: Record<string, unknown>) => {
    currentAttrs = nextAttrs;
  });
  const state = {
    doc: {
      nodeAt: () => ({ type: { name: 'embed' }, attrs: currentAttrs }),
      descendants: (visit: (node: { type: { name: string }; attrs: Record<string, unknown> }) => boolean) => {
        visit({ type: { name: 'embed' }, attrs: currentAttrs });
      },
    },
    tr: { setNodeMarkup },
  };
  const editor = { state, view: { state, dispatch } };
  const createNodeView = Embed.config.addNodeView!.call(Embed);
  createNodeView!({ node: { attrs }, getPos: () => 1, editor } as never);
  return { dispatch, setNodeMarkup, editor };
}

describe('Embed code preview upgrade', () => {
  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it('persists a real fenced-code preview before replacing its reference', async () => {
    const [fenced] = parseEmbedNodes('```text\n@OpenMates summarize\n```', 'write');
    expect(fenced.contentRef).toMatch(/^preview:code-code:/);

    let finishPersistence!: (value: { embed_id: string }) => void;
    createCodeEmbed.mockImplementationOnce(() => new Promise((resolve) => {
      finishPersistence = resolve;
    }));

    const { dispatch, setNodeMarkup, editor } = mountPreview(fenced);
    await vi.waitFor(() => expect(createCodeEmbed).toHaveBeenCalledWith(
      '@OpenMates summarize', 'text', undefined,
    ));
    expect(dispatch).not.toHaveBeenCalled();
    const readyToSend = waitForCodeDocPreviewUpgrades(editor as never);

    finishPersistence({ embed_id: 'stored-code-1' });
    await vi.waitFor(() => expect(dispatch).toHaveBeenCalledTimes(1));
    expect(await readyToSend).toBe(true);
    expect(setNodeMarkup.mock.calls[0][2].contentRef).toBe('embed:stored-code-1');
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it('keeps an unsuccessful document upgrade unsent with its preview draft intact', async () => {
    const [document] = parseEmbedNodes('```doc\nTeam notes\n```', 'write');
    expect(document.contentRef).toMatch(/^preview:docs-doc:/);
    createDocEmbed.mockRejectedValueOnce(new Error('local storage unavailable'));
    const { dispatch, editor } = mountPreview(document);

    expect(await waitForCodeDocPreviewUpgrades(editor as never)).toBe(false);
    expect(dispatch).not.toHaveBeenCalled();
    expect(editor.view.state.doc.nodeAt().attrs.contentRef).toBe(document.contentRef);
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it('keeps legacy code previews supported without upgrading other preview types', async () => {
    createCodeEmbed.mockResolvedValueOnce({ embed_id: 'stored-legacy-1' });
    const legacy = mountPreview({
      type: 'code-code', status: 'finished', contentRef: 'preview:code:old-1', code: 'legacy',
    });
    await vi.waitFor(() => expect(legacy.dispatch).toHaveBeenCalledTimes(1));
    expect(legacy.setNodeMarkup.mock.calls[0][2].contentRef).toBe('embed:stored-legacy-1');

    createCodeEmbed.mockClear();
    const unrelated = mountPreview({
      type: 'web-website', status: 'finished', contentRef: 'preview:web-website:site-1', code: 'url',
    });
    await Promise.resolve();
    expect(createCodeEmbed).not.toHaveBeenCalled();
    expect(unrelated.dispatch).not.toHaveBeenCalled();
  });
});
