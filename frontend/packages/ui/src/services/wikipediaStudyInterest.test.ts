// contract-test-file: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { wikipediaArticleIdentity } from '../utils/wikipediaLearning';
import { parseRuleDocument } from '../utils/ruleDocuments';

const mocks = vi.hoisted(() => ({ saveRule: vi.fn(), publish: vi.fn() }));
const entries = { value: [] as Array<{ id: string; item_value: Record<string, unknown> }> };
const profile = writable({ user_id: 'test-owner' });
vi.mock('../stores/userProfile', () => ({ userProfile: { subscribe: (...args: Parameters<typeof profile.subscribe>) => profile.subscribe(...args) } }));
vi.mock('../stores/personalDocumentMemories', () => ({ currentPersonalDocumentMemories: () => entries.value }));
vi.mock('./ruleDocumentService', () => ({ savePersonalRuleDocument: mocks.saveRule, personalDocumentMemoryEntries: mocks.publish }));
import { findWikipediaStudyInterest, saveWikipediaStudyInterest } from './wikipediaStudyInterest';

describe('Wikipedia Study interests', () => {
  beforeEach(() => { entries.value = []; profile.set({ user_id: 'test-owner' }); mocks.saveRule.mockReset(); mocks.publish.mockReset(); });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  it('creates one ask-first personal Memory for concurrent saves and reuses it', async () => {
    const article = wikipediaArticleIdentity('Ada_Lovelace', 'en');
    mocks.saveRule.mockImplementation(async (input: { document: string }) => {
      await Promise.resolve();
      entries.value = [{ id: 'account-memory-saved', item_value: { document: input.document } }];
      return { id: 'personal:saved', source: 'personal', document: input.document };
    });
    expect(await Promise.all([saveWikipediaStudyInterest(article), saveWikipediaStudyInterest(article)])).toEqual(['account-memory-saved', 'account-memory-saved']);
    expect(await saveWikipediaStudyInterest(article)).toBe('account-memory-saved');
    expect(mocks.saveRule).toHaveBeenCalledOnce();
    const fields = parseRuleDocument(mocks.saveRule.mock.calls[0][0].document);
    expect(fields).toMatchObject({ title: 'Study interest: Ada Lovelace', load_mode: 'ask_first' });
    expect(fields.body).toContain(article.source_url);
    expect(findWikipediaStudyInterest(wikipediaArticleIdentity('Ada_Lovelace', 'de'))).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  it('keeps disambiguated topics distinct', async () => {
    const planet = wikipediaArticleIdentity('Mercury_(planet)', 'en');
    mocks.saveRule.mockImplementation(async (input: { document: string }) => {
      entries.value = [{ id: 'account-memory-planet', item_value: { document: input.document } }];
      return { id: 'personal:planet', source: 'personal', document: input.document };
    });
    await saveWikipediaStudyInterest(planet);
    expect(findWikipediaStudyInterest(planet)).toBe('account-memory-planet');
    expect(findWikipediaStudyInterest(wikipediaArticleIdentity('Mercury_(element)', 'en'))).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=wikipedia-mentions.learning.chat-and-memory
  it('allows retry after a failed save and rejects saving without an account', async () => {
    mocks.saveRule.mockRejectedValue(new Error('Unavailable'));
    const article = wikipediaArticleIdentity('Ada_Lovelace', 'en');
    await expect(saveWikipediaStudyInterest(article)).rejects.toThrow('Unavailable');
    await expect(saveWikipediaStudyInterest(article)).rejects.toThrow('Unavailable');
    expect(mocks.saveRule).toHaveBeenCalledTimes(2);
    profile.set({ user_id: '' });
    await expect(saveWikipediaStudyInterest(article)).rejects.toThrow('Login required');
  });
});
