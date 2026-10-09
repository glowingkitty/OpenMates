import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  awaitPersonalChatPredecessor, bindPersonalChatTurn, clearPersonalChatTurnBarriers,
  completePersonalChatTurn, failMatchingPersonalChatTurn, failPersonalChatTurn,
  reservePersonalChatTurn,
} from '../personalChatTurnBarrier';

afterEach(() => clearPersonalChatTurnBarriers());

describe('personal encrypted chat turn barrier', () => {
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it('reserves before optimistic writes and queues a rapid follow-up until matching canonical ACK', async () => {
    const first = reservePersonalChatTurn('chat-a', 'user-1');
    expect(await awaitPersonalChatPredecessor(first)).toBeNull();
    expect(reservePersonalChatTurn('chat-a', 'user-1')).toBe(first);
    const second = reservePersonalChatTurn('chat-a', 'user-2');
    const enteredPreflight = vi.fn();
    const queued = awaitPersonalChatPredecessor(second).then(enteredPreflight);
    bindPersonalChatTurn(first, 'turn-1');
    expect(completePersonalChatTurn('chat-a', 'other-turn', 2)).toBe(false);
    expect(completePersonalChatTurn('chat-b', 'turn-1', 2)).toBe(false);
    await Promise.resolve();
    expect(enteredPreflight).not.toHaveBeenCalled();
    // The committed version is the server's value, regardless of the optimistic
    // local message count or a concurrent unrelated remote update.
    expect(completePersonalChatTurn('chat-a', 'turn-1', 7)).toBe(true);
    await queued;
    expect(enteredPreflight).toHaveBeenCalledWith(7);
    expect(completePersonalChatTurn('chat-a', 'turn-1', 8)).toBe(false);
    bindPersonalChatTurn(second, 'turn-2');
    expect(completePersonalChatTurn('chat-a', 'turn-2', 9)).toBe(true);
    expect(await awaitPersonalChatPredecessor(reservePersonalChatTurn('chat-a', 'user-3'))).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it('unblocks with an error on rejected preflight and does not send a stale successor', async () => {
    const first = reservePersonalChatTurn('chat-a', 'user-1');
    const second = reservePersonalChatTurn('chat-a', 'user-2');
    const waiting = awaitPersonalChatPredecessor(second);
    failPersonalChatTurn(first, new Error('version_conflict'));
    await expect(waiting).rejects.toThrow('previous encrypted reply has not been saved');
    failPersonalChatTurn(second, new Error('not sent'));
    expect(await awaitPersonalChatPredecessor(reservePersonalChatTurn('chat-a', 'retry-3'))).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.recovery-takeover,chats.completion.lease-fenced
  it('accepts recovered terminal state only for its bound turn after local apply', async () => {
    const first = reservePersonalChatTurn('chat-recovered', 'user-1');
    const second = reservePersonalChatTurn('chat-recovered', 'user-2');
    bindPersonalChatTurn(first, 'recovered-turn');
    expect(failMatchingPersonalChatTurn('chat-recovered', 'stale-turn', new Error('stale'))).toBe(false);
    expect(completePersonalChatTurn('chat-recovered', 'recovered-turn', NaN)).toBe(false);
    expect(completePersonalChatTurn('chat-recovered', 'recovered-turn', 4)).toBe(true);
    await expect(awaitPersonalChatPredecessor(second)).resolves.toBe(4);
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.sync.key-gated-recovery
  it('releases queued dependents on connection loss without inventing a committed version', async () => {
    const first = reservePersonalChatTurn('chat-lost', 'user-1');
    const second = reservePersonalChatTurn('chat-lost', 'user-2');
    bindPersonalChatTurn(first, 'turn-1');
    const waiting = awaitPersonalChatPredecessor(second);
    clearPersonalChatTurnBarriers();
    await expect(waiting).rejects.toThrow('previous encrypted reply has not been saved');
    expect(completePersonalChatTurn('chat-lost', 'turn-1', 3)).toBe(false);
    expect(await awaitPersonalChatPredecessor(reservePersonalChatTurn('chat-lost', 'retry'))).toBeNull();
  });
});
