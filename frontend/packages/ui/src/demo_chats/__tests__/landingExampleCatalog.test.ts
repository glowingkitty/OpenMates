// Public catalog curation and shared landing defaults.
// These invariants preserve capability coverage while removing redundant chats.
// Internal renderer fixtures are deliberately excluded from public discovery.
// The test uses committed metadata only and makes no provider requests.
import { describe, expect, it } from 'vitest';
import { ALL_EXAMPLE_CHATS, INTERNAL_EXAMPLE_CHATS } from '../exampleChatData';
import landingDefaults from '../../generated/landingExampleChats.generated.json';
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
    for (const fixture of INTERNAL_EXAMPLE_CHATS) expect(publicIds.has(fixture.chat_id)).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=marketing-landing.example-catalog-alignment
  it('preserves a demonstration of every previously represented skill and focus mode', () => {
    const keys = new Set(ALL_EXAMPLE_CHATS.flatMap(capabilityKeys));
    for (const key of expectations.capabilityKeys) expect(keys.has(key), key).toBe(true);
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
