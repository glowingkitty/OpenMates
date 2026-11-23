/**
 * Reverse lookup for sub-chats: which Plan assumption a chat checks or which
 * Task it works on, read from the plaintext `linked_sub_chat_id` links of the
 * parent chat's Plans and Tasks. Display only; no new storage.
 */
import { listUserPlans } from '../../services/userPlanService';
import { listUserTasks } from '../../services/userTaskService';
import { loadChatPlanDetails, type ChatPlanDetails } from './chatPlanDetails';

export interface SubChatWork {
  kind: 'assumption' | 'task';
  label: string;
}

/** Pure lookup over already loaded Plan details. */
export function findSubChatWork(chatId: string, details: ChatPlanDetails): SubChatWork | null {
  for (const detail of Object.values(details)) {
    const assumption = detail.assumptions.find((item) => item.linkedSubChatId === chatId);
    if (assumption) return { kind: 'assumption', label: assumption.correctedText || assumption.text };
    const task = detail.tasks.find((item) => item.linkedSubChatId === chatId);
    if (task) return { kind: 'task', label: task.title };
  }
  return null;
}

/** Loads the parent chat's Plans and Tasks and resolves the sub-chat's work. */
export async function loadSubChatWork(chatId: string, parentChatId: string): Promise<SubChatWork | null> {
  const [tasks, plans] = await Promise.all([listUserTasks({ chatId: parentChatId }), listUserPlans({ chatId: parentChatId })]);
  return findSubChatWork(chatId, await loadChatPlanDetails(plans, tasks));
}
