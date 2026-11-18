import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  awaitPersonalChatPredecessor, bindPersonalChatTurn, clearPersonalChatTurnBarriers,
  completePersonalChatTurn, completePersonalChatMessage, failMatchingPersonalChatTurn, failPersonalChatTurn,
  reservePersonalChatTurn, observePersonalChatCanonicalVersion, hasRecoveryBoundPersonalChatMessage,
  markPersonalChatTurnLegacy, admitPersonalChatTurn, markPersonalChatReplyEnded, markPersonalChatReplyRunning,
} from '../personalChatTurnBarrier';

afterEach(() => clearPersonalChatTurnBarriers());

describe('personal encrypted chat turn barrier', () => {
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it('lets an epoch-zero LEGACY turn persist through legacy storage and settle its follow-up', async () => {
    const first = reservePersonalChatTurn('chat-legacy', 'user-1');
    bindPersonalChatTurn(first, 'turn-1');
    expect(hasRecoveryBoundPersonalChatMessage('chat-legacy', 'user-1')).toBe(true);
    // No sealed recovery job exists at epoch zero; the legacy ACK settles the turn.
    markPersonalChatTurnLegacy(first);
    expect(hasRecoveryBoundPersonalChatMessage('chat-legacy', 'user-1')).toBe(false);
    const followUp = reservePersonalChatTurn('chat-legacy', 'user-2');
    expect(completePersonalChatMessage('chat-legacy', 'user-1', 3)).toBe(true);
    expect(await awaitPersonalChatPredecessor(followUp)).toBe(3);
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it('reserves before optimistic writes and queues a rapid follow-up until matching canonical ACK', async () => {
    const first = reservePersonalChatTurn('chat-a', 'user-1');
    expect(await awaitPersonalChatPredecessor(first)).toBeNull();
    expect(reservePersonalChatTurn('chat-a', 'user-1')).toBe(first);
    const second = reservePersonalChatTurn('chat-a', 'user-2');
    const enteredPreflight = vi.fn();
    const queued = awaitPersonalChatPredecessor(second).then(enteredPreflight);
    expect(hasRecoveryBoundPersonalChatMessage('chat-a', 'user-1')).toBe(false);
    bindPersonalChatTurn(first, 'turn-1');
    expect(hasRecoveryBoundPersonalChatMessage('chat-a', 'user-1')).toBe(true);
    expect(hasRecoveryBoundPersonalChatMessage('other-chat', 'user-1')).toBe(false);
    expect(completePersonalChatTurn('chat-a', 'other-turn', 2)).toBe(false);
    expect(completePersonalChatTurn('chat-b', 'turn-1', 2)).toBe(false);
    await Promise.resolve();
    expect(enteredPreflight).not.toHaveBeenCalled();
    // The committed version is the server's value, regardless of the optimistic
    // local message count or a concurrent unrelated remote update.
    expect(completePersonalChatTurn('chat-a', 'turn-1', 7)).toBe(true);
    await queued;
    expect(enteredPreflight).toHaveBeenCalledWith(7);
    expect(hasRecoveryBoundPersonalChatMessage('chat-a', 'user-1')).toBe(false);
    expect(completePersonalChatTurn('chat-a', 'turn-1', 8)).toBe(false);
    bindPersonalChatTurn(second, 'turn-2');
    expect(completePersonalChatTurn('chat-a', 'turn-2', 9)).toBe(true);
    expect(await awaitPersonalChatPredecessor(reservePersonalChatTurn('chat-a', 'user-3'))).toBe(9);
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

// contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
it('retains a settled canonical receipt, advances remote versions, and clears on workspace reset', async () => {
  const first = reservePersonalChatTurn('settled-chat', 'first');
  bindPersonalChatTurn(first, 'first-turn');
  expect(completePersonalChatTurn('settled-chat', 'first-turn', 4)).toBe(true);
  observePersonalChatCanonicalVersion('settled-chat', 6);
  observePersonalChatCanonicalVersion('settled-chat', 3);
  const next = reservePersonalChatTurn('settled-chat', 'next');
  await expect(awaitPersonalChatPredecessor(next)).resolves.toBe(6);
  const { invalidateWorkspaceCaches } = await import('../workspaceCacheLifecycle');
  invalidateWorkspaceCaches();
  await expect(awaitPersonalChatPredecessor(reservePersonalChatTurn('settled-chat', 'fresh'))).resolves.toBeNull();
});

describe('legacy user message settlement', () => {
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it('settles only the exact reserved chat/user identity with a canonical integer version', async () => {
    const first = reservePersonalChatTurn('legacy-chat', 'user-1');
    bindPersonalChatTurn(first, 'real-turn');
    const second = reservePersonalChatTurn('legacy-chat', 'user-2');
    expect(completePersonalChatMessage('other-chat', 'user-1', 7)).toBe(false);
    expect(completePersonalChatMessage('legacy-chat', 'other-user', 7)).toBe(false);
    expect(completePersonalChatMessage('legacy-chat', 'user-1', NaN)).toBe(false);
    expect(completePersonalChatMessage('legacy-chat', 'user-1', -1)).toBe(false);
    expect(first.settled).toBe(false);
    expect(completePersonalChatMessage('legacy-chat', 'user-1', 7)).toBe(true);
    await expect(awaitPersonalChatPredecessor(second)).resolves.toBe(7);
    expect(completePersonalChatMessage('legacy-chat', 'user-1', 8)).toBe(false);
    expect(second.settled).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('resolves a follower at the predecessor admitted version without terminal persistence', async () => {
    const first = reservePersonalChatTurn('chat-q', 'user-1');
    bindPersonalChatTurn(first, 'turn-1');
    const second = reservePersonalChatTurn('chat-q', 'user-2');
    const third = reservePersonalChatTurn('chat-q', 'user-3');
    const entered = vi.fn();
    const secondWait = awaitPersonalChatPredecessor(second).then(entered);
    await Promise.resolve();
    expect(entered).not.toHaveBeenCalled(); // still preflighting: no admitted version yet
    admitPersonalChatTurn(first, 3);
    await secondWait;
    expect(entered).toHaveBeenCalledWith(3);
    // The follower's own admission advances the chain for the next follower.
    admitPersonalChatTurn(second, 4);
    expect(await awaitPersonalChatPredecessor(third)).toBe(4);
    expect(first.settled).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('rejects a follower when the predecessor fails before admission', async () => {
    const first = reservePersonalChatTurn('chat-r', 'user-1');
    const second = reservePersonalChatTurn('chat-r', 'user-2');
    const waiting = awaitPersonalChatPredecessor(second);
    failPersonalChatTurn(first, new Error('boom'));
    await expect(waiting).rejects.toThrow('has not been saved');
  });
});


// contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
it('reports ordinary sends before their journal exists, including an older turn after its newer tail fails',async()=>{
  const barrier=await import('../personalChatTurnBarrier');
  barrier.clearPersonalChatTurnBarriers();
  const first=barrier.reservePersonalChatTurn('cleanup-chat','first');
  const second=barrier.reservePersonalChatTurn('cleanup-chat','second');
  expect(barrier.hasPendingPersonalChatTurn('cleanup-chat')).toBe(true);
  expect(barrier.hasPendingPersonalChatTurn('other-chat')).toBe(false);
  barrier.failPersonalChatTurn(second,new Error('not sent'));
  expect(barrier.hasPendingPersonalChatTurn('cleanup-chat')).toBe(true);
  barrier.failPersonalChatTurn(first,new Error('not sent'));
  expect(barrier.hasPendingPersonalChatTurn('cleanup-chat')).toBe(false);
});

describe('queued follow-up behind an admitted turn', () => {
  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('uses the newest server version when another device queued a row after the admitted predecessor', async () => {
    const first = reservePersonalChatTurn('queue-chat', 'user-1');
    bindPersonalChatTurn(first, 'turn-1');
    const followUp = reservePersonalChatTurn('queue-chat', 'user-2');
    admitPersonalChatTurn(first, 5);
    // A CLI follow-up queued on another device committed its row at version 6.
    observePersonalChatCanonicalVersion('queue-chat', 6);
    await expect(awaitPersonalChatPredecessor(followUp)).resolves.toBe(6);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('keeps the admitted version when no newer server version was observed', async () => {
    const first = reservePersonalChatTurn('queue-chat-2', 'user-1');
    bindPersonalChatTurn(first, 'turn-1');
    const followUp = reservePersonalChatTurn('queue-chat-2', 'user-2');
    admitPersonalChatTurn(first, 5);
    await expect(awaitPersonalChatPredecessor(followUp)).resolves.toBe(5);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('waits for the stored reply once the predecessor run ended, so the server version is not stale', async () => {
    const first = reservePersonalChatTurn('ended-chat', 'user-1');
    bindPersonalChatTurn(first, 'turn-1');
    admitPersonalChatTurn(first, 5);
    // The reply finished streaming; its encrypted row is still being stored.
    markPersonalChatReplyEnded('ended-chat', 'user-1');
    const followUp = reservePersonalChatTurn('ended-chat', 'user-2');
    let resolved: number | null | undefined;
    const pending = awaitPersonalChatPredecessor(followUp).then((version) => { resolved = version; });
    await new Promise((tick) => setTimeout(tick, 0));
    expect(resolved).toBeUndefined();
    expect(completePersonalChatTurn('ended-chat', 'turn-1', 6)).toBe(true);
    await pending;
    expect(resolved).toBe(6);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('goes at once again when a focus continuation starts a new run before the reply is stored', async () => {
    const first = reservePersonalChatTurn('focus-chat', 'user-1');
    bindPersonalChatTurn(first, 'turn-1');
    admitPersonalChatTurn(first, 5);
    markPersonalChatReplyEnded('focus-chat', 'user-1');
    const followUp = reservePersonalChatTurn('focus-chat', 'user-2');
    const pending = awaitPersonalChatPredecessor(followUp);
    await new Promise((tick) => setTimeout(tick, 0));
    // The continuation task is running: the server queues the follow-up behind it.
    markPersonalChatReplyRunning('focus-chat');
    await expect(pending).resolves.toBe(5);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('does not wait for persistence while the predecessor reply is still running', async () => {
    const first = reservePersonalChatTurn('running-chat', 'user-1');
    bindPersonalChatTurn(first, 'turn-1');
    const followUp = reservePersonalChatTurn('running-chat', 'user-2');
    admitPersonalChatTurn(first, 5);
    await expect(awaitPersonalChatPredecessor(followUp)).resolves.toBe(5);
  });
});
