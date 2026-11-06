// TS-generated parity vectors for the shared Rust Apps skill execution policy.
// The committed JSON (packages/openmates-rust/src/web_apps_ts_vectors.json) holds
// inputs plus the outcomes of the existing TypeScript service
// (appsWorkspaceService.ts, flag off). This test fails if the TypeScript
// behaviour drifts from the vectors; the Rust unit tests (web_apps_tests.rs)
// replay the same file against web_apps.rs.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.example.test${path}` }));
vi.mock('../../anonymousChatStorage', () => ({ anonymousChatStorage: { getAnonymousId: () => 'guest-1' } }));
vi.mock('../../../stores/authState', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true, isInitialized: true }) }));
vi.mock('../../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'user-A' }) }));

import {
  acceptedTaskIds, errorDetail, executeAppsSkill, failedSkillResponse,
  getAnonymousAppsSkillAvailability, getAppsSkillDetails,
} from '../../appsWorkspaceService';
import { authStore } from '../../../stores/authState';
import type { AppsSkillDetails, AppsSkillResponse } from '../../../types/appsWorkspace';

type Scripted = { status: number; text: string };
const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_apps_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const ORIGIN = 'https://api.example.test';

function scriptedFetch(routes: Record<string, Scripted[]>, calls: string[]) {
  const queues = new Map(Object.entries(routes).map(([key, list]) => [key, [...list]]));
  return vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url.slice(ORIGIN.length)}`;
    calls.push(key);
    const next = queues.get(key)?.shift();
    if (!next) throw new Error(`unscripted ${key}`);
    return new Response(next.text, { status: next.status });
  });
}

async function settle<T>(promise: Promise<T>): Promise<{ ok: true; value: unknown } | { ok: false; message: string }> {
  let done = false;
  const outcome = promise.then(
    (value) => ({ ok: true as const, value: JSON.parse(JSON.stringify(value)) }),
    (error: Error) => ({ ok: false as const, message: error.message }),
  ).finally(() => { done = true; });
  for (let i = 0; i < 50 && !done; i++) await vi.advanceTimersByTimeAsync(2000);
  return outcome;
}

beforeEach(() => {
  vi.useFakeTimers();
  authStore.set({ isAuthenticated: true, isInitialized: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Apps skill execution parity vectors (TypeScript side)', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('error detail, skill failure and accepted task ids match the committed vectors', () => {
    for (const c of vectors.errorDetail) expect(errorDetail(c.body, c.status), JSON.stringify(c)).toBe(c.out);
    for (const c of vectors.errorDetailRaw) expect(errorDetail(JSON.parse(c.text), c.status)).toBe(c.out);
    for (const c of vectors.failure) {
      const out = failedSkillResponse(c.body as AppsSkillResponse);
      expect(out === null ? null : String(out), JSON.stringify(c)).toBe(c.out);
    }
    for (const c of vectors.taskIds) expect(acceptedTaskIds(c.envelope as AppsSkillResponse), JSON.stringify(c)).toEqual(c.out);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('skill details and anonymous quotes match the committed vectors', async () => {
    for (const c of vectors.details) {
      const fetchMock = vi.fn(async () => new Response(c.response.text, { status: c.response.status }));
      vi.stubGlobal('fetch', fetchMock);
      const signal = new AbortController().signal;
      expect(await settle(getAppsSkillDetails(c.app, c.skill, signal)), JSON.stringify(c)).toEqual(c.out);
      expect(fetchMock).toHaveBeenCalledWith(`${ORIGIN}${c.url}`, { credentials: c.credentials, signal });
    }
    for (const c of vectors.availability) {
      const calls: string[] = [];
      vi.stubGlobal('fetch', scriptedFetch({ [`POST ${c.url}`]: [c.response] }, calls));
      expect(await getAnonymousAppsSkillAvailability('web', 'search', { q: 1 }), JSON.stringify(c)).toEqual(c.out);
    }
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('direct execution, polling and resolution match the committed vectors', async () => {
    for (const c of vectors.execute) {
      authStore.set({ isAuthenticated: !c.guest, isInitialized: true });
      const calls: string[] = [];
      vi.stubGlobal('fetch', scriptedFetch(c.routes, calls));
      const run = executeAppsSkill(c.app, c.skill, { case: c.name }, {
        guest: c.guest, ...(c.teamId ? { teamId: c.teamId } : {}), metadata: c.metadata as AppsSkillDetails,
      });
      expect(await settle(run), c.name).toEqual(c.out);
      expect([...calls].sort(), c.name).toEqual(c.calls);
    }
  });
});
