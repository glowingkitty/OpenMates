import { describe, expect, it, vi } from 'vitest';
import { OutboundMessageSends } from '../outboundMessageSends';

const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
};

describe('ordinary and journal recovery send ownership', () => {
  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent,message-input.send.ownership
  it('reserves before preparation and retains ownership after dispatch until context completion', async () => {
    const sends = new OutboundMessageSends();
    const preparation = deferred();
    const context = deferred();
    const send = vi.fn(async (hold) => { await preparation.promise; hold(context.promise); });
    const first = sends.run('account/socket', 'chat/message', 'immutable', send);
    const concurrent = sends.run('account/socket', 'chat/message', 'immutable', send);
    expect(concurrent).toBe(first);
    expect(send).toHaveBeenCalledOnce();
    preparation.resolve();
    await first;
    await sends.run('account/socket', 'chat/message', 'immutable', send);
    expect(send).toHaveBeenCalledOnce();
    context.resolve();
    await Promise.resolve();
    await sends.run('account/socket', 'chat/message', 'immutable', send);
    expect(send).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent,message-input.send.ownership
  it('rejects changed content while allowing independent messages and failed preparation retries', async () => {
    const sends = new OutboundMessageSends();
    const context = deferred();
    const send = vi.fn(async (hold) => hold(context.promise));
    await sends.run('owner/socket', 'message', 'original', send);
    await expect(sends.run('owner/socket', 'message', 'changed', send)).rejects.toThrow('immutable content');
    await sends.run('owner/socket', 'another-message', 'other', send);
    expect(send).toHaveBeenCalledTimes(2);
    const failed = vi.fn(async () => { throw new Error('preparation failed'); });
    await expect(sends.run('owner/socket', 'failed', 'same', failed)).rejects.toThrow('preparation failed');
    await sends.run('owner/socket', 'failed', 'same', send);
    expect(send).toHaveBeenCalledTimes(3);
    context.resolve();
  });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent,message-input.send.ownership
  it('accepts only the sender-validated canonical privacy/timestamp representation after preparation', async () => {
    const sends = new OutboundMessageSends();
    const preparation = deferred();
    const context = deferred();
    const send = vi.fn(async (hold) => {
      await preparation.promise;
      hold(context.promise, 'validated canonical representation');
    });
    const first = sends.run('owner/socket', 'message', 'original representation', send);
    const recovery = sends.run('owner/socket', 'message', 'validated canonical representation', send);
    const edit = sends.run('owner/socket', 'message', 'unrelated edit', send);
    const rejected = expect(edit).rejects.toThrow('immutable content');
    preparation.resolve();
    await Promise.all([first, recovery, rejected]);
    await sends.run('owner/socket', 'message', 'original representation', send);
    expect(send).toHaveBeenCalledOnce();
    context.resolve();
  });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent,teams.context.full-switch-local
  it.each(['account', 'Team epoch', 'socket'])('allows durable replay after %s replacement and fences stale completion', async () => {
    const sends = new OutboundMessageSends();
    const oldContext = deferred();
    const newContext = deferred();
    const oldSend = vi.fn(async (hold) => hold(oldContext.promise));
    const replay = vi.fn(async (hold) => hold(newContext.promise));
    await sends.run('old scope', 'chat/message', 'retained', oldSend);
    await sends.run('new scope', 'chat/message', 'retained', replay);
    oldContext.resolve();
    await Promise.resolve();
    await sends.run('new scope', 'chat/message', 'retained', replay);
    expect(replay).toHaveBeenCalledOnce();
    newContext.resolve();
  });
});
