import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, type Writable } from 'svelte/store';

const mocks = vi.hoisted(() => ({
  owner: 'account-a' as string | null,
  auth: null as unknown as Writable<{ isInitialized: boolean; isAuthenticated: boolean }>,
  profile: null as unknown as Writable<{ user_id: string | null }>,
  read: vi.fn(), decrypt: vi.fn(async (value: string) => value),
  encrypt: vi.fn(async (value: string) => value), save: vi.fn(),
  storageGet: vi.fn(), storageSet: vi.fn(),
  sync: vi.fn(async () => true), invalidators: [] as Array<() => void>,
}));
vi.mock('../../services/workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.owner }));
vi.mock('../../services/workspaceCacheLifecycle', () => ({ registerWorkspaceCacheClear: (fn: () => void) => mocks.invalidators.push(fn) }));
vi.mock('../authState', async () => {
  const { writable } = await import('svelte/store');
  mocks.auth = writable({ isInitialized: true, isAuthenticated: mocks.owner !== null });
  return { authStore: mocks.auth };
});
vi.mock('../userProfile', async () => {
  const { writable } = await import('svelte/store');
  mocks.profile = writable({ user_id: mocks.owner });
  return { userProfile: mocks.profile };
});
vi.mock('../../services/db', () => ({ chatDB: {
  getAppSettingsMemoriesEntriesByApp: mocks.read, storeAppSettingsMemoriesEntries: mocks.save,
} }));
vi.mock('../../services/cryptoService', () => ({
  decryptWithMasterKey: mocks.decrypt, encryptWithMasterKey: mocks.encrypt,
  getKeyFromStorage: vi.fn(async () => ({})),
}));
vi.mock('../../services/chatSyncService', () => ({ chatSyncService: { sendStoreAppSettingsMemoriesEntry: mocks.sync } }));
function row(data: Record<string, unknown>) {
  return { id: 'pii-settings', item_type: 'pii_detection_settings', item_key: 'hashed', item_version: 1,
    created_at: 1, encrypted_item_json: JSON.stringify(data) };
}

describe('enhanced personal-data preference hydration', () => {
  afterEach(() => { vi.unstubAllGlobals(); });
  beforeEach(() => {
    vi.resetModules(); vi.clearAllMocks(); mocks.invalidators.length = 0; mocks.owner = 'account-a';
    mocks.auth?.set({ isInitialized: true, isAuthenticated: true });
    mocks.profile?.set({ user_id: mocks.owner });
    mocks.decrypt.mockImplementation(async value => value);
    mocks.encrypt.mockImplementation(async value => value);
    mocks.save.mockReset().mockResolvedValue(undefined);
    mocks.sync.mockReset().mockResolvedValue(true);
    mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: false })]);
    mocks.storageGet.mockReturnValue(null);
    vi.stubGlobal("localStorage", { getItem: mocks.storageGet, setItem: mocks.storageSet });
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  it('keeps anonymous readiness stable through account sync and still reloads local opt-out', async () => {
    mocks.owner = null;
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.ensureEnhancementReady();
    const readiness: boolean[] = [];
    const stop = personalDataStore.enhancementReady.subscribe(value => readiness.push(value));
    window.dispatchEvent(new Event('appSettingsMemoriesSyncReady'));
    window.dispatchEvent(new Event('appSettingsMemoriesEntrySynced'));
    await Promise.resolve();
    expect(readiness).toEqual([true]);
    mocks.storageGet.mockReturnValue('false');
    await personalDataStore.loadFromStorage();
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(get(personalDataStore.enhancementReady)).toBe(true);
    stop();
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out
  it('holds readiness closed until the encrypted opt-out is decrypted and retains baseline settings', async () => {
    let finish!: (value: string) => void;
    mocks.decrypt.mockImplementationOnce(value => new Promise(resolve => { finish = () => resolve(value); }));
    const { personalDataStore } = await import('../personalDataStore');
    const load = personalDataStore.ensureEnhancementReady();
    await vi.waitFor(() => expect(mocks.decrypt).toHaveBeenCalled());
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    finish(''); await load;
    expect(get(personalDataStore.enhancementReady)).toBe(true);
    expect(get(personalDataStore.settings)).toMatchObject({ masterEnabled: true, enhancedEnabled: false,
      categories: { email_addresses: true, api_keys: true } });
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out
  it('defaults legacy encrypted preferences to enhanced on and persists opt-out in the encrypted singleton', async () => {
    mocks.read.mockResolvedValue([row({ masterEnabled: true, categories: { phone_numbers: false } })]);
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.ensureEnhancementReady();
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(true);
    await personalDataStore.setEnhancedEnabled(false);
    expect(JSON.parse(mocks.encrypt.mock.calls[0][0])).toMatchObject({
      masterEnabled: true, enhancedEnabled: false, categories: { phone_numbers: false },
    });
    expect(await personalDataStore.waitForPrivacyMutations()).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  it('does not interpret a cold account cache as permission to initialize before the first encrypted sync', async () => {
    mocks.read.mockResolvedValue([]);
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.ensureEnhancementReady();
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    window.dispatchEvent(new CustomEvent('appSettingsMemoriesSyncReady'));
    await personalDataStore.loadFromStorage();
    expect(get(personalDataStore.enhancementReady)).toBe(true);
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  it('fences the old owner during decryption and never publishes its readiness into another account', async () => {
    let finish!: () => void;
    mocks.decrypt.mockImplementationOnce(value => new Promise(resolve => { finish = () => resolve(value); }));
    const { personalDataStore } = await import('../personalDataStore');
    const load = personalDataStore.ensureEnhancementReady();
    await vi.waitFor(() => expect(mocks.decrypt).toHaveBeenCalled());
    mocks.owner = 'account-b'; mocks.profile.set({ user_id: 'account-b' });
    mocks.read.mockResolvedValue([]);
    finish(); await load;
    await personalDataStore.ensureEnhancementReady();
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  it('restarts an in-flight hydration for a remote opt-out and discards the older enabled result', async () => {
    mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: true })]);
    let finishOlderRead!: () => void;
    mocks.decrypt.mockImplementationOnce(value => new Promise(resolve => { finishOlderRead = () => resolve(value); }));
    const { personalDataStore } = await import('../personalDataStore');
    const oldLoad = personalDataStore.ensureEnhancementReady();
    await vi.waitFor(() => expect(mocks.decrypt).toHaveBeenCalled());
    mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: false })]);
    window.dispatchEvent(new CustomEvent('appSettingsMemoriesEntrySynced'));
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    await personalDataStore.loadFromStorage();
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(get(personalDataStore.enhancementReady)).toBe(true);
    finishOlderRead(); await oldLoad;
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(get(personalDataStore.enhancementReady)).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out
  it('can hydrate from inside an initializing mutator without waiting for its own mutation', async () => {
    mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: true })]);
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.setEnhancedEnabled(false);
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(await personalDataStore.waitForPrivacyMutations()).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  it('defers old sync authority until a held local opt-out write finishes, then reads the persisted opt-out', async () => {
    mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: true })]);
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.ensureEnhancementReady();
    let releaseWrite!: () => void;
    mocks.save.mockImplementationOnce(() => new Promise(resolve => { releaseWrite = () => {
      mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: false })]);
      resolve(undefined);
    }; }));
    const writing = personalDataStore.setEnhancedEnabled(false);
    await vi.waitFor(() => expect(mocks.save).toHaveBeenCalled());
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    const published: boolean[] = [];
    const stop = personalDataStore.settings.subscribe(settings => published.push(settings.enhancedEnabled));
    window.dispatchEvent(new CustomEvent('appSettingsMemoriesEntrySynced'));
    const refreshing = personalDataStore.loadFromStorage();
    await Promise.resolve(); await Promise.resolve();
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    releaseWrite(); await writing; await refreshing;
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(get(personalDataStore.enhancementReady)).toBe(true);
    expect(published).not.toContain(true);
    stop();
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  it('cannot bypass a pending opt-out through another initializing settings mutation', async () => {
    mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: true })]);
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.ensureEnhancementReady();
    let releaseWrite!: () => void;
    mocks.save.mockImplementationOnce(() => new Promise(resolve => { releaseWrite = () => resolve(undefined); }));
    const writing = personalDataStore.setEnhancedEnabled(false);
    await vi.waitFor(() => expect(mocks.save).toHaveBeenCalled());
    window.dispatchEvent(new CustomEvent('appSettingsMemoriesEntrySynced'));
    await expect(personalDataStore.toggleCategory('phone_numbers')).rejects.toThrow('not ready');
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    releaseWrite(); await writing;
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(get(personalDataStore.enhancementReady)).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out,pii.web.local-bounded-inference
  it('preserves optimistic opt-out with readiness closed when its held write fails and sync still contains enabled', async () => {
    mocks.read.mockResolvedValue([row({ masterEnabled: true, enhancedEnabled: true })]);
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.ensureEnhancementReady();
    let failWrite!: () => void;
    mocks.save.mockImplementationOnce(() => new Promise((_resolve, reject) => { failWrite = () => reject(new Error('storage unavailable')); }));
    const writing = personalDataStore.setEnhancedEnabled(false);
    const rejected = expect(writing).rejects.toThrow('storage unavailable');
    await vi.waitFor(() => expect(mocks.save).toHaveBeenCalled());
    const published: boolean[] = [];
    const stop = personalDataStore.settings.subscribe(settings => published.push(settings.enhancedEnabled));
    window.dispatchEvent(new CustomEvent('appSettingsMemoriesEntrySynced'));
    const refreshing = personalDataStore.loadFromStorage();
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    failWrite(); await rejected; await refreshing;
    await personalDataStore.loadFromStorage();
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    expect(get(personalDataStore.enhancementReady)).toBe(false);
    expect(published).not.toContain(true);
    stop();
  });

  // contract-test: direct surface=gui.web assertions=pii.web.enhanced-default-and-opt-out
  it('hydrates anonymous opt-out before readiness and persists further anonymous changes without account writes', async () => {
    mocks.owner = null;
    mocks.auth?.set({ isInitialized: true, isAuthenticated: false });
    mocks.profile?.set({ user_id: null });
    mocks.storageGet.mockReturnValue('false');
    const { personalDataStore } = await import('../personalDataStore');
    await personalDataStore.ensureEnhancementReady();
    expect(get(personalDataStore.enhancementReady)).toBe(true);
    expect(get(personalDataStore.settings).enhancedEnabled).toBe(false);
    await personalDataStore.setEnhancedEnabled(true);
    expect(localStorage.setItem).toHaveBeenCalledWith('openmates:anonymous:enhanced-pii', 'true');
    expect(mocks.encrypt).not.toHaveBeenCalled();
    expect(mocks.sync).not.toHaveBeenCalled();
  });
});
