/** Progressive encrypted task-list loading for TUI workspaces. */
import type { OpenMatesClient, UserTaskRecord } from "./client.js";
import { decryptUserTasks, type DecryptedUserTask } from "./tasksCli.js";
import { loadProgressiveCachedTuiWorkspace, type TuiWorkspaceSource } from "./tuiCachedWorkspaces.js";

type TaskFilters = Parameters<OpenMatesClient["listUserTasks"]>[0];

/** Keep saved rows visible until a complete server snapshot can replace them. */
export function mergePartialTuiTasks(previous: DecryptedUserTask[] | null, page: DecryptedUserTask[]): DecryptedUserTask[] {
  if (!previous?.length) return page;
  const freshIds = new Set(page.map(task => task.taskId));
  return [...page, ...previous.filter(task => !freshIds.has(task.taskId))];
}

export function loadTuiTaskList(
  client: OpenMatesClient,
  key: string,
  filters: TaskFilters,
  publish: (tasks: DecryptedUserTask[], source: TuiWorkspaceSource, complete: boolean) => void | Promise<void>,
  onError?: (error: unknown, hasUsable: boolean) => void,
): Promise<DecryptedUserTask[] | null> {
  return loadProgressiveCachedTuiWorkspace(client, key, async progress => {
    const masterKey = client.getMasterKeyBytes();
    let decrypted: DecryptedUserTask[] = [];
    let received = 0;
    const records = await client.listUserTasks(filters, {
      onPage: async (cumulative: UserTaskRecord[], complete: boolean) => {
        // The client validates cumulative order and ownership before this callback.
        const next = await decryptUserTasks(cumulative.slice(received), masterKey);
        received = cumulative.length;
        decrypted = [...decrypted, ...next];
        await progress(decrypted, complete);
      },
    });
    // Older compatible clients may return a complete list without page callbacks.
    return received === records.length ? decrypted : decryptUserTasks(records, masterKey);
  }, publish, onError, mergePartialTuiTasks);
}
