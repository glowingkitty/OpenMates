/**
 * Thin web glue for Memory privacy (decision D-5 of docs/plans/assistant-memory-writes):
 * released and written Memory bodies are anonymized by the Rust core with the
 * chat's placeholders. This module only gathers the chat's already stored
 * mappings and calls the core; no anonymization logic lives here. Mappings are
 * never logged.
 */
import { chatDB } from '../../db';
import { retainedPreparedPrivacyMemories } from '../../preparedPrivacyForSend';
import { rustWebCrypto } from '../crypto/webCryptoClient';
import { memoryAnonymize, type MemoryAnonymized } from '../crypto/memoryOps';
import { memoryResponseMappings } from './memoryResponseMappings';
import type { PIIMapping } from '../../../types/chat';

/** Cumulative mappings of the chat: user messages plus Memory responses. */
export async function chatPiiMappings(chatId: string): Promise<PIIMapping[]> {
  const byPlaceholder = new Map<string, PIIMapping>();
  for (const message of await chatDB.getMessagesForChat(chatId)) {
    const list = message.role === 'user' ? message.pii_mappings ?? []
      : message.role === 'system' ? memoryResponseMappings(message.content) : [];
    for (const mapping of list) byPlaceholder.set(mapping.placeholder, mapping);
  }
  return [...byPlaceholder.values()];
}

/** Anonymizes the `content` of released Memory entries in the core. */
export async function anonymizeMemoryEntries(chatId: string, entries: unknown[]): Promise<MemoryAnonymized> {
  const client = rustWebCrypto();
  if (!client) throw new Error('rust_core_unavailable');
  return memoryAnonymize(client, entries, retainedPreparedPrivacyMemories(), await chatPiiMappings(chatId));
}
