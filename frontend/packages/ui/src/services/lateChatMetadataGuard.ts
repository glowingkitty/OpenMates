import { registerWorkspaceCacheClear } from './workspaceCacheLifecycle';
import { BoundedCache } from '../utils/boundedCache';

// Keep completed task ownership after active typing is cleared. Optional
// metadata can arrive late without reviving that task or replacing a newer one.
const owners = new BoundedCache<string, { taskId: string; userMessageId: string }>(128 * 1024, 256);
const completedTasks = new BoundedCache<string, true>(64 * 1024, 512);
registerWorkspaceCacheClear(() => { owners.clear(); completedTasks.clear(); });
export function noteChatMetadataTurn(chatId: string, taskId: string, userMessageId: string): boolean {
  const owner = owners.get(chatId);
  if (taskId && (completedTasks.has(`${chatId}:${taskId}`)
    || (owner && !owner.taskId && owner.userMessageId !== userMessageId))) return false;
  if (taskId && owner?.taskId && owner.taskId !== taskId) completedTasks.set(`${chatId}:${owner.taskId}`, true);
  owners.set(chatId, { taskId, userMessageId });
  return true;
}
export function completeChatMetadataTurn(chatId: string, taskId: string): void {
  completedTasks.set(`${chatId}:${taskId}`, true);
}
export function isChatMetadataTurnCurrent(chatId: string, taskId: string, userMessageId?: string): boolean {
  const owner = owners.get(chatId);
  return !owner || ((owner.taskId === taskId || (!owner.taskId && owner.userMessageId === userMessageId))
    && (!userMessageId || owner.userMessageId === userMessageId));
}

export function getChatMetadataTurnKey(chatId: string): string | null {
  const owner = owners.get(chatId);
  return owner ? `${owner.taskId}:${owner.userMessageId}` : null;
}
