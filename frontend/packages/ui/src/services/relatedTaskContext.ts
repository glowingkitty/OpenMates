/** Bounded client-decrypted Task snapshots. Server ownership/version/activity checks remain authoritative. */
import { listUserTaskDependencies, listUserTasks, type UserTaskViewModel } from './userTaskService';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';

export interface RelatedTaskSnapshot {
  task_id: string;
  title: string;
  summary: string;
  project_id: string | null;
  status: string;
  revision: string;
}

const OPEN_TASK_STATUSES = new Set(['todo', 'backlog', 'in_progress', 'blocked']);
const MAX_DEPENDENCY_READS = 4;

export function taskContextSnapshots(tasks: UserTaskViewModel[], now = Date.now() / 1_000,
  chatId?: string, dependencyTaskIds: ReadonlySet<string> = new Set()): RelatedTaskSnapshot[] {
  const linked = (task: UserTaskViewModel) => !!chatId && task.primaryChatId === chatId && OPEN_TASK_STATUSES.has(task.status);
  const priority = (task: UserTaskViewModel) => linked(task) ? 2 : dependencyTaskIds.has(task.task_id) ? 1 : 0;
  return tasks.filter((task) => linked(task) || dependencyTaskIds.has(task.task_id)
    || task.updatedAt <= now && (task.status === 'in_progress'
      || ['blocked', 'done'].includes(task.status) && now - task.updatedAt < 1_800))
    .sort((a, b) => priority(b) - priority(a)
      || Number(b.status === 'in_progress') - Number(a.status === 'in_progress')
      || b.updatedAt - a.updatedAt || a.task_id.localeCompare(b.task_id))
    .slice(0, 24).map((task) => ({ task_id: task.task_id, title: task.title.slice(0, 240),
      summary: (task.description || task.latestInstruction || '').slice(0, 1_200),
      project_id: task.linkedProjectIds[0] ?? null, status: task.status, revision: String(task.version) }));
}

export async function collectRelatedTaskSnapshots(teamId?: string | null, chatId?: string): Promise<RelatedTaskSnapshot[]> {
  // updatedAt is only a client shortlist. The backend uses actual lifecycle or
  // comment activity; navigation and reordering cannot manufacture eligibility.
  const scope = getWorkspaceCacheIdentity();
  const filters = teamId ? { teamId } : {};
  const lists = await Promise.allSettled([
    listUserTasks(filters),
    ...(chatId ? [listUserTasks({ ...filters, chatId })] : []),
  ]);
  if (scope !== getWorkspaceCacheIdentity()) return [];
  const tasks = new Map<string, UserTaskViewModel>();
  for (const result of lists) {
    if (result.status !== 'fulfilled') continue;
    for (const task of result.value) {
      const previous = tasks.get(task.task_id);
      if (!previous || task.version > previous.version
        || task.version === previous.version && task.updatedAt > previous.updatedAt) tasks.set(task.task_id, task);
    }
  }
  const candidates = [...tasks.values()];
  const dependencyTaskIds = new Set<string>();
  // The existing dependency API is owner-only. Never substitute its personal
  // namespace for a Team read. Edges qualify references, not task authority.
  if (chatId && !teamId) {
    const linkedTasks = taskContextSnapshots(candidates, Date.now() / 1_000, chatId)
      .filter((snapshot) => tasks.get(snapshot.task_id)?.primaryChatId === chatId
        && OPEN_TASK_STATUSES.has(snapshot.status)).slice(0, MAX_DEPENDENCY_READS);
    const edges = await Promise.allSettled(linkedTasks.map((task) => listUserTaskDependencies(task.task_id)));
    if (scope !== getWorkspaceCacheIdentity()) return [];
    for (const result of edges) {
      if (result.status !== 'fulfilled') continue;
      for (const dependency of result.value) {
        if (dependency.targetKind === 'task') dependencyTaskIds.add(dependency.targetId);
      }
    }
  }
  return taskContextSnapshots(candidates, Date.now() / 1_000, chatId, dependencyTaskIds);
}
