// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { observeOwnedTurnMetadata, type CliTurnMetadata } from '../src/ownedTurnMetadata.js';
import type { OpenMatesWsClient } from '../src/ws.js';

function fixture() {
  const handlers = new Map<string, Set<(frame: unknown) => void>>();
  let onClose: (() => void) | null = null;
  let current = true;
  const stored: CliTurnMetadata[] = [], shown: CliTurnMetadata[] = [];
  let released = 0;
  const ws = { isOpen: () => true, onMessageType(type: string, handler: (frame: unknown) => void) {
    if (!handlers.has(type)) handlers.set(type, new Set());
    handlers.get(type)!.add(handler);
    return () => { handlers.get(type)!.delete(handler); };
  }, onClose(handler: () => void) { onClose = handler; return () => { onClose = null; }; } } as unknown as OpenMatesWsClient;
  const observer = observeOwnedTurnMetadata({ ws, chatId: 'chat', turnId: 'turn', userMessageId: 'user',
    ownerCurrent: () => current, persist: async metadata => { stored.push(metadata); }, onMetadata: metadata => shown.push(metadata),
    onReleased: () => { released++; }, retentionMs: 25 });
  const emit = (type: string, frame: unknown) => { for (const handler of [...(handlers.get(type) ?? [])]) handler(frame); };
  const metadata = { chat_id: 'chat', turn_id: 'turn', user_message_id: 'user', source_metadata_v: 3,
    updated_chat_title: 'Late title', chat_summary: 'Late summary', follow_up_request_suggestions: ['Continue'] };
  return { observer, emit, metadata, stored, shown, count: () => [...handlers.values()].reduce((sum, set) => sum + set.size, 0),
    disconnect: () => onClose?.(), invalidate: () => { current = false; }, released: () => released };
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

// contract-test: supporting surface=cli assertions=chats.completion.independent-metadata
test('optional metadata queues until required persistence, then persists and renders independently with exact turn/version fences', async () => {
  const f = fixture();
  f.emit('post_processing_completed', { ...f.metadata, turn_id: 'different-turn' });
  f.emit('post_processing_completed', { ...f.metadata, user_message_id: 'different-user' });
  f.emit('post_processing_completed', { ...f.metadata, chat_id: 'different-chat' });
  assert.equal(f.stored.length, 0);
  f.emit('post_processing_completed', f.metadata);
  await tick(); assert.equal(f.stored.length, 0);
  f.observer.handOff('Suggested authored reply');
  await tick(); assert.equal(f.stored.length, 1); assert.equal(f.shown[0]?.chatSummary, 'Late summary');
  assert.equal(f.shown[0]?.suggestedFollowupMessage, 'Suggested authored reply');
  f.emit('post_processing_completed', { ...f.metadata, source_metadata_v: 2, updated_chat_title: 'Older title' });
  f.emit('post_processing_completed', f.metadata); await tick();
  assert.equal(f.stored.length, 1, 'older versions and duplicates cannot overwrite stored metadata');
  f.emit('post_processing_completed', { ...f.metadata, source_metadata_v: 4, updated_chat_title: 'Newer title' });
  await tick(); assert.equal(f.shown.at(-1)?.updatedChatTitle, 'Newer title');
  f.observer.stop(); assert.equal(f.count(), 0);
 });

// contract-test: supporting surface=cli assertions=chats.completion.independent-metadata
test('owned metadata subscriptions release on timeout, disconnect, cancellation and scope changes', async () => {
  for (const reason of ['timeout', 'disconnect', 'cancel', 'scope'] as const) {
    const f = fixture(); f.observer.handOff();
    if (reason === 'disconnect') f.disconnect();
    if (reason === 'cancel') f.observer.stop();
    if (reason === 'scope') { f.invalidate(); f.emit('post_processing_completed', f.metadata); }
    if (reason === 'timeout') await new Promise(resolve => setTimeout(resolve, 40));
    assert.equal(f.count(), 0, reason); assert.equal(f.released(), 1, reason);
    f.observer.stop(); assert.equal(f.released(), 1, 'release is idempotent');
  }
 });

// contract-test: supporting surface=cli assertions=chats.completion.independent-metadata
test('legacy chat-only metadata releases after required handoff without retaining an unusable socket or painting another turn', async () => {
  const f = fixture();
  f.emit('post_processing_completed', { chat_id: 'chat', updated_chat_title: 'Unfenced title' });
  assert.equal(f.released(), 0, 'required reply still owns the transport');
  assert.equal(f.observer.handOff(), true); await tick();
  assert.equal(f.released(), 1); assert.equal(f.count(), 0); assert.equal(f.shown.length, 0);
  assert.equal(f.observer.handOff(), false, 'stopped subscriptions cannot acquire transport ownership');
 });
