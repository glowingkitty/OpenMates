import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  scope: 'account-a:team-epoch-1',
  projects: vi.fn(async () => []),
  memoryKeys: vi.fn(async () => []),
  tasks: vi.fn(async () => []),
}));
vi.mock('../projectService', () => ({ listProjects: mocks.projects }));
vi.mock('../db', () => ({ chatDB: { getAppSettingsMemoriesMetadataKeys: mocks.memoryKeys } }));
vi.mock('../userTaskService', () => ({ listUserTasks: mocks.tasks }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.scope }));
import { prefetchChatMetadata } from '../chatMetadataWarmup';

describe('metadata preparation before Send', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  // contract-test: supporting surface=gui.web assertions=workflows.chat.metadata-warmup
  it('prepares exact inventory queries without sending a draft or reading selected bodies', async () => {
    await prefetchChatMetadata({ scope: mocks.scope, teamId: 'team-a', chatId: 'chat-a' });
    expect(mocks.memoryKeys).toHaveBeenCalledOnce();
    expect(mocks.projects).toHaveBeenCalledExactlyOnceWith({ teamId: 'team-a' });
    expect(mocks.tasks.mock.calls).toEqual([[{ teamId: 'team-a' }], [{ teamId: 'team-a', chatId: 'chat-a' }]]);
  });

  // contract-test: supporting surface=gui.web assertions=workflows.chat.metadata-warmup
  it('discards preparation admitted for an old account or Team epoch', async () => {
    await prefetchChatMetadata({ scope: 'account-a:team-epoch-0', teamId: 'team-a', chatId: 'chat-a' });
    expect(mocks.memoryKeys).not.toHaveBeenCalled();
    expect(mocks.projects).not.toHaveBeenCalled();
    expect(mocks.tasks).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=workflows.chat.metadata-warmup
  it('keeps an unavailable inventory optional so the normal Send can retry', async () => {
    mocks.projects.mockRejectedValueOnce(new Error('offline'));
    await expect(prefetchChatMetadata({ scope: mocks.scope, teamId: null })).resolves.toBeUndefined();
    expect(mocks.tasks).toHaveBeenCalledExactlyOnceWith({});
  });
});
