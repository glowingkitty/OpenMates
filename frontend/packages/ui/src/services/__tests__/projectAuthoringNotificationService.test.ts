import { describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ notify: vi.fn(), project: vi.fn(), contents: vi.fn() }));
vi.mock('../../stores/authStore', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'owner' }) }));
vi.mock('../../stores/notificationStore', () => ({ notificationStore: { addNotificationWithOptions: mocks.notify } }));
vi.mock('../../i18n/translations', async () => ({ text: (await import('svelte/store')).readable((key: string) => key) }));
vi.mock('../projectService', () => ({ getProject: mocks.project, getProjectContents: mocks.contents }));
import { handleProjectAuthoringReady, projectAuthoringResultHref, type ProjectAuthoringReadyEvent } from '../projectAuthoringNotificationService';

const event: ProjectAuthoringReadyEvent = { id: 'ready-test', type: 'project.authoring_ready',
  safe_body_key: 'notifications.project_authoring.ready', routing: { project_id: 'project', result_kind: 'focus', result_id: 'item', embed_id: 'embed', job_id: 'job' } };
describe('Project authoring ready notification', () => {
  // contract-test: supporting surface=gui.web assertions=notifications.project-authoring.result-route
  it('deduplicates safe ready events and links to the existing Project or Workflow workspace', () => {
    handleProjectAuthoringReady(event);
    handleProjectAuthoringReady(event);
    expect(mocks.notify).toHaveBeenCalledTimes(1);
    expect(mocks.notify).toHaveBeenCalledWith('success', expect.objectContaining({ message: 'notifications.project_authoring.ready', dedupeKey: event.id, onAction: expect.any(Function) }));
    expect(projectAuthoringResultHref(event)).toBe('/#project-id=project');
    expect(projectAuthoringResultHref({ ...event, routing: { ...event.routing, result_kind: 'workflow', result_id: 'workflow' } })).toBe('/#workflow-id=workflow&workflow-tab=details');
  });
  // contract-test: supporting surface=gui.web assertions=notifications.project-authoring.result-route
  it('rejects stale-owner and nonready payloads, and resolves access when opening', async () => {
    mocks.notify.mockClear();
    handleProjectAuthoringReady({ ...event, id: 'wrong-owner' }, 'other');
    handleProjectAuthoringReady({ ...event, id: 'pending', type: 'project.authoring_pending' });
    expect(mocks.notify).not.toHaveBeenCalled();
    mocks.project.mockRejectedValue(new Error('revoked'));
    handleProjectAuthoringReady({ ...event, id: 'revoked-ready' });
    const options = mocks.notify.mock.calls[0][1];
    options.onAction();
    await vi.waitFor(() => expect(mocks.notify).toHaveBeenCalledWith('info', expect.objectContaining({ message: 'notifications.project_authoring.unavailable' })));
    expect(mocks.contents).not.toHaveBeenCalled();
  });
});
