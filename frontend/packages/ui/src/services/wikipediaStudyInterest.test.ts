// contract-test-file: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { wikipediaArticleIdentity } from '../utils/wikipediaLearning';

const mocks = vi.hoisted(() => ({ createEntry: vi.fn() }));
const state = writable({ decryptedEntries: new Map<string, { id: string; app_id: string; settings_group: string; item_value: Record<string, unknown> }>() });
const profile = writable({ user_id: 'test-owner' });
vi.mock('../stores/appSettingsMemoriesStore', () => ({ appSettingsMemoriesStore: { subscribe: (...args: Parameters<typeof state.subscribe>) => state.subscribe(...args), createEntry: mocks.createEntry } }));
vi.mock('../stores/userProfile', () => ({ userProfile: { subscribe: (...args: Parameters<typeof profile.subscribe>) => profile.subscribe(...args) } }));
import { findWikipediaStudyInterest, saveWikipediaStudyInterest } from './wikipediaStudyInterest';

describe('Wikipedia Study interests', () => {
  beforeEach(() => { state.set({ decryptedEntries: new Map() }); profile.set({ user_id: 'test-owner' }); mocks.createEntry.mockReset(); });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  it('uses the encrypted memory API once for concurrent saves and reuses the saved goal', async () => {
    const article = wikipediaArticleIdentity('Ada_Lovelace', 'en');
    mocks.createEntry.mockImplementation(async (app: string, data: { settings_group: string; item_value: Record<string, unknown> }) => {
      await Promise.resolve();
      state.set({ decryptedEntries: new Map([['saved', { id: 'saved', app_id: app, settings_group: data.settings_group, item_value: data.item_value }]]) });
    });
    expect(await Promise.all([saveWikipediaStudyInterest(article), saveWikipediaStudyInterest(article)])).toEqual(['saved', 'saved']);
    expect(await saveWikipediaStudyInterest(article)).toBe('saved');
    expect(mocks.createEntry).toHaveBeenCalledOnce();
    expect(mocks.createEntry.mock.calls[0][1].item_value).toEqual({ topic: 'Ada Lovelace', _wikipedia: article });
    expect(findWikipediaStudyInterest(wikipediaArticleIdentity('Ada_Lovelace', 'de'))).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  it('keeps disambiguated topics distinct and only reuses an exact legacy topic', () => {
    state.set({ decryptedEntries: new Map([['legacy', { id: 'legacy', app_id: 'study', settings_group: 'learning_goals', item_value: { topic: 'Mercury (planet)' } }]]) });
    expect(findWikipediaStudyInterest(wikipediaArticleIdentity('Mercury_(planet)', 'en'))).toBe('legacy');
    expect(findWikipediaStudyInterest(wikipediaArticleIdentity('Mercury_(element)', 'en'))).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  it('allows retry after a failed save and rejects saving without an account', async () => {
    mocks.createEntry.mockRejectedValue(new Error('Unavailable'));
    const article = wikipediaArticleIdentity('Ada_Lovelace', 'en');
    await expect(saveWikipediaStudyInterest(article)).rejects.toThrow('Unavailable');
    await expect(saveWikipediaStudyInterest(article)).rejects.toThrow('Unavailable');
    expect(mocks.createEntry).toHaveBeenCalledTimes(2);
    profile.set({ user_id: '' });
    await expect(saveWikipediaStudyInterest(article)).rejects.toThrow('Login required');
  });
});
