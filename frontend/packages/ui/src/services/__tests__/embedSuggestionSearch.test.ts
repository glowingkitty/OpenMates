import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Chat } from '../../types/chat';
import { searchSavedEmbedMemories } from '../embedSuggestionSearch';

const mocks = vi.hoisted(() => ({
  getMessagesForChat: vi.fn(),
  getDecryptedMetadata: vi.fn(),
  getEmbed: vi.fn(),
}));

vi.mock('../db', () => ({ chatDB: { getMessagesForChat: mocks.getMessagesForChat, getAllAppSettingsMemoriesEntries: async () => [] } }));
vi.mock('../chatMetadataCache', () => ({ chatMetadataCache: { getDecryptedMetadata: mocks.getDecryptedMetadata } }));
vi.mock('../embedStore', () => ({ embedStore: { get: mocks.getEmbed } }));
vi.mock('../embedResolver', () => ({
  extractEmbedReferences: (content: string) => content.includes('embed-ref')
    ? [{ embed_id: 'event-parent', type: 'app_skill_use' }]
    : [],
  decodeToonContent: async (content: string) => JSON.parse(content),
}));
vi.mock('../searchSettingsCatalog', () => ({ getSettingsSearchCatalog: () => [], getAppSearchCatalog: () => [] }));
vi.mock('../../data/appsMetadata', () => ({ appsMetadata: {} }));
vi.mock('../../demo_chats', () => ({
  getDemoMessages: () => [], isPublicChat: () => false, isExampleChat: () => false,
  getExampleChatEmbed: () => undefined,
  INTRO_CHATS: [], LEGAL_CHATS: [],
}));

describe('composer embed suggestions', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mocks.getDecryptedMetadata.mockResolvedValue({ title: 'Other chat', summary: null, tags: null, draftPreview: null });
  });

  // contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
  it('searches every saved embed memory regardless of date and deduplicates IDs', () => {
    const entriesByApp = new Map<string, Record<string, Array<{ id: string; item_value: Record<string, unknown>; updated_at: number }>>>([['events', {
      saved_events: [
        { id: 'old-memory', item_value: { embed_id: 'old-event', title: 'Berlin design meetup', location: 'Berlin' }, updated_at: 1 },
        { id: 'new-memory', item_value: { embed_id: 'old-event', title: 'Berlin design meetup', location: 'Berlin' }, updated_at: 2 },
        { id: 'other-memory', item_value: { embed_id: 'other-event', title: 'Munich meetup' }, updated_at: 3 },
      ],
    }], ['health', {
      appointments: [
        { id: 'appointment-memory', item_value: { embed_id: 'appointment', title: 'October 7', where: 'Dr. Ada · cardiology' }, updated_at: 4 },
      ],
    }]]);
    const state = { entriesByApp };
    expect(searchSavedEmbedMemories(state, 'berlin')).toEqual([expect.objectContaining({
      embedId: 'old-event', title: 'Berlin design meetup',
      settingsPath: 'apps/events/settings_memories/saved_events/entry/new-memory',
    })]);
    expect(searchSavedEmbedMemories(state, 'meetup')).toHaveLength(2);
    expect(searchSavedEmbedMemories(state, 'meetup', 1)).toHaveLength(1);
    expect(searchSavedEmbedMemories(state, 'cardiology')[0]?.embedId).toBe('appointment');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
  it('indexes all 50 local child titles once and returns an exact child result', async () => {
    const childIds = Array.from({ length: 50 }, (_, index) => `event-${index}`);
    mocks.getMessagesForChat.mockResolvedValue([{
      message_id: 'message-1', chat_id: 'chat-1', content: 'embed-ref', created_at: 100,
    }]);
    mocks.getEmbed.mockImplementation(async (ref: string) => {
      if (ref === 'embed:event-parent') return {
        type: 'app-skill-use', status: 'finished',
        content: JSON.stringify({ app_id: 'events', skill_id: 'search', query: 'Meetups', embed_ids: childIds.join('|') }),
      };
      const index = Number(ref.replace('embed:event-', ''));
      if (!Number.isInteger(index) || index < 0 || index >= 50) return null;
      return { type: 'events-event', status: 'finished', content: JSON.stringify({ title: `Distinct meetup ${index}`, venue_city: 'Berlin' }) };
    });
    const chat = {
      chat_id: 'chat-1', title: 'Other chat', created_at: 100,
      last_edited_overall_timestamp: 100,
    } as Chat;
    const { search, invalidateChatSearchIndex } = await import('../searchService');
    const result = await search('Distinct meetup 49', [chat], (key) => key, [], true, false, undefined, true);
    expect(result.embeds).toEqual([expect.objectContaining({ embedId: 'event-49', title: 'Distinct meetup 49', chatId: 'chat-1' })]);
    expect(mocks.getEmbed).toHaveBeenCalledTimes(51);

    const warmResult = await search('Distinct meetup 48', [chat], (key) => key, [], true, false, undefined, true);
    expect(warmResult.embeds[0]?.embedId).toBe('event-48');
    expect(mocks.getEmbed).toHaveBeenCalledTimes(51);

    invalidateChatSearchIndex('chat-1');
    await search('Distinct meetup 48', [chat], (key) => key, [], true, false, undefined, true);
    expect(mocks.getEmbed).toHaveBeenCalledTimes(102);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
  it('uses parent preview metadata to avoid decrypting later child results', async () => {
    const childIds = Array.from({ length: 50 }, (_, index) => `preview-event-${index}`);
    mocks.getMessagesForChat.mockResolvedValue([{
      message_id: 'message-2', chat_id: 'chat-2', content: 'embed-ref', created_at: 101,
    }]);
    mocks.getEmbed.mockImplementation(async (ref: string) => {
      if (ref === 'embed:event-parent') return {
        type: 'app-skill-use', status: 'finished',
        content: JSON.stringify({ app_id: 'events', skill_id: 'search', embed_ids: childIds.join('|'),
          preview_results: childIds.map((_, index) => ({ title: `Preview event ${index}` })) }),
      };
      return { type: 'events-event', status: 'finished', content: JSON.stringify({ title: 'Local event' }) };
    });
    const chat = { chat_id: 'chat-2', title: 'Other chat', created_at: 101,
      last_edited_overall_timestamp: 101 } as Chat;
    const { search } = await import('../searchService');
    const result = await search('Preview event 49', [chat], (key) => key, [], true, false, undefined, true);
    expect(result.embeds[0]?.embedId).toBe('preview-event-49');
    expect(mocks.getEmbed).toHaveBeenCalledTimes(11);
  });
});
