// Background workspace admission and identity-switch regression.
// Service reads are stubbed to hold real promise boundaries deterministically.
// Browser tests cover the corresponding authenticated routes and encrypted data.
// Foreground reads never wait on this coordinator's background admission limit.
// Each test releases held work so no detached background job remains.
import { expect, it, vi } from 'vitest';

const calls = vi.hoisted(() => ({ workflows: vi.fn(), tasks: vi.fn(), plans: vi.fn(), projects: vi.fn() }));
vi.mock('../../stores/authStore', async () => {
  const { writable } = await import('svelte/store');
  return { authStore: writable({ isAuthenticated: true }) };
});
vi.mock('../../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  return { userProfile: writable({ user_id: 'prefetch-a' }) };
});
vi.mock('../../stores/appSkillsStore', async () => {
  const { writable } = await import('svelte/store');
  return { featureAvailabilityStore: writable({ disabledById: {} }) };
});
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../stores/workflowWorkspaceStore', () => ({ workflowWorkspaceStore: { loadWorkflows: calls.workflows } }));
vi.mock('../userTaskService', () => ({ listTaskBoardItems: calls.tasks }));
vi.mock('../userPlanService', () => ({ listUserPlans: calls.plans }));
vi.mock('../projectService', () => ({ listProjects: calls.projects }));

import { prefetchWorkspace, scheduleIdleWorkspacePrefetch } from '../workspacePrefetchService';
import { userProfile } from '../../stores/userProfile';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';

function hold() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => { release = resolve; });
  return { promise, release };
}

// contract-test: infrastructure
it('keeps a new identity prefetch queued behind two old jobs without dropping it', async () => {
  const workflow = hold();
  const project = hold();
  calls.workflows.mockImplementationOnce(() => workflow.promise).mockResolvedValue([]);
  calls.projects.mockImplementationOnce(() => project.promise).mockResolvedValue([]);
  calls.tasks.mockResolvedValue([]);
  calls.plans.mockResolvedValue([]);
  prefetchWorkspace('workflows');
  prefetchWorkspace('projects');
  expect(calls.workflows).toHaveBeenCalledTimes(1);
  expect(calls.projects).toHaveBeenCalledTimes(1);
  userProfile.update((profile) => ({ ...profile, user_id: 'prefetch-b' }));
  invalidateWorkspaceCaches();
  prefetchWorkspace('workflows');
  expect(calls.workflows).toHaveBeenCalledTimes(1);
  workflow.release();
  await vi.waitFor(() => expect(calls.workflows).toHaveBeenCalledTimes(2));
  project.release();
  await Promise.resolve();
});

// contract-test: infrastructure
it('keeps direct entity navigation free of idle full-workspace reads', () => {
  vi.clearAllMocks();
  invalidateWorkspaceCaches();
  let idleCallback: (() => void) | undefined;
  const location = { hash: '#task-id=selected-task', pathname: '/' };
  const requestIdleCallback = vi.fn((callback: () => void) => { idleCallback = callback; });
  vi.stubGlobal('window', { location, requestIdleCallback });
  try {
    scheduleIdleWorkspacePrefetch();
    expect(requestIdleCallback).not.toHaveBeenCalled();
    location.hash = '#chats';
    scheduleIdleWorkspacePrefetch();
    expect(requestIdleCallback).toHaveBeenCalledTimes(1);
    location.hash = '#plan-id=selected-plan';
    idleCallback!();
    for (const read of Object.values(calls)) expect(read).not.toHaveBeenCalled();
  } finally {
    vi.unstubAllGlobals();
    invalidateWorkspaceCaches();
  }
});
