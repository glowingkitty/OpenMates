import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const mocks = vi.hoisted(() => ({ focus: vi.fn(), project: vi.fn(), contents: vi.fn(), settings: vi.fn(),
  catalog: vi.fn(), selected: vi.fn(), save: vi.fn(), history: vi.fn(), revision: vi.fn(), encrypt: vi.fn() }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../stores/authStore', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'owner' }) }));
vi.mock('../db', () => ({ chatDB: { getMessage: vi.fn(async () => null), getMessageWindowForChat: mocks.history } }));
vi.mock('../projectService', () => ({ getActiveProjectFocus: mocks.focus, getProject: mocks.project,
  getProjectContents: mocks.contents, getProjectSettings: mocks.settings }));
vi.mock('../agenticProjectContextService', () => ({ collectProjectFocusCatalog: mocks.catalog,
  loadSelectedProjectFocusDocuments: mocks.selected, projectItemRevision: mocks.revision }));
vi.mock('../ruleDocumentService', () => ({ saveProjectMarkdownDocument: mocks.save }));
vi.mock('../cryptoService', () => ({ encryptWithEmbedKey: mocks.encrypt }));
vi.mock('../projectBrowserEvents', () => ({ broadcastProjectFilesChanged: vi.fn() }));
import { assessProjectAuthoring, startProjectAuthoring, saveProjectAuthoring, projectAuthoringJobs } from '../projectAuthoringClientService';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
import { authStore } from '../../stores/authStore';

const recommendation = { recommendation_id: 'proposal-1', chat_id: 'chat', project_id: 'project',
  kind: 'focus' as const, action: 'create' as const, target_id: null, expected_revision: null, expires_at: 9_999_999_999 };
const document = { name: 'Private focus', description: 'Service debugging', when_to_use: 'Debug services', instructions: 'private instruction', phases: [] };
const draft = { document, markdown: 'exact generated Markdown', path: '.openmates/focuses/logical/SKILL.md',
  save_operation_id: 'project-authoring:job', expected_embed_revision: 0 };
const initialJob = { ...recommendation, job_id: 'job', status: 'needs_save', draft };
async function flush() { for (let index = 0; index < 25; index++) await Promise.resolve(); }

describe('Project authoring client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    invalidateWorkspaceCaches();
    authStore.set({ isAuthenticated: true } as never);
    mocks.focus.mockResolvedValue({ project_id: 'project', team_id: null });
    mocks.project.mockResolvedValue({ project_id: 'project', projectKey: new Uint8Array(32) });
    mocks.contents.mockResolvedValue({ items: [], folders: [] });
    mocks.settings.mockResolvedValue({ writeMode: 'always_ask' });
    mocks.catalog.mockResolvedValue([]);
    mocks.selected.mockResolvedValue([]);
    mocks.history.mockResolvedValue({ messages: [{ role: 'user', content: 'Please debug', status: 'sent' },
      { role: 'assistant', content: 'This repeatable diagnostic process helps.', status: 'finished' }] });
    mocks.revision.mockResolvedValue('new-revision');
    mocks.encrypt.mockResolvedValue('private-ciphertext');
    mocks.save.mockResolvedValue({ project_item_id: 'actual-item', embed_id: 'embed', version_id: 1,
      file_operation_id: 'project-authoring:job', item_revision: 'new-revision' });
  });
  afterEach(() => { invalidateWorkspaceCaches(); vi.unstubAllGlobals(); });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click,workflows.project.update-authoring
  it('assesses metadata and loads only the selected existing Focus before an Update button', async () => {
    mocks.catalog.mockResolvedValue([{ kind: 'focus', id: 'selected', title: 'Debug', summary: 'Failure diagnosis', revision: 'base', when_to_use: 'private hint', display_path: 'private path' }]);
    mocks.selected.mockResolvedValue([{ id: 'selected', revision: 'base', document }]);
    const inspection = { ...recommendation, action: 'inspect', target_id: 'selected', expected_revision: 'base' };
    const fetchMock = vi.fn(async (url: string, _options?: RequestInit) => {
      if (url.endsWith('/v1/workflows')) return Response.json({ workflows: [] });
      if (url.endsWith('/recommend')) return Response.json({ recommendations: [inspection] });
      if (url.endsWith('/inspect')) return Response.json({ recommendation: { ...inspection, action: 'update' } });
      throw new Error('unexpected author call');
    });
    vi.stubGlobal('fetch', fetchMock);
    const receipts = await assessProjectAuthoring({ chat_id: 'chat', project_id: 'project', user_message_id: 'user-turn', assistant_message_id: 'response' });
    expect(receipts?.[0]).toMatchObject({ type: 'project_authoring_recommendation', action: 'update', event_id: 'proposal-1' });
    expect(mocks.selected).toHaveBeenCalledExactlyOnceWith('chat', 'project', ['selected']);
    const firstBody = JSON.parse(String(fetchMock.mock.calls.find(call => call[0].endsWith('/recommend'))?.[1]?.body));
    expect(firstBody.message_id).toBe('user-turn');
    expect(JSON.stringify(firstBody.catalog)).not.toContain('private instruction');
    expect(mocks.save).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.some(call => call[0].endsWith('/jobs'))).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click,projects.files.write-policy-enforcement
  it('starts only on click, displays the exact draft, and saves always-ask only after explicit Save', async () => {
    const fetchMock = vi.fn(async (url: string, _options?: RequestInit) => Response.json({ job: url.endsWith('/saved')
      ? { ...initialJob, status: 'ready', draft: undefined } : initialJob }));
    vi.stubGlobal('fetch', fetchMock);
    await startProjectAuthoring(recommendation);
    await flush();
    expect(get(projectAuthoringJobs).job.draft?.markdown).toBe(draft.markdown);
    expect(mocks.save).not.toHaveBeenCalled();
    const result = await saveProjectAuthoring('job');
    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ document: draft.markdown,
      operationId: draft.save_operation_id, expectedEmbedRevision: 0, saveApproved: true,
      metadata: { focus_title: document.name, focus_description: document.description, focus_when_to_use: document.when_to_use } }));
    const ack = fetchMock.mock.calls.find(call => call[0].endsWith('/saved'));
    expect(JSON.parse(String(ack?.[1]?.body))).toMatchObject({ project_item_id: 'actual-item', embed_id: 'embed', saved_revision: 'new-revision' });
    expect(result.status).toBe('ready');
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click,projects.files.write-policy-enforcement
  it('stops a save after Project activation changes and never acknowledges a failed save', async () => {
    const fetchMock = vi.fn(async (_url: string, _options?: RequestInit) => Response.json({ job: initialJob }));
    vi.stubGlobal('fetch', fetchMock);
    await startProjectAuthoring(recommendation);
    await flush();
    mocks.focus.mockResolvedValue({ project_id: 'other', team_id: null });
    await expect(saveProjectAuthoring('job')).rejects.toThrow('project_authoring_project_changed');
    expect(mocks.save).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/saved'))).toBe(false);
    mocks.focus.mockResolvedValue({ project_id: 'project', team_id: null });
    mocks.save.mockRejectedValue(new Error('atomic_save_conflict'));
    await expect(saveProjectAuthoring('job')).rejects.toThrow('atomic_save_conflict');
    expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/saved'))).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click
  it('keeps clarification visible without saving or creating an ordinary chat', async () => {
    const job = { ...initialJob, status: 'needs_input', draft: { question: 'Which diagnostic scope should be reusable?' } };
    const fetchMock = vi.fn(async (_url: string, _options?: RequestInit) => Response.json({ job }));
    vi.stubGlobal('fetch', fetchMock);
    await startProjectAuthoring(recommendation);
    await flush();
    expect(get(projectAuthoringJobs).job).toMatchObject({ status: 'needs_input', draft: { question: job.draft.question } });
    expect(mocks.save).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.every(call => String(call[0]).includes('/authoring/jobs'))).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=workflows.project.update-authoring,workflows.portability.remote-project-save
  it('acknowledges remote YAML only after encrypted binding metadata CAS has settled', async () => {
    const binding = { project_id: 'project', source_id: 'source', folder_path: '/work', file_path: '/work/job.workflow.yaml',
      base_hash: 'hash', saved_content: 'canonical YAML', workflow_version_id: 'version-2' };
    const item = { project_item_id: 'workflow-item', item_type: 'workflow', target_id: 'workflow', metadata: { remote_workflow_file: { ...binding, base_hash: 'old' } }, encrypted: {} };
    mocks.contents.mockImplementation(async () => ({ items: [item], folders: [] }));
    mocks.revision.mockImplementation(async () => item.metadata.remote_workflow_file.base_hash === 'old' ? 'base-item' : 'saved-item');
    const job = { ...initialJob, kind: 'workflow', action: 'update', target_id: 'workflow', result_id: 'workflow',
      project_item_id: item.project_item_id, expected_item_revision: 'base-item', workflow_version_id: 'version-2',
      status: 'needs_binding_save', draft: { remote_binding: binding } };
    const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === 'PATCH') {
        expect(JSON.parse(String(options.body))).toMatchObject({ encrypted_metadata: 'private-ciphertext', expected_item_revision: 'base-item' });
        item.metadata = { ...item.metadata, remote_workflow_file: binding, remote_file_status: 'saved' } as typeof item.metadata;
        return Response.json({});
      }
      if (url.endsWith('/workflow-saved')) {
        expect(item.metadata.remote_workflow_file.base_hash).toBe('hash');
        return Response.json({ job: { ...job, status: 'ready', draft: undefined } });
      }
      return Response.json({ job });
    });
    vi.stubGlobal('fetch', fetchMock);
    await startProjectAuthoring({ ...recommendation, kind: 'workflow', action: 'update', target_id: 'workflow', expected_revision: '1' });
    await flush();
    await vi.waitFor(() => expect(get(projectAuthoringJobs).job.status).toBe('ready'));
    expect(fetchMock.mock.calls.some(call => call[0].endsWith('/workflow-saved'))).toBe(true);
    expect(mocks.save).not.toHaveBeenCalled();
  });
});
