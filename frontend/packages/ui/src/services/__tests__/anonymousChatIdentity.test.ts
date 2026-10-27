import { afterEach, describe, expect, it, vi } from 'vitest';
import { ANONYMOUS_ID_STORAGE, getAnonymousClientId } from '../anonymousChatIdentity';
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('lightweight anonymous client identity', () => {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('reuses the existing storage key and identity without rotating it', () => {
    const getItem = vi.fn(() => 'existing-client'); const setItem = vi.fn();
    vi.stubGlobal('localStorage', { getItem, setItem });
    expect(ANONYMOUS_ID_STORAGE).toBe('openmates_anonymous_id');
    expect(getAnonymousClientId()).toBe('existing-client');
    expect(getItem).toHaveBeenCalledWith('openmates_anonymous_id'); expect(setItem).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('creates and persists a UUID only when no client identity exists', () => {
    const uuid = '00000000-0000-4000-8000-000000000001';
    const setItem = vi.fn(); vi.stubGlobal('localStorage', { getItem: () => null, setItem });
    vi.spyOn(crypto, 'randomUUID').mockReturnValue(uuid);
    expect(getAnonymousClientId()).toBe(uuid);
    expect(setItem).toHaveBeenCalledWith('openmates_anonymous_id', uuid);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('preserves storage write exceptions instead of returning an unpersisted identity', () => {
    const failure = new DOMException('Storage full', 'QuotaExceededError');
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => { throw failure; } });
    expect(() => getAnonymousClientId()).toThrow(failure);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('preserves storage access exceptions instead of silently changing identity', () => {
    const failure = new DOMException('Storage unavailable', 'SecurityError');
    vi.stubGlobal('localStorage', { getItem: () => { throw failure; } });
    expect(() => getAnonymousClientId()).toThrow(failure);
  });
});
