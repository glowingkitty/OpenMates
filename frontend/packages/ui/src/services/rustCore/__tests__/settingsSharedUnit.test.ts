// contract-test-file: tooling
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
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
  rustBuildRequestMessage, rustConfirmOutcome, rustIsRequestAnswered, rustPlanRequestCategories, rustPlanSelectedKeys,
  rustPlanPrivacyEntry, rustResponseCategories, rustResponseContent, rustSelectEntryIds,
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
  settings_plan_selected_keys: (keys) => (calls.push(`keys ${keys}`), '[]'),
  settings_select_entry_ids: (ids, selection) => (calls.push(`select ${ids} ${selection}`), '["a"]'),
  settings_response_categories: (cats, released) => (calls.push(`cats ${cats} ${released}`), '[]'),
  settings_confirm_outcome: (count, voice, hasId) => (calls.push(`outcome ${count} ${voice} ${hasId}`), JSON.stringify({ kind: 'send' })),
  settings_response_content: (u, action, cats) => (calls.push(`content ${u} ${action} ${cats}`), `{"u":"${u}"}`),
  settings_plan_privacy_entry: (type, data, defaults) => (calls.push(`privacy ${type} ${data} ${defaults}`), JSON.stringify({ kind: 'other' })),
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
  it('serves the response decisions from the Rust binding', async () => {
    await expect(rustPlanSelectedKeys(['a-b'])).resolves.toEqual([]);
    await expect(rustSelectEntryIds(['a', 'b'], null)).resolves.toEqual(['a']);
    await expect(rustResponseCategories([{ appId: 'a', itemType: 'b' }], [])).resolves.toEqual([]);
    await expect(rustConfirmOutcome(2, true, false)).resolves.toEqual({ kind: 'send' });
    await expect(rustResponseContent('u1', 'rejected')).resolves.toBe('{"u":"u1"}');
    expect(calls).toEqual([
      'keys ["a-b"]', 'select ["a","b"] null', 'cats [{"appId":"a","itemType":"b"}] []', 'outcome 2 true false', 'content u1 rejected null',
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('serves the privacy entry plan from the Rust binding', async () => {
    await expect(rustPlanPrivacyEntry('location_settings', { impreciseByDefault: false }, { a: true })).resolves.toEqual({ kind: 'other' });
    expect(calls).toEqual(['privacy location_settings {"impreciseByDefault":false} {"a":true}']);
  });

  it('returns the Rust request message and rethrows its error text without fallback', async () => {
    const base = { userMessageId: 'u1', createdAt: 5, entryCounts: new Map<string, number | null>([['a-b', null]]), voice: true };
    await expect(rustBuildRequestMessage({ ...base, requestId: 'r1', requestedKeys: ['a-b'] }))
      .resolves.toEqual({ message_id: 'r1', role: 'system', content: '["a-b"]{"a-b":null}', created_at: 5, user_message_id: 'u1' });
    await expect(rustBuildRequestMessage({ ...base, requestId: '', requestedKeys: ['a-b'] }))
      .rejects.toThrow('Memory requests require stable request and user-message identities');
    expect(calls).toEqual(['build true', 'build true']);
  });
});
