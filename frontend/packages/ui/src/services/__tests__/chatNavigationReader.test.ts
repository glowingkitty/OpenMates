import { beforeEach, describe, expect, it, vi } from 'vitest';
import { chatNavigationReader } from '../chatNavigationReader';

const { getChat } = vi.hoisted(() => ({ getChat: vi.fn() }));
vi.mock('../db', () => ({ chatDB: { getChat } }));

describe('canonical navigation read', () => {
  beforeEach(() => { getChat.mockReset(); });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.fixed-binding
  it('preserves the pending canonical lookup until storage completes', async () => {
    let complete!: (value: null) => void;
    const canonicalRead = new Promise<null>(resolve => { complete = resolve; });
    getChat.mockReturnValue(canonicalRead);
    const navigationRead = chatNavigationReader.readChatForNavigation('fixture-chat');
    expect(navigationRead).not.toBe(canonicalRead);
    expect(getChat).toHaveBeenCalledExactlyOnceWith('fixture-chat');
    let settled = false;
    void navigationRead.then(() => { settled = true; });
    await Promise.resolve();
    expect(settled).toBe(false);
    complete(null);
    await expect(navigationRead).resolves.toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.fixed-binding
  it('allows initialization and the native read callback to complete before navigation settles', async () => {
    let finishInitialization!: () => void;
    const initialization = new Promise<void>(resolve => { finishInitialization = resolve; });
    let callbackCompleted = false;
    getChat.mockImplementation(async () => {
      await initialization;
      return new Promise<null>(resolve => {
        queueMicrotask(() => { callbackCompleted = true; resolve(null); });
      });
    });
    const navigationRead = chatNavigationReader.readChatForNavigation('fixture-chat');
    await Promise.resolve();
    expect(callbackCompleted).toBe(false);
    finishInitialization();
    await expect(navigationRead).resolves.toBeNull();
    expect(callbackCompleted).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.fixed-binding
  it('propagates canonical lookup failure without creating a navigation result', async () => {
    const error = new Error('Fictional decryption failure');
    getChat.mockRejectedValue(error);
    await expect(chatNavigationReader.readChatForNavigation('fixture-chat')).rejects.toBe(error);
  });
});
