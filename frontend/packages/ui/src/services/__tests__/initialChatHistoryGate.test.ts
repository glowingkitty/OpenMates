import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => null }));
vi.mock('../workspaceCacheLifecycle', () => ({ registerWorkspaceCacheClear: () => {} }));
import { InitialChatHistoryGate } from '../initialChatHistoryGate';

describe('owned initial chat history admission', () => {
  let scope: string | null;
  let gate: InitialChatHistoryGate;
  beforeEach(() => { scope = 'account:workspace:key-epoch1'; gate = new InitialChatHistoryGate(() => scope); });
  // contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
  it('does not defer cold-load or other-device histories', () => {
    expect(gate.defer('remote', vi.fn())).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
  it('keeps optimistic history local until exact durable initial ACK and repairs once', async () => {
    gate.register('chat', 'initial');
    const first = vi.fn(); const latest = vi.fn();
    expect(gate.defer('chat', first)).toBe(true);
    expect(gate.defer('chat', latest)).toBe(true);
    gate.bind('chat', 'initial', 'turn');
    expect(gate.acknowledge('chat', 'other', 'turn', scope)).toBe(false);
    expect(gate.acknowledge('chat', 'initial', 'other', scope)).toBe(false);
    expect(gate.acknowledge('chat', 'initial', 'turn', 'other-account')).toBe(false);
    expect(gate.pending('chat')).toBe(true); // failed/offline attempts grant no canonical state
    expect(gate.acknowledge('chat', 'initial', 'turn', scope)).toBe(true);
    expect(gate.acknowledge('chat', 'initial', 'turn', scope)).toBe(false);
    await Promise.resolve();
    expect(first).not.toHaveBeenCalled(); expect(latest).toHaveBeenCalledTimes(1);
    expect(gate.defer('chat', vi.fn())).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
  it('never replaces the initial identity with a follow-up or unrelated turn', () => {
    gate.register('chat', 'initial'); gate.register('chat', 'followup');
    gate.bind('chat', 'followup', 'bad'); gate.bind('chat', 'initial', 'turn');
    expect(gate.acknowledge('chat', 'followup', 'bad', scope)).toBe(false);
    expect(gate.acknowledge('chat', 'initial', 'turn', scope)).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
  it('permits an explicit same-initial-message retry while rejecting its obsolete ACK', () => {
    gate.register('chat', 'initial'); gate.bind('chat', 'initial', 'rejected-turn');
    expect(gate.pending('chat')).toBe(true);
    gate.bind('chat', 'initial', 'retry-turn');
    expect(gate.acknowledge('chat', 'initial', 'rejected-turn', scope)).toBe(false);
    expect(gate.acknowledge('chat', 'initial', 'retry-turn', scope)).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
  it('clears stale account/workspace/key ownership and cancels queued repair', async () => {
    const repair = vi.fn(); gate.register('chat', 'initial'); gate.bind('chat', 'initial', 'turn');
    gate.defer('chat', repair); gate.acknowledge('chat', 'initial', 'turn', scope);
    scope = 'account:workspace:key-epoch2'; await Promise.resolve(); expect(repair).not.toHaveBeenCalled();
    gate.register('chat2', 'initial'); scope = 'other-account'; expect(gate.pending('chat2')).toBe(false);
    scope = null; expect(gate.acknowledge('chat2', 'initial', 'turn', scope)).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
  it('explicit cache invalidation drops only its recoverable gate registry', () => {
    gate.register('chat', 'initial'); gate.clear(); expect(gate.pending('chat')).toBe(false);
  });
});
