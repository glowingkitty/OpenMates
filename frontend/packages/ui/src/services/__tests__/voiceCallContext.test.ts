import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({
  identity: 'owner-one' as string | null, projects: vi.fn(async () => []), active: vi.fn(async () => null as unknown),
  catalogue: vi.fn(async () => [{ project_id: 'project-one', name: 'Fictional Project', summary: 'Routing metadata' }]),
  documents: vi.fn(async () => [] as Array<{ id: string; revision: string; markdown: string }>),
  personal: vi.fn(async () => [] as unknown[]),
}));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.identity }));
vi.mock('../../config/api', () => ({ getWebSocketUrl: () => 'wss://fixture.invalid/v1/ws?client_capabilities=project_file_jobs' }));
vi.mock('../projectService', () => ({ listProjects: mocks.projects, getActiveProjectFocus: mocks.active }));
vi.mock('../agenticProjectContextService', () => ({ collectProjectFocusRoutingCandidates: mocks.catalogue,
  loadSelectedProjectFocusDocuments: mocks.documents }));
vi.mock('../ruleDocumentService', () => ({ personalDocumentMemoryEntries: mocks.personal }));
import { loadVoiceProjectContext } from '../voiceCallContext';

beforeEach(() => {
  vi.clearAllMocks(); mocks.identity = 'owner-one'; mocks.active.mockResolvedValue(null); mocks.personal.mockResolvedValue([]);
  mocks.documents.mockResolvedValue([]);
});
describe('voice owner-scoped Project context', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.privacy
  it('sends only discovery metadata before accepted Project access', async () => {
    const context = await loadVoiceProjectContext('chat-one');
    expect(context.project_focus_candidates).toEqual([{ project_id: 'project-one', name: 'Fictional Project', summary: 'Routing metadata' }]);
    expect(context.client_capabilities).toEqual(['project_file_jobs']);
    expect(context).not.toHaveProperty('project_focus_documents');
    expect(mocks.documents).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.privacy
  it('loads only the already-authorized active specialist through the shared document guard', async () => {
    mocks.active.mockResolvedValue({ project_id: 'project-one', specialist_focus_id: 'project-focus:project-one:focus-one' });
    mocks.documents.mockResolvedValue([{ id: 'focus-one', revision: 'revision-one', markdown: 'Authorized specialist guidance' }]);
    expect((await loadVoiceProjectContext('chat-one')).project_focus_documents).toEqual([
      { item_id: 'focus-one', revision: 'revision-one', document: 'Authorized specialist guidance' },
    ]);
    expect(mocks.documents).toHaveBeenCalledExactlyOnceWith('chat-one', 'project-one', ['focus-one']);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.privacy
  it('advertises personal memory availability without transmitting its private body', async () => {
    mocks.personal.mockResolvedValue([{ id: 'private-one', item_value: 'Fictional private memory' }]);
    const context = await loadVoiceProjectContext();
    expect(context.app_settings_memories_metadata).toEqual(['openmates-memories']);
    expect(JSON.stringify(context)).not.toContain('Fictional private memory');
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.project-context,video-call.privacy
  it('rejects metadata captured across an owner change', async () => {
    mocks.active.mockImplementationOnce(async () => { mocks.identity = 'another-owner'; return null; });
    await expect(loadVoiceProjectContext('chat-one')).rejects.toThrow('owner changed');
  });
});
