// Project summary/detail cache regression coverage.
// Fake API responses retain the encrypted transport structure.
// Only client decryption is stubbed here; browser coverage exercises real keys.
// Holds responses to establish mutation, deletion and identity fences.
// Cache values stay in memory and are discarded between test accounts.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

vi.mock('../../config/api', () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
  storageArchiveFetch: (input: RequestInfo | URL, init?: RequestInit) => fetch(input, init),
}));
vi.mock('../../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  return { userProfile: writable({ user_id: 'project-cache-test' }) };
});
vi.mock('../cryptoService', () => ({
  decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array(32)),
  decryptWithEmbedKey: vi.fn(async (value: string) => value.replace('sealed:', '')),
  encryptWithEmbedKey: vi.fn(async (value: string) => `sealed:${value}`),
  encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-key'),
  generateEmbedKey: vi.fn(() => new Uint8Array(32)),
  wrapEmbedKeyWithChatKey: vi.fn(async () => 'team-wrapped-key'), wrapEmbedKeyWithMasterKey: vi.fn(),
  unwrapEmbedKeyWithEmbedKey: vi.fn(async () => new Uint8Array(32)),
}));
vi.mock('../teamService', () => ({ getTeamKey: vi.fn(async () => new Uint8Array(32)) }));
vi.mock('../../message_parsing/utils', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../message_parsing/utils')>(),
  computeSHA256: vi.fn(async (value: string) => `hash:${value}`),
}));

import { createProject, decryptProject, getProject, listProjects, peekProjects, updateProjectMetadata, deleteProject } from '../projectService';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
import { setActiveTeamContext } from '../../stores/teamStore';
import { computeSHA256 } from '../../message_parsing/utils';
import { getTeamKey } from '../teamService';
import { unwrapEmbedKeyWithEmbedKey } from '../cryptoService';

function record(version = 1, name = 'Initial') {
  return { project_id: 'project-a', encrypted_project_key: 'wrapped-key',
    encrypted_name: `sealed:${name}`, encrypted_description: 'sealed:Description', encrypted_icon: 'sealed:folder',
    version, created_at: 1, updated_at: version, last_opened_at: 1 };
}
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((complete) => { resolve = complete; });
  return { promise, resolve };
}

describe('recent Project projections', () => {
  beforeEach(() => { vi.restoreAllMocks(); vi.stubGlobal('crypto', webcrypto); setActiveTeamContext(null); invalidateWorkspaceCaches(); });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,projects.lifecycle.encrypted-crud
  it('uses the active Team for list, key decryption, creation, and deletion', async () => {
    setActiveTeamContext({ team_id: 'team-a' } as Parameters<typeof setActiveTeamContext>[0]);
    vi.mocked(getTeamKey).mockResolvedValue(new Uint8Array(32));
    vi.mocked(unwrapEmbedKeyWithEmbedKey).mockResolvedValue(new Uint8Array(32));
    const teamRecord = { ...record(), key_wrappers: [{ key_type: 'team', hashed_team_id: await computeSHA256('team-a'), encrypted_project_key: 'team-wrapped-key' }] };
    const decryptedTeamRecord = await decryptProject(teamRecord, 'team-a');
    expect(unwrapEmbedKeyWithEmbedKey).toHaveBeenCalled();
    expect(decryptedTeamRecord?.teamId).toBe('team-a');
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ projects: [teamRecord] }))
      .mockResolvedValueOnce(Response.json({ project: record(1, 'Created') }))
      .mockResolvedValueOnce(Response.json({ deleted: true }));
    expect((await listProjects())[0].teamId).toBe('team-a');
    expect(String(fetchMock.mock.calls[0][0])).toContain('team_id=team-a');
    const created = await createProject('Created', 'always_ask');
    const createUrl = String(fetchMock.mock.calls[1][0]);
    const createBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(createUrl).toContain('team_id=team-a');
    expect(createBody.key_wrappers[0].hashed_team_id).toBe(await computeSHA256('team-a'));
    expect(created.teamId).toBe('team-a');
    await deleteProject(created.project_id, { teamId: created.teamId });
    expect(String(fetchMock.mock.calls[2][0])).toContain('team_id=team-a');
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it('discards a Personal list response after switching to a Team', async () => {
    const personal = deferred();
    const teamRecord = { ...record(1, 'Team'), key_wrappers: [{
      key_type: 'team', hashed_team_id: await computeSHA256('team-a'), encrypted_project_key: 'team-wrapped-key',
    }] };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => personal.promise)
      .mockResolvedValueOnce(Response.json({ projects: [teamRecord] }));
    const oldList = listProjects();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    setActiveTeamContext({ team_id: 'team-a' } as Parameters<typeof setActiveTeamContext>[0]);
    const newList = await listProjects();
    expect(newList.map((project) => project.name)).toEqual(['Team']);
    personal.resolve(Response.json({ projects: [record(1, 'Personal')] }));
    await expect(oldList).rejects.toThrow('superseded');
    expect(peekProjects()?.map((project) => project.name)).toEqual(['Team']);
  });

  // contract-test: supporting surface=gui.web assertions=projects.lifecycle.encrypted-crud
  it('shares list and entity data without fetching/decrypting on a fresh revisit', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ projects: [record()] }));
    const [first, concurrent] = await Promise.all([listProjects(), listProjects()]);
    expect(first).toBe(concurrent);
    expect(await listProjects()).toBe(first);
    expect((await getProject('project-a')).name).toBe('Initial');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=projects.lifecycle.encrypted-crud
  it('returns newer metadata when an older edit response arrives last', async () => {
    const older = deferred();
    const newer = deferred();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(Response.json({ projects: [record()] }));
    const project = (await listProjects())[0];
    fetchMock.mockImplementationOnce(() => older.promise).mockImplementationOnce(() => newer.promise);
    const oldEdit = updateProjectMetadata(project, { name: 'Older' });
    const newEdit = updateProjectMetadata(project, { name: 'Newer' });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    newer.resolve(Response.json({ project: record(3, 'Newer') }));
    expect((await newEdit).name).toBe('Newer');
    older.resolve(Response.json({ project: record(2, 'Older') }));
    expect((await oldEdit).name).toBe('Newer');
    expect(peekProjects()?.[0].name).toBe('Newer');
  });

  // contract-test: supporting surface=gui.web assertions=projects.lifecycle.encrypted-crud
  it('prevents a pending list response from restoring a deleted Project', async () => {
    const stale = deferred();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(Response.json({ projects: [record()] }));
    await listProjects();
    fetchMock.mockImplementationOnce(() => stale.promise).mockResolvedValueOnce(Response.json({ deleted: true }));
    const oldList = listProjects({ force: true });
    const rejection = expect(oldList).rejects.toThrow('superseded');
    await Promise.resolve();
    await deleteProject('project-a');
    stale.resolve(Response.json({ projects: [record()] }));
    await rejection;
    expect(peekProjects()).toEqual([]);
  });
});
