import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ notify: vi.fn(), project: vi.fn(), contents: vi.fn() }));
vi.mock('../../stores/authStore', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'owner' }) }));
vi.mock('../../stores/notificationStore', () => ({ notificationStore: { addNotificationWithOptions: mocks.notify } }));
vi.mock('../../i18n/translations', async () => ({ text: (await import('svelte/store')).readable((key: string, options?: { values?: Record<string, string> }) => options?.values ? `${key}:${Object.values(options.values).join(',')}` : key) }));
vi.mock('../projectService', () => ({ getProject: mocks.project, getProjectContents: mocks.contents }));
import { REPLAY_WINDOW_MS, handleProjectAuthoringReady, projectAuthoringResultHref, type ProjectAuthoringReadyEvent } from '../projectAuthoringNotificationService';

const event: ProjectAuthoringReadyEvent = { id: 'ready-test', type: 'project.authoring_ready',
  safe_body_key: 'notifications.project_authoring.ready', routing: { project_id: 'project', result_kind: 'focus', result_id: 'item', embed_id: 'embed', job_id: 'job' } };
const storage = new Map<string, string>();
vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) });
const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
beforeEach(() => { mocks.notify.mockClear(); mocks.project.mockReset(); storage.clear(); mocks.project.mockResolvedValue({ name: 'Kitchen renovation' }); });

describe('Project authoring ready notification', () => {
  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it('deduplicates safe ready events, names the Project, and links to the existing Project or Workflow workspace', async () => {
    await handleProjectAuthoringReady(event);
    await handleProjectAuthoringReady(event);
    expect(mocks.notify).toHaveBeenCalledTimes(1);
    expect(mocks.notify).toHaveBeenCalledWith('success', expect.objectContaining({ message: 'notifications.project_authoring.ready_named:Kitchen renovation', dedupeKey: event.id, onAction: expect.any(Function) }));
    expect(projectAuthoringResultHref(event)).toBe('/#project-id=project');
    expect(projectAuthoringResultHref({ ...event, routing: { ...event.routing, result_kind: 'workflow', result_id: 'workflow' } })).toBe('/#workflow-id=workflow&workflow-tab=details');
  });
  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it('falls back to the generic text when the Project name cannot be read', async () => {
    mocks.project.mockRejectedValue(new Error('locked'));
    await handleProjectAuthoringReady({ ...event, id: 'unnamed' });
    expect(mocks.notify).toHaveBeenCalledWith('success', expect.objectContaining({ message: 'notifications.project_authoring.ready' }));
  });
  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it('replays a stored result only once, and only when it is recent', async () => {
    await handleProjectAuthoringReady({ ...event, id: 'old', created_at: minutesAgo(REPLAY_WINDOW_MS / 60_000 + 5) }, 'owner', 'backlog');
    await handleProjectAuthoringReady({ ...event, id: 'undated' }, 'owner', 'backlog');
    expect(mocks.notify).not.toHaveBeenCalled();
    await handleProjectAuthoringReady({ ...event, id: 'recent', created_at: minutesAgo(5) }, 'owner', 'backlog');
    expect(mocks.notify).toHaveBeenCalledTimes(1);
    // A reload starts with an empty in-memory set but keeps what this device already announced.
    vi.resetModules();
    const reloaded = await import('../projectAuthoringNotificationService');
    mocks.notify.mockClear();
    await reloaded.handleProjectAuthoringReady({ ...event, id: 'recent', created_at: minutesAgo(5) }, 'owner', 'backlog');
    expect(mocks.notify).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it('announces a live result even when its event id was not seen before', async () => {
    await handleProjectAuthoringReady({ ...event, id: 'live-now', created_at: minutesAgo(0) }, 'owner', 'live');
    expect(mocks.notify).toHaveBeenCalledTimes(1);
    // A stream that resends it after a reload does not announce it a second time.
    vi.resetModules();
    const reloaded = await import('../projectAuthoringNotificationService');
    mocks.notify.mockClear();
    await reloaded.handleProjectAuthoringReady({ ...event, id: 'live-now', created_at: minutesAgo(0) }, 'owner', 'live');
    expect(mocks.notify).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it('rejects stale-owner and nonready payloads, and resolves access when opening', async () => {
    await handleProjectAuthoringReady({ ...event, id: 'wrong-owner' }, 'other');
    await handleProjectAuthoringReady({ ...event, id: 'pending', type: 'project.authoring_pending' });
    expect(mocks.notify).not.toHaveBeenCalled();
    mocks.project.mockRejectedValue(new Error('revoked'));
    await handleProjectAuthoringReady({ ...event, id: 'revoked-ready' });
    const options = mocks.notify.mock.calls[0][1];
    options.onAction();
    await vi.waitFor(() => expect(mocks.notify).toHaveBeenCalledWith('info', expect.objectContaining({ message: 'notifications.project_authoring.unavailable' })));
    expect(mocks.contents).not.toHaveBeenCalled();
  });
});
