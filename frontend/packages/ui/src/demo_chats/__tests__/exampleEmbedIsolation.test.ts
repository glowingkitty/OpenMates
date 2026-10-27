import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ALL_EXAMPLE_CHATS } from '../exampleChatData';
import { getExampleChatEmbed, resolveExampleFullscreenTarget } from '../exampleChatStore';
import { clearEmbedError, markEmbedAsError, resolveEmbed } from '../../services/embedResolver';
import { embedStore } from '../../services/embedStore';
import { chatDB } from '../../services/db';

// This namespace test supplies private rows directly; it does not initialize IndexedDB.
beforeEach(() => vi.spyOn(chatDB, 'getChat').mockResolvedValue(null));

afterEach(() => vi.restoreAllMocks());

describe('example embed namespace', () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('keeps child fullscreen and content scoped to the selected example group', async () => {
    const example = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === 'example-gigantic-airplanes')!;
    const parent = example.embeds.find((embed) => embed.embed_ids?.length)!;
    const childId = parent.embed_ids!.find((id) => example.embeds.some((embed) => embed.embed_id === id))!;
    expect(childId).toBeTruthy();
    const privateContent = 'E2E private source content';
    const privateRead = vi.spyOn(embedStore, 'get').mockResolvedValue({
      embed_id: childId, type: 'web_result', status: 'finished', content: privateContent,
    });
    try {
      expect(getExampleChatEmbed(childId, example.chat_id)).toBeTruthy();
      // A retained search result child has its own fullscreen and stays scoped
      // to this existing public example, even when a private UUID collides.
      expect(resolveExampleFullscreenTarget(childId, example.chat_id)).toEqual({ targetEmbedId: childId });
      expect(resolveExampleFullscreenTarget(childId, 'private-source-chat')).toBeNull();
      expect((await resolveEmbed(childId, { chatId: 'private-source-chat' }))?.content).toBe(privateContent);
      markEmbedAsError(childId, 'error');
      expect((await resolveEmbed(childId, { chatId: example.chat_id }))?.content)
        .toBe(getExampleChatEmbed(childId, example.chat_id)?.content);
      expect(privateRead).toHaveBeenCalledTimes(1);
    } finally {
      clearEmbedError(childId);
      privateRead.mockRestore();
    }
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('fails closed when a fixture ID is missing despite a cached private row', async () => {
    const example = ALL_EXAMPLE_CHATS.find((chat) => chat.chat_id === 'example-gigantic-airplanes')!;
    const missingId = '11111111-1111-4111-8111-111111111111';
    const privateRead = vi.spyOn(embedStore, 'get').mockResolvedValue({
      embed_id: missingId, type: 'app-skill-use', status: 'finished', content: 'private source',
    });
    expect(await resolveEmbed(missingId, { chatId: example.chat_id })).toBeNull();
    expect(privateRead).not.toHaveBeenCalled();
    expect((await resolveEmbed(missingId, { chatId: 'private-source-chat' }))?.content).toBe('private source');
  });
});
