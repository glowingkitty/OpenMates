import { afterEach, describe, expect, it, vi } from 'vitest';
import { VisibleMessageReceipts } from '../visibleMessageReceipts';

afterEach(() => vi.useRealTimers());

describe('visible message receipts', () => {
  const scope = () => ({ ownerId: 'owner', chatId: 'chat', epoch: 1, connection: {} });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
  it('coalesces sixty concurrent visibility frames over four messages', async () => {
    const reporter = new VisibleMessageReceipts();
    const active = scope();
    const send = vi.fn(async () => {});
    await Promise.all(Array.from({ length: 60 }, () => Promise.all(
      ['one', 'two', 'three', 'four'].map(id => reporter.report(active, id, send)),
    )));
    expect(send).toHaveBeenCalledTimes(4);
    for (let frame = 0; frame < 60; frame++) {
      for (const id of ['one', 'two', 'three', 'four']) await reporter.report(active, id, send);
    }
    expect(send).toHaveBeenCalledTimes(4);
  });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
  it('retries failed sends and rechecks after the bounded interval', async () => {
    vi.useFakeTimers();
    const reporter = new VisibleMessageReceipts();
    const active = scope();
    const send = vi.fn().mockRejectedValueOnce(new Error('disconnected')).mockResolvedValue(undefined);
    expect(await reporter.report(active, 'one', send)).toBe(false);
    expect(await reporter.report(active, 'one', send)).toBe(true);
    expect(send).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(30_000);
    await reporter.report(active, 'one', send);
    expect(send).toHaveBeenCalledTimes(3);
  });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
  it.each(['ownerId', 'chatId', 'epoch', 'connection'] as const)('resets for a new %s', async field => {
    const reporter = new VisibleMessageReceipts();
    const active = scope();
    const send = vi.fn(async () => {});
    await reporter.report(active, 'one', send);
    const changed = { ...active, [field]: field === 'epoch' ? 2 : field === 'connection' ? {} : 'different' };
    await reporter.report(changed, 'one', send);
    expect(send).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
  it('does not reconnect for telemetry or let an old completion suppress a new connection', async () => {
    const reporter = new VisibleMessageReceipts();
    const active = scope();
    const send = vi.fn(async () => {});
    expect(await reporter.report({ ...active, connection: null }, 'one', send)).toBe(false);
    let finish!: () => void;
    const previous = reporter.report(active, 'one', () => new Promise(resolve => { finish = resolve; }));
    await Promise.resolve();
    const next = { ...active, connection: {} };
    await reporter.report(next, 'one', send);
    finish();
    await previous;
    await reporter.report(next, 'one', send);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
