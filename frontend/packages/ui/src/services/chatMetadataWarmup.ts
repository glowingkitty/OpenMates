/** Prepare existing tab-local inventory projections; no draft or AI request. */
import { listProjects } from './projectService';
import { listUserTasks } from './userTaskService';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';

export async function prefetchChatMetadata(input: {
  scope: string | null;
  teamId: string | null;
  chatId?: string;
}): Promise<void> {
  if (!input.scope || input.scope !== getWorkspaceCacheIdentity()) return;
  const filters = input.teamId ? { teamId: input.teamId } : {};
  // These exact queries share the bounded, mutation-invalidated caches used by
  // the Send collectors. Accepted Plan approval and active focus stay fresh.
  await Promise.allSettled([
    listProjects({ teamId: input.teamId }),
    listUserTasks(filters),
    ...(input.chatId ? [listUserTasks({ ...filters, chatId: input.chatId })] : []),
  ]);
}
