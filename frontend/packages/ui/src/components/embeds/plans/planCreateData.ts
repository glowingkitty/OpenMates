/**
 * Maps the plans.create skill result (title, summary, goal) onto PlanEmbedData
 * as a draft Plan with empty lists. Pure mapping, no I/O.
 */
import type { PlanEmbedData } from './planEmbedModel';

const asText = (value: unknown): string => (typeof value === 'string' ? value : '');

export function planDataFromCreate(content: Record<string, unknown>, id: string): PlanEmbedData {
  const planId = asText(content.request_id) || id;
  const goal = asText(content.goal) || asText(content.summary);
  const now = Math.floor(Date.now() / 1000);
  return {
    plan: {
      plan_id: planId, title: asText(content.title), goal,
      scopeIn: '', scopeOut: '', userFlows: [], assumptions: '', openQuestions: '', constraints: '',
      decisions: '', risks: '', status: 'draft', primaryChatId: asText(content.chat_id) || null,
      linkedProjectIds: [], plannerFocusId: null, version: 1, createdAt: now, updatedAt: now, completedAt: null,
      encrypted: { plan_id: planId, encrypted_title: '', encrypted_goal: '', status: 'draft', created_at: now, updated_at: now },
    },
    tasks: [], assumptions: [], criteria: [], checks: [],
  };
}
