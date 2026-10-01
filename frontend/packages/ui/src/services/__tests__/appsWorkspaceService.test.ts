import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppsSkillDetails } from '../../types/appsWorkspace';

vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.example.test${path}` }));
vi.mock('../anonymousChatStorage', () => ({ anonymousChatStorage: { getAnonymousId: () => 'guest-1' } }));
vi.mock('../../stores/authState', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true, isInitialized: true }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'user-A' }) }));

import { executeAppsSkill } from '../appsWorkspaceService';
import { authStore } from '../../stores/authState';
import { userProfile } from '../../stores/userProfile';

const metadata = {
  app_id: 'audio', skill_id: 'generate', slug: 'generate', name: 'Generate',
  name_translation_key: 'audio.generate', description: '', description_translation_key: '',
  icon_image: null, input_schema: { type: 'object' }, primary_fields: [], defaults: {},
  pricing: null, providers: [], models: [], anonymous_allowed: false,
  execution_available: true, unavailable_reason: null, execution_mode: 'async_job',
} satisfies AppsSkillDetails;

beforeEach(() => {
  userProfile.update(profile => ({ ...profile, user_id: 'user-A' }));
  authStore.set({ isAuthenticated: true, isInitialized: true });
});
afterEach(() => vi.unstubAllGlobals());

describe('direct Apps skill execution', () => {
  // contract-test: direct surface=gui.web assertions=apps.execution.direct-shared-contract,apps.results.web-retained-graph
  it('retains accepted task ID before polling and resumes without another POST after retention failure', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      requests.push(`${init?.method ?? 'GET'} ${url}`);
      if (url.endsWith('/v1/apps/audio/skills/generate')) return Response.json({ success: true, data: { task_id: 'job-1' } });
      if (url.endsWith('/v1/tasks/job-1')) return Response.json({ task_id: 'job-1', status: 'completed', result: { embed_id: 'embed-1' } });
      throw new Error(`Unexpected URL: ${url}`);
    }));
    const input = { prompt: 'A soft click' };
    await expect(executeAppsSkill('audio', 'generate', input, {
      guest: false, metadata, onTaskSubmitted: async () => { throw new Error('storage unavailable'); },
    })).rejects.toThrow('storage unavailable');
    const saved: string[] = [];
    const result = await executeAppsSkill('audio', 'generate', input, {
      guest: false, metadata, onTaskSubmitted: async taskId => { saved.push(taskId); },
    });
    expect(saved).toEqual(['job-1']);
    expect(result.data).toEqual({ embed_id: 'embed-1' });
    expect(requests.filter(request => request.startsWith('POST '))).toHaveLength(1);
  });

  // contract-test: direct surface=gui.web assertions=apps.execution.direct-shared-contract,apps.library.embeds-account-paginated
  it('does not share a pending response or retention callback across account switch', async () => {
    const requests: string[] = [];
    let releaseFirst: (response: Response) => void = () => {};
    const firstResponse = new Promise<Response>(resolve => { releaseFirst = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      requests.push(`${init?.method ?? 'GET'} ${url}`);
      if (requests.length === 1) return firstResponse;
      return Response.json({ success: true, data: { owner: 'user-B' } });
    }));
    const callbacks: string[] = [];
    const input = { prompt: 'same sound' };
    const first = executeAppsSkill('audio', 'generate', input, {
      guest: false, metadata, onTaskSubmitted: async () => { callbacks.push('user-A'); },
    });
    userProfile.update(profile => ({ ...profile, user_id: 'user-B' }));
    authStore.set({ isAuthenticated: true, isInitialized: true });
    const second = executeAppsSkill('audio', 'generate', input, { guest: false, metadata });
    releaseFirst(Response.json({ success: true, data: { task_id: 'job-A' } }));
    await expect(first).rejects.toThrow('account_context_changed');
    expect((await second).data).toEqual({ owner: 'user-B' });
    expect(callbacks).toEqual([]);
    expect(requests.filter(request => request.startsWith('POST '))).toHaveLength(2);
  });

  // contract-test: direct surface=gui.web assertions=apps.execution.direct-shared-contract
  it('keeps a pending request through an unchanged authentication refresh', async () => {
    let release: (response: Response) => void = () => {};
    const pendingResponse = new Promise<Response>(resolve => { release = resolve; });
    const fetchMock = vi.fn(async () => pendingResponse);
    vi.stubGlobal('fetch', fetchMock);
    const execution = executeAppsSkill('audio', 'generate', { prompt: 'steady' }, { guest: false, metadata });
    authStore.set({ isAuthenticated: true, isInitialized: true });
    release(Response.json({ success: true, data: { owner: 'user-A' } }));
    expect((await execution).data).toEqual({ owner: 'user-A' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
