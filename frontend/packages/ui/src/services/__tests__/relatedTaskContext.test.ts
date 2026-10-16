import { beforeEach, describe, expect, it, vi } from 'vitest';
const { list, dependencies, identity } = vi.hoisted(() => ({ list: vi.fn(), dependencies: vi.fn(), identity: vi.fn() }));
vi.mock('../userTaskService', () => ({ listUserTasks: list, listUserTaskDependencies: dependencies }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: identity }));
import { collectRelatedTaskSnapshots, taskContextSnapshots } from '../relatedTaskContext';
const task = (id: string, status = 'in_progress', updatedAt = 10_000) => ({ task_id: id,
  title: 'Fix duplicate posts', description: 'Owned Task summary', latestInstruction: '', status,
  updatedAt, linkedProjectIds: ['project-a'], version: 7 }) as any;
describe('related Task transport shortlist', () => {
  beforeEach(() => { vi.clearAllMocks(); dependencies.mockResolvedValue([]); identity.mockReturnValue('owner-a'); });
  // contract-test: supporting surface=gui.web assertions=chats.context.related-work-selection
  it('preserves active older work and excludes old completed, pending and future-dated candidates', () => {
    const snapshots = taskContextSnapshots([task('active', 'in_progress', 1), task('recent', 'blocked', 9_900),
      task('old', 'done', 1), task('todo', 'todo'), task('future', 'done', 10_100),
      task('future-active', 'in_progress', 10_100)], 10_000);
    expect(snapshots.map(item => item.task_id)).toEqual(['active', 'recent']);
    expect(snapshots[0]).toMatchObject({ revision: '7', project_id: 'project-a' });
  });
  // contract-test: supporting surface=gui.web assertions=chats.context.related-work-selection
  it('limits candidates and transmitted text without changing the source Task', () => {
    const source = task('task-0'); source.title = 't'.repeat(500); source.description = 'd'.repeat(5_000);
    const snapshots = taskContextSnapshots([source, ...Array.from({ length: 35 }, (_, index) => task(`task-${index + 1}`))], 10_000);
    expect(snapshots).toHaveLength(24); expect(snapshots[0].title).toHaveLength(240);
    expect(snapshots[0].summary).toHaveLength(1_200); expect(source.description).toHaveLength(5_000);
  });
  // contract-test: supporting surface=gui.web assertions=chats.context.related-work-selection
  it('keeps Team discovery in the requested server-checked namespace', async () => {
    list.mockResolvedValue([task('active')]);
    await collectRelatedTaskSnapshots('team-a', 'chat-a');
    expect(list).toHaveBeenCalledWith({ teamId: 'team-a' });
    expect(list).toHaveBeenCalledWith({ teamId: 'team-a', chatId: 'chat-a' });
    expect(dependencies).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.context.related-work-selection,chats.direction.context-assessment
  it('prioritizes old current-chat open Tasks over global discovery while excluding old unlinked work', () => {
    const linked = ['todo', 'backlog', 'blocked'].map((status) => ({ ...task(`linked-${status}`, status, 1), primaryChatId: 'chat-a' }));
    const snapshots = taskContextSnapshots([...Array.from({ length: 30 }, (_, index) => task(`active-${index}`)),
      ...linked, task('old-unlinked', 'blocked', 1), { ...task('other-chat', 'todo', 1), primaryChatId: 'chat-b' },
      { ...task('future-linked', 'todo', 20_000), primaryChatId: 'chat-a' }], 10_000, 'chat-a');
    expect(snapshots).toHaveLength(24);
    expect(snapshots.slice(0, 4).map(item => item.task_id)).toEqual([
      'future-linked', 'linked-backlog', 'linked-blocked', 'linked-todo',
    ]);
    expect(snapshots.some(item => ['old-unlinked', 'other-chat'].includes(item.task_id))).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=chats.context.related-work-selection,chats.direction.context-assessment
  it('includes old actual dependency targets and preserves linked Tasks missing from the global page', async () => {
    const linked = { ...task('linked', 'todo', 1), primaryChatId: 'chat-a' };
    list.mockImplementation(async (filters) => filters.chatId ? [linked] : [task('dependency', 'blocked', 1), task('old-unlinked', 'blocked', 1)]);
    dependencies.mockResolvedValue([{ targetKind: 'task', targetId: 'dependency' }, { targetKind: 'plan', targetId: 'old-unlinked' }]);
    const snapshots = await collectRelatedTaskSnapshots(null, 'chat-a');
    expect(snapshots.map(item => item.task_id)).toEqual(['linked', 'dependency']);
    expect(dependencies).toHaveBeenCalledWith('linked');
    expect(list).toHaveBeenCalledWith({ chatId: 'chat-a' });
  });
  // contract-test: supporting surface=gui.web assertions=chats.context.related-work-selection,chats.direction.context-assessment
  it('bounds real dependency reads and discards snapshots after an account switch', async () => {
    list.mockResolvedValue(Array.from({ length: 10 }, (_, index) => ({ ...task(`linked-${index}`, 'todo'), primaryChatId: 'chat-a' })));
    await collectRelatedTaskSnapshots(null, 'chat-a');
    expect(dependencies).toHaveBeenCalledTimes(4);
    dependencies.mockImplementation(async () => { identity.mockReturnValue('owner-b'); return []; });
    expect(await collectRelatedTaskSnapshots(null, 'chat-a')).toEqual([]);
  });
});
