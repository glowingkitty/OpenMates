// `settings` unit of the shared Rust core Worker: the real router and installer
// over a scripted binding (the Rust decisions themselves are proven by
// web_settings_tests.rs over the TS-generated vectors) and the flag-on page
// adapter following those decisions with no TypeScript fallback.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installSettingsUnit } from '../settings/settingsUnit';
import { rustSettingsStats } from '../settings/settingsClient';
import {
  rustBuildRequestMessage, rustIsRequestAnswered, rustPlanRequestCategories,
} from '../settings/rustSettingsRequests';
import type { SettingsBinding } from '../settings/settingsProtocol';

const calls: string[] = [];
const binding: SettingsBinding = {
  settings_category_plan: (keys, counts) => (calls.push(`plan ${keys} ${counts}`), JSON.stringify({ categories: [], validKeys: JSON.parse(keys) })),
  settings_request_answered: (contents, id) => (calls.push(`answered ${contents} ${id}`), id === 'm1'),
  settings_build_request_message: (u, r, keys, at, counts, voice) => {
    calls.push(`build ${voice}`);
    if (!r) return JSON.stringify({ kind: 'error', message: 'Memory requests require stable request and user-message identities' });
    return JSON.stringify({ kind: 'ok', message: { message_id: r, role: 'system', content: keys + counts, created_at: JSON.parse(at), user_message_id: u } });
  },
};

function fakeWorker() {
  const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
  const router = createSharedWorkerRouter({
    installers: { settings: installSettingsUnit },
    loadBinding: async () => binding,
    reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); }),
  });
  const endpoint: SharedWorkerEndpoint = {
    postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
    addEventListener(type, listener) { listeners[type].push(listener); },
    terminate() {},
  };
  return endpoint;
}

let unregister: (() => void) | null = null;
beforeEach(() => {
  calls.length = 0;
  unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => { unregister?.(); });

describe('shared settings unit', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('refuses a binding without the settings exports', () => {
    const channel = new MessageChannel();
    expect(() => installSettingsUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
      .toThrow('unavailable');
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('serves the request decisions from the Rust binding', async () => {
    const before = rustSettingsStats.calls;
    await expect(rustPlanRequestCategories(['a-b'], new Map([['a-b', 2]]))).resolves.toEqual({ categories: [], validKeys: ['a-b'] });
    await expect(rustIsRequestAnswered(['{}'], 'm1')).resolves.toBe(true);
    await expect(rustIsRequestAnswered(['{}'], 'm2')).resolves.toBe(false);
    expect(calls).toContain('plan ["a-b"] {"a-b":2}');
    expect(rustSettingsStats.calls - before).toBe(3);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('returns the Rust request message and rethrows its error text without fallback', async () => {
    const base = { userMessageId: 'u1', createdAt: 5, entryCounts: new Map<string, number | null>([['a-b', null]]), voice: true };
    await expect(rustBuildRequestMessage({ ...base, requestId: 'r1', requestedKeys: ['a-b'] }))
      .resolves.toEqual({ message_id: 'r1', role: 'system', content: '["a-b"]{"a-b":null}', created_at: 5, user_message_id: 'u1' });
    await expect(rustBuildRequestMessage({ ...base, requestId: '', requestedKeys: ['a-b'] }))
      .rejects.toThrow('Memory requests require stable request and user-message identities');
    expect(calls).toEqual(['build true', 'build true']);
  });
});
