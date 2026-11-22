/**
 * Loads the Plan linked to a chat as SpecPlanLinks / SpecPlanTask lists for the
 * Specification and Check fullscreens. Mapping only; Plan and Task loading stay
 * in the Plan/Task services and chatPlanDetails. Failures resolve to null so the
 * cards stay as they are; only the error code is logged (no plaintext).
 */
import { listUserPlans } from '../../../services/userPlanService';
import { listUserTasks } from '../../../services/userTaskService';
import { loadChatPlanDetails } from '../../chats/chatPlanDetails';
import type { SpecPlanLinks } from './specPlanLinks';

export async function loadSpecPlanLinks(chatId: string | null | undefined): Promise<SpecPlanLinks | null> {
  if (!chatId) return null;
  try {
    const [chatTasks, plans] = await Promise.all([listUserTasks({ chatId }), listUserPlans({ chatId, limit: 6 })]);
    const plan = plans.find((item) => !['completed', 'archived'].includes(item.status)) ?? plans[0];
    if (!plan) return null;
    const detail = (await loadChatPlanDetails([plan], chatTasks))[plan.plan_id];
    if (!detail) return null;
    const descriptions = new Map(chatTasks.map((task) => [task.task_id, task.description]));
    return {
      planId: plan.plan_id,
      assumptions: detail.assumptions.map((item) => ({ text: item.text, status: item.status, linkedSubChatId: item.linkedSubChatId })),
      tasks: detail.tasks.map((task) => ({
        taskId: task.taskId,
        title: task.title,
        description: descriptions.get(task.taskId) || task.title,
        status: task.status,
        linkedSubChatId: task.linkedSubChatId ?? null,
      })),
    };
  } catch (error) {
    const code = (error as { code?: string; name?: string } | null)?.code ?? (error as Error | null)?.name ?? 'unknown';
    console.warn('[loadSpecPlanLinks] Plan links not loaded:', code);
    return null;
  }
}
