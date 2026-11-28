/**
 * Maps the plans.create skill result and resolves its durable, decrypted Plan
 * through the same client services as the chat's active Plan panel.
 */
import { loadChatPlanDetails } from '../../chats/chatPlanDetails';
import { getUserPlan, listUserPlans } from '../../../services/userPlanService';
import { assistantTaskPersistenceRevision } from '../../../services/userTaskService';
import type { EmbedSourceChatContext } from '../../../types/embedFullscreen';
import type { PlanEmbedData } from './planEmbedModel';

const asText = (value: unknown): string => (typeof value === 'string' ? value : '');

function planCreateAction(content: Record<string, unknown>): Record<string, unknown> {
  const action = content.pending_client_action;
  return action && typeof action === 'object' ? action as Record<string, unknown> : content;
}

export function planDataFromCreate(content: Record<string, unknown>, id: string): PlanEmbedData {
  const action = planCreateAction(content);
  const planId = asText(content.plan_id) || asText(action.plan_id) || asText(action.request_id) || id;
  const goal = asText(action.goal) || asText(action.summary);
  const now = Math.floor(Date.now() / 1000);
  return {
    plan: {
      plan_id: planId, title: asText(action.title), goal,
      scopeIn: '', scopeOut: '', userFlows: [], assumptions: '', openQuestions: '', constraints: '',
      decisions: '', risks: '', status: 'draft', primaryChatId: asText(action.chat_id) || null,
      linkedProjectIds: [], plannerFocusId: null, version: 1, createdAt: now, updatedAt: now, completedAt: null,
      encrypted: { plan_id: planId, encrypted_title: '', encrypted_goal: '', status: 'draft', created_at: now, updated_at: now },
    },
    tasks: [], assumptions: [], criteria: [], checks: [],
  };
}

/** Publish fresh Plan details while this preview or fullscreen stays mounted. */
export function watchCreatedPlan(
  content: Record<string, unknown>, source: EmbedSourceChatContext | undefined,
  onPlan: (data: PlanEmbedData) => void,
): () => void {
  if (source?.isReadOnly || source?.exampleChatId) return () => {};
  const planId = asText(content.plan_id) || asText(planCreateAction(content).plan_id);
  const chatId = source?.chatId;
  if (!planId && !chatId) return () => {};
  let generation = 0;
  const unsubscribe = assistantTaskPersistenceRevision.subscribe(() => {
    const currentGeneration = ++generation;
    void (async () => {
      const plan = planId ? await getUserPlan(planId) : (await listUserPlans({ chatId: chatId ?? undefined, limit: 1 }))[0];
      if (!plan || currentGeneration !== generation) return;
      const details = (await loadChatPlanDetails([plan], []))[plan.plan_id];
      if (currentGeneration === generation) onPlan({ plan, ...details });
    })().catch(() => {
      if (currentGeneration === generation) console.warn('[PlanCreate] saved Plan details unavailable');
    });
  });
  return () => { generation += 1; unsubscribe(); };
}
