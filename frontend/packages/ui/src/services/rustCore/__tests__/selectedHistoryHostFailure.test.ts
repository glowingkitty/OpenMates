import { describe, expect, it, vi } from 'vitest';
import {
  isRecoverableSelectedHistoryFailure, readSelectedCacheAcrossDisconnect, RetiredSelectedHistoryHost,
} from '../selectedHistoryHostFailure';

function fixture(startOnline: boolean) {
  const links = new EventTarget();
  let online = startOnline;
  return {
    isOnline: () => online,
    listenOffline(callback: () => void) {
      links.addEventListener('offline', callback);
      return () => links.removeEventListener('offline', callback);
    },
    disconnect() {
      online = false;
      links.dispatchEvent(new Event('offline'));
    },
  };
}

describe('selected cache disconnect recovery', () => {
  // contract-test: supporting surface=gui.web assertions=sync.startup.opened-offline-and-archive
  it('cancels a held online cache read and finishes with two local rows', async () => {
    const link = fixture(true);
    const local = vi.fn(async () => ['row-one', 'row-two']);
    const online = vi.fn((signal: AbortSignal) => new Promise<string[]>((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true });
    }));
    const result = readSelectedCacheAcrossDisconnect(link, online, local);
    expect(online).toHaveBeenCalledOnce();
    expect(local).not.toHaveBeenCalled();
    link.disconnect();
    await expect(result).resolves.toEqual(['row-one', 'row-two']);
    expect(online).toHaveBeenCalledOnce();
    expect(local).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement
  it('never turns a real session denial into an offline cache read', async () => {
    const link = fixture(true);
    const local = vi.fn(async () => ['unpublishable']);
    const online = (signal: AbortSignal) => new Promise<string[]>((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('session_expired')), { once: true });
    });
    const result = readSelectedCacheAcrossDisconnect(link, online, local);
    link.disconnect();
    await expect(result).rejects.toThrow('session_expired');
    expect(local).not.toHaveBeenCalled();
    for (const reason of ['session_expired', 'authentication_failed', 'forbidden', 'invalidated_snapshot']) {
      expect(isRecoverableSelectedHistoryFailure(new Error(reason))).toBe(false);
    }
    expect(isRecoverableSelectedHistoryFailure(new RetiredSelectedHistoryHost())).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.opened-offline-and-archive
  it('when already disconnected, never enters the online request', async () => {
    const online = vi.fn();
    const local = vi.fn(async () => ['row-one', 'row-two']);
    await expect(readSelectedCacheAcrossDisconnect(fixture(false), online, local))
      .resolves.toEqual(['row-one', 'row-two']);
    expect(online).not.toHaveBeenCalled();
    expect(local).toHaveBeenCalledOnce();
  });
});
