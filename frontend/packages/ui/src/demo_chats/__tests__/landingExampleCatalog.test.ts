// Public catalog curation and shared landing defaults.
// Quality takes priority over retaining an example for every capability.
// Internal renderer fixtures are deliberately excluded from public discovery.
// The test uses committed metadata only and makes no provider requests.
import { describe, expect, it } from 'vitest';
import { ALL_EXAMPLE_CHATS, INTERNAL_EXAMPLE_CHATS } from '../exampleChatData';
import landingDefaults from '../../generated/landingExampleChats.generated.json';
import { getExampleChatData, getExampleChatBySlug, getExampleChat, getExampleChatMessages, getExampleChatsForSkill } from '../exampleChatStore';
import { INTEREST_TAGS } from '../interestTags';
import expectations from './fixtures/curatedExampleExpectations.json';

const capabilityKeys = (chat: (typeof ALL_EXAMPLE_CHATS)[number]) => [
  ...(chat.metadata.app_skill_examples ?? []),
  ...(chat.metadata.app_focus_mode_examples ?? []),
];
const publicIds = new Set(ALL_EXAMPLE_CHATS.map(chat => chat.chat_id));
const landingIds = new Set([...landingDefaults.map(example => example.chatId), ...expectations.landingFeatureIds]);

describe('curated public example catalog', () => {
  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment
  it('retains every landing destination and retires redundant public entries', () => {
    expect(publicIds.size).toBe(ALL_EXAMPLE_CHATS.length);
    for (const id of landingIds) expect(publicIds.has(id), id).toBe(true);
    for (const example of expectations.retiredExamples) expect(publicIds.has(example.chatId), example.chatId).toBe(false);
    for (const example of expectations.retiredExamples) {
      expect(ALL_EXAMPLE_CHATS.find(chat => chat.slug === example.slug), example.slug).toBeUndefined();
      expect(INTEREST_TAGS.some(tag => tag.exampleChats.includes(example.chatId)), example.chatId).toBe(false);
    }
    for (const fixture of INTERNAL_EXAMPLE_CHATS) expect(publicIds.has(fixture.chat_id)).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment,public-example-chats.catalog.discoverable
  it('cannot load retired low-quality chats by ID or direct slug', () => {
    for (const example of [...expectations.qualityRetiredExamples, ...expectations.unsupportedProviderExamples]) {
      expect(getExampleChatData(example.chatId), example.chatId).toBeUndefined();
      expect(getExampleChat(example.chatId), example.chatId).toBeNull();
      expect(getExampleChatMessages(example.chatId), example.chatId).toEqual([]);
      expect(getExampleChatBySlug(example.slug), example.slug).toBeUndefined();
      expect(INTERNAL_EXAMPLE_CHATS.find(chat => chat.chat_id === example.chatId), example.chatId).toBeUndefined();
    }
  });
  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment,public-example-chats.catalog.discoverable
  it('does not expose unsupported examples through skill discovery or internal membership', () => {
    const retiredIds = new Set(expectations.unsupportedProviderExamples.map(example => example.chatId));
    for (const example of INTERNAL_EXAMPLE_CHATS) expect(retiredIds.has(example.chat_id)).toBe(false);
    for (const key of ['shopping.search_products', 'travel.search_connections', 'hosting.search_domains', 'jobs.search', 'health.search_appointments', 'home.search', 'models3d.search', 'electronics.search_components', 'videos.get_transcript', 'web.search']) {
      const [app, skill] = key.split('.');
      for (const chat of getExampleChatsForSkill(app, skill)) expect(retiredIds.has(chat.chat_id), chat.chat_id).toBe(false);
    }
    expect(getExampleChatsForSkill('web', 'search').some(chat => chat.chat_id === 'example-gigantic-airplanes')).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment
  it('keeps all surviving landing defaults in the approved order', () => {
    for (const id of expectations.qualityRetiredChildIds) {
      expect(getExampleChat(id), id).toBeNull();
      expect(getExampleChatMessages(id), id).toEqual([]);
    }
    expect(landingDefaults).toEqual(expectations.landingDefaults);
  });
  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment
  it('keeps extra examples only when they are the sole survivor for a capability', () => {
    const counts = new Map<string, number>();
    for (const chat of ALL_EXAMPLE_CHATS) {
      for (const key of new Set(capabilityKeys(chat))) counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    for (const chat of ALL_EXAMPLE_CHATS.filter(chat => !landingIds.has(chat.chat_id))) {
      expect(capabilityKeys(chat).some(key => counts.get(key) === 1), chat.chat_id).toBe(true);
    }
  });
});
