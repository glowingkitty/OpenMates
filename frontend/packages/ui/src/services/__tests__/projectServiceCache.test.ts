// Project summary/detail cache regression coverage.
// Fake API responses retain the encrypted transport structure.
// Only client decryption is stubbed here; browser coverage exercises real keys.
// Holds responses to establish mutation, deletion and identity fences.
// Cache values stay in memory and are discarded between test accounts.
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
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
  wrapEmbedKeyWithChatKey: vi.fn(), wrapEmbedKeyWithMasterKey: vi.fn(), unwrapEmbedKeyWithEmbedKey: vi.fn(),
}));

import { getProject, listProjects, peekProjects, updateProjectMetadata, deleteProject } from '../projectService';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';

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
  beforeEach(() => { vi.restoreAllMocks(); invalidateWorkspaceCaches(); });

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
