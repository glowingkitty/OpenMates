import { randomUUID } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../stores/authState', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../stores/teamStore', async () => ({ activeTeamContext: (await import('svelte/store')).writable({ team: null, teamId: null as string | null, epoch: 0 }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'user-A' }) }));
vi.mock('../anonymousChatStorage', () => ({ anonymousChatStorage: { getAnonymousId: () => 'guest' } }));
vi.mock('../appsWorkspaceAttachmentService', () => ({ prepareAppsRequestAttachments: vi.fn(async () => ({ assets: { image: { type: 'image', format: 'jpg', data_base64: 'image-data' } }, attachments: [{ type: 'image', asset_ref: 'image', name: 'photo.png', mime_type: 'image/png' }] })) }));
vi.mock('../appsWorkspaceService', () => ({ executeAppsSkill: vi.fn(async () => ({ success: true, data: { results: [] } })), getAppsSkillDetails: vi.fn(async (app_id: string, skill_id: string) => ({ app_id, skill_id, input_schema: { type: 'object', properties: {} }, execution_available: true })) }));
vi.mock('../appsWorkspaceResultsService', () => ({ retainAppsResult: vi.fn(async () => 'result-id') }));
vi.mock('../../stores/personalDataStore', async () => {
  const { writable } = await import('svelte/store');
  return { personalDataStore: { settings: writable({ masterEnabled: true, categories: {} as Record<string, boolean> }),
    enabledEntries: writable([] as Array<{id:string; type:string; textToHide:string; replaceWith:string}>),
    waitForPrivacyMutations: vi.fn(async () => true) } };
});
vi.mock('../../stores/embedPIIStore', () => ({ getActivePIIMappingsForRewrite: vi.fn(() => []) }));
import { runAppsWorkspaceRequest } from '../appsWorkspaceRequestService';
import { executeAppsSkill, getAppsSkillDetails } from '../appsWorkspaceService';
import { retainAppsResult } from '../appsWorkspaceResultsService';
import { activeTeamContext } from '../../stores/teamStore';
import { userProfile } from '../../stores/userProfile';
import { personalDataStore } from '../../stores/personalDataStore';
import { prepareAppsRequestAttachments } from '../appsWorkspaceAttachmentService';
beforeEach(() => { vi.mocked(crypto.randomUUID).mockImplementation(() => randomUUID()); personalDataStore.enabledEntries.set([]); personalDataStore.settings.set({ masterEnabled: true, categories: {} }); vi.mocked(personalDataStore.waitForPrivacyMutations).mockResolvedValue(true); activeTeamContext.set({ team: null, teamId: null, epoch: 0 }); vi.clearAllMocks(); userProfile.update(profile => ({ ...profile, user_id: 'user-A' })); });
afterEach(() => vi.unstubAllGlobals());
describe('Apps natural requests', () => {
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('interprets then executes and retains the accepted skill, preserving the context', async () => {
    const context = { skill_id: 'search', input: { query: 'Berlin' }, embed_id: 'old', chat_id: 'chat', result: { results: [{ title: 'Cafe' }] } };
    const fetchMock = vi.fn(async (_url: string, _options: RequestInit) => Response.json({ action: 'execute', skill_id: 'search', input: { query: 'quiet cafes' } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(runAppsWorkspaceRequest({ appId: 'maps', text: 'quiet cafes', guest: false, requestId: 'req', context })).resolves.toMatchObject({ action: 'execute', embedId: 'result-id' });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({ context, request_id: 'req', app_id: 'maps' });
    expect(executeAppsSkill).toHaveBeenCalledWith('maps', 'search', { query: 'quiet cafes' }, expect.objectContaining({ guest: false }));
    expect(retainAppsResult).toHaveBeenCalledOnce();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it.each(['chat', 'workflow'] as const)('hands %s off without executing or creating an optimistic result', async action => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ action, reason: 'multiple steps' })));
    const handoff = vi.fn(async () => {});
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'help', guest: false, onChat: handoff, onWorkflow: handoff })).resolves.toMatchObject({ action });
    expect(handoff).toHaveBeenCalledWith(expect.objectContaining({ text: 'help' }));
    expect(executeAppsSkill).not.toHaveBeenCalled(); expect(retainAppsResult).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('preserves files through chat rather than dropping them during interpretation', async () => {
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    const attachments = [new File(['document'], 'notes.pdf', { type: 'application/pdf' })];
    const onChat = vi.fn(async () => {});
    await runAppsWorkspaceRequest({ appId: 'web', text: 'describe', guest: false, attachments, onChat });
    expect(onChat).toHaveBeenCalledWith(expect.objectContaining({ attachments })); expect(fetchMock).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('passes image decision assets for interpretation and executes only the accepted native route', async () => {
    const fetchMock = vi.fn(async (_url: string, _options: RequestInit) => Response.json({ action: 'execute', skill_id: 'search', input: { query: 'matching style' } }));
    vi.stubGlobal('fetch', fetchMock);
    await runAppsWorkspaceRequest({ appId: 'shopping', text: 'find this style', guest: false, attachments: [new File(['image'], 'photo.png', { type: 'image/png' })] });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toMatchObject({ assets: { image: { data_base64: 'image-data' } }, attachments: [{ type: 'image', asset_ref: 'image' }] });
    expect(executeAppsSkill).toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('preserves image files in chat when workflow text input cannot consume attachments', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ action: 'workflow' })));
    const onChat = vi.fn(async () => {}); const onWorkflow = vi.fn(async () => {});
    const attachments = [new File(['image'], 'photo.png', { type: 'image/png' })];
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'plan with this image', guest: false, attachments, onChat, onWorkflow })).resolves.toMatchObject({ action: 'chat' });
    expect(onChat).toHaveBeenCalledWith(expect.objectContaining({ attachments })); expect(onWorkflow).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('rejects a result arriving after account changes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { userProfile.update(profile => ({ ...profile, user_id: 'user-B' })); return Response.json({ action: 'execute', skill_id: 'search', input: {} }); }));
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'search', guest: false })).rejects.toThrow('account_context_changed');
    expect(executeAppsSkill).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('opens one retained processing result before an async execution finishes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ action: 'execute', skill_id: 'generate', input: { prompt: 'a song' } })));
    const accepted = vi.fn(async () => {});
    vi.mocked(executeAppsSkill).mockImplementationOnce(async (_app, _skill, _input, options) => {
      await options.onTaskSubmitted?.('task-1');
      expect(accepted).toHaveBeenCalledOnce();
      expect(retainAppsResult).toHaveBeenCalledWith(expect.objectContaining({ response: { task_id: 'task-1', status: 'processing' } }));
      return { success: true, data: { results: [] } };
    });
    await runAppsWorkspaceRequest({ appId: 'audio', text: 'a song', guest: false, onAccepted: accepted });
    expect(accepted).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ embedId: 'result-id', skillId: 'generate' }));
    expect(retainAppsResult).toHaveBeenCalledTimes(2);
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it.each(['execute', 'chat', 'workflow'] as const)('rejects deferred %s routing after leaving a Team, including switch-back', async action => {
    for (const switchBack of [false, true]) {
      vi.clearAllMocks(); activeTeamContext.set({ team: null, teamId: 'TeamA', epoch: 10 });
      let resolveResponse!: (value: Response) => void;
      vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { resolveResponse = resolve; })));
      const onChat = vi.fn(async () => {}); const onWorkflow = vi.fn(async () => {}); const onAccepted = vi.fn(async () => {});
      const request = runAppsWorkspaceRequest({ appId: 'web', text: 'private TeamA request', guest: false, teamId: 'TeamA', onChat, onWorkflow, onAccepted });
      await vi.waitFor(() => expect(resolveResponse).toBeTypeOf('function'));
      activeTeamContext.set({ team: null, teamId: null, epoch: 11 });
      if (switchBack) activeTeamContext.set({ team: null, teamId: 'TeamA', epoch: 12 });
      resolveResponse(Response.json({ action, skill_id: 'search', input: { query: 'private' } }));
      await expect(request).rejects.toThrow('team_context_changed');
      expect(onChat).not.toHaveBeenCalled(); expect(onWorkflow).not.toHaveBeenCalled(); expect(onAccepted).not.toHaveBeenCalled();
      expect(executeAppsSkill).not.toHaveBeenCalled(); expect(retainAppsResult).not.toHaveBeenCalled();
    }
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('rejects a mismatched explicit Team before interpretation', async () => {
    vi.stubGlobal('fetch', vi.fn());
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'search', guest: false, teamId: 'TeamA' })).rejects.toThrow('team_context_changed');
    expect(fetch).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('hands oversized prior result context to chat intact before interpretation or uploads', async () => {
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    const context = { result: { children: [{ description: 'private'.repeat(5000) }] } };
    const attachments = [new File(['image'], 'photo.png', { type: 'image/png' })];
    const onChat = vi.fn(async () => {});
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'compare these results', guest: false, context, attachments, onChat })).resolves.toMatchObject({ action: 'chat', reason: 'result_context_too_large' });
    expect(onChat).toHaveBeenCalledWith(expect.objectContaining({ context, attachments }));
    expect(fetchMock).not.toHaveBeenCalled(); expect(executeAppsSkill).not.toHaveBeenCalled(); expect(retainAppsResult).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('rejects malformed execute responses before dispatch', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ action: 'execute', skill_id: 'search', input: [] })));
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'search', guest: false })).rejects.toThrow('invalid_interpretation');
    expect(executeAppsSkill).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,pii.composer.detect-redact-exclude
  it('protects typed and nested result text with collision-safe local tokens, then restores native arguments', async () => {
    const context = { skill_id: 'search', embed_id: 'opaque-embed-id', chat_id: 'opaque-chat-id',
      input: { query: 'Email alice@example.com', aes_key: 'opaque-native-key', url: 'https://upload.invalid/audio?token=opaque-capability' },
      result: { children: [{ title: 'Contact bob@example.com', piiMappings: [{ placeholder: '[PRIVATE]', original: 'must-not-leave@example.com' }] }] } };
    let sent: Record<string, any> = {};
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      sent = JSON.parse(init.body as string);
      return Response.json({ action: 'execute', skill_id: 'search', input: { query: sent.text, previous: sent.context.input.query,
        result: sent.context.result.children[0].title, aes_key: sent.context.input.aes_key, url: sent.context.input.url } });
    }));
    await runAppsWorkspaceRequest({ appId: 'web', text: 'Find alice@example.com', guest: false, context });
    expect(JSON.stringify(sent)).not.toContain('alice@example.com'); expect(JSON.stringify(sent)).not.toContain('bob@example.com');
    expect(JSON.stringify(sent)).not.toContain('must-not-leave@example.com'); expect(JSON.stringify(sent)).not.toContain('piiMappings');
    expect(sent.context.embed_id).toBe('opaque-embed-id'); expect(sent.context.chat_id).toBe('opaque-chat-id');
    expect(sent.context.input.aes_key).toBe('opaque-native-key'); expect(sent.context.input.url).toBe(context.input.url);
    expect(sent.expected_user_id).toBe('user-A');
    expect(executeAppsSkill).toHaveBeenCalledWith('web', 'search', { query: 'Find alice@example.com', previous: 'Email alice@example.com',
      result: 'Contact bob@example.com', aes_key: 'opaque-native-key', url: context.input.url }, expect.anything());
    expect(context.result.children[0].piiMappings[0].original).toBe('must-not-leave@example.com');
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,pii.composer.detect-redact-exclude
  it.each([{ masterEnabled: false, categories: {} }, { masterEnabled: true, categories: { email_addresses: false } }])('honors existing master/category settings without inventing another detector', async settings => {
    personalDataStore.settings.set(settings);
    const fetchMock = vi.fn(async () => Response.json({ action: 'chat' })); vi.stubGlobal('fetch', fetchMock);
    await runAppsWorkspaceRequest({ appId: 'web', text: 'Find alice@example.com', guest: false, onChat: vi.fn(async () => {}) });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string).text).toBe('Find alice@example.com');
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,pii.composer.detect-redact-exclude
  it('honors configured personal entries and keeps original handoff text/context', async () => {
    personalDataStore.enabledEntries.set([{ id: 'private-name', type: 'name', textToHide: 'Alice Private', replaceWith: 'ME' }] as any);
    const fetchMock = vi.fn(async () => Response.json({ action: 'workflow' })); vi.stubGlobal('fetch', fetchMock);
    const onWorkflow = vi.fn(async () => {}); const context = { input: { query: 'Alice Private' } };
    await runAppsWorkspaceRequest({ appId: 'web', text: 'Research Alice Private daily', context, guest: false, onWorkflow });
    expect(fetchMock.mock.calls[0][1].body).not.toContain('Alice Private');
    expect(onWorkflow).toHaveBeenCalledWith(expect.objectContaining({ text: 'Research Alice Private daily', context }));
    expect(executeAppsSkill).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it.each(['abort', 'account'] as const)('does not transmit after %s during asynchronous privacy preparation', async change => {
    let ready!: () => void;
    vi.mocked(personalDataStore.waitForPrivacyMutations).mockImplementationOnce(() => new Promise<boolean>(resolve => { ready = () => resolve(true); }));
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock); const controller = new AbortController();
    const pending = runAppsWorkspaceRequest({ appId: 'web', text: 'alice@example.com', guest: false, signal: controller.signal });
    await vi.waitFor(() => expect(ready).toBeTypeOf('function'));
    if (change === 'abort') controller.abort(); else userProfile.update(profile => ({ ...profile, user_id: 'user-B' }));
    ready();
    await expect(pending).rejects.toThrow(change === 'abort' ? /abort/i : 'account_context_changed');
    expect(fetchMock).not.toHaveBeenCalled(); expect(executeAppsSkill).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('revalidates restored values against the native schema and rejects unknown tokens', async () => {
    vi.mocked(getAppsSkillDetails).mockResolvedValueOnce({ input_schema: { type: 'object', properties: { query: { type: 'string', maxLength: 8 } } } } as any);
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => Response.json({ action: 'execute', skill_id: 'search', input: { query: JSON.parse(init.body as string).text } })));
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'alice@example.com', guest: false })).rejects.toThrow('invalid_native_input');
    expect(executeAppsSkill).not.toHaveBeenCalled();
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ action: 'execute', skill_id: 'search', input: { query: '[OM_PII_00000000000000000000000000000000]' } })));
    await expect(runAppsWorkspaceRequest({ appId: 'web', text: 'museums', guest: false })).rejects.toThrow('pii_mapping_unavailable');
    expect(executeAppsSkill).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language,pii.composer.detect-redact-exclude
  it('protects result-ranking text while retaining original readable native result objects', async () => {
    const native = { success: true, data: { results: [{ title: 'alice@example.com', description: 'Contact bob@example.com' }, { title: 'Cafe' }] } };
    vi.mocked(executeAppsSkill).mockResolvedValueOnce(native);
    const fetchMock = vi.fn(async (url, init) => {
      if (String(url).endsWith('/rank')) {
        expect(init.body).not.toContain('alice@example.com'); expect(init.body).not.toContain('bob@example.com');
        expect(JSON.parse(init.body as string).expected_user_id).toBe('user-A');
        return Response.json({ ranked_ids: ['result-1', 'result-0'] });
      }
      return Response.json({ action: 'execute', skill_id: 'search', input: { query: 'cafes' } });
    }); vi.stubGlobal('fetch', fetchMock);
    await runAppsWorkspaceRequest({ appId: 'web', text: 'find alice@example.com', guest: false, attachments: [new File(['image'], 'photo.png', { type: 'image/png' })] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(vi.mocked(retainAppsResult).mock.calls[0][0].response)).toContain('alice@example.com');
  });
  // contract-test: direct surface=gui.web assertions=apps.requests.natural-language
  it('preserves exact native audio capabilities while withholding restoration maps from model-visible metadata', async () => {
    const input = { s3_key: 'opaque-upload', s3_base_url: 'https://upload.invalid', aes_key: 'exact-aes', aes_nonce: 'exact-nonce', vault_wrapped_aes_key: 'vault:v1:exact' };
    vi.mocked(prepareAppsRequestAttachments).mockResolvedValueOnce({ assets: {}, attachments: [{ type: 'audio', name: 'alice@example.com.wav', mime_type: 'audio/wav', input }] });
    let sent: any;
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => { sent = JSON.parse(init.body as string); return Response.json({ action: 'execute', skill_id: 'transcribe', input: { requests: [sent.attachments[0].input] } }); }));
    await runAppsWorkspaceRequest({ appId: 'audio', text: 'transcribe', guest: false, attachments: [new File(['audio'], 'alice@example.com.wav', { type: 'audio/wav' })] });
    expect(sent.attachments[0].name).not.toContain('alice@example.com'); expect(sent.attachments[0].input).toEqual(input);
    expect(executeAppsSkill).toHaveBeenCalledWith('audio', 'transcribe', { requests: [input] }, expect.anything());
  });

});
