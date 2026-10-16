import { parseMemoriesLoadedEvent, type MemoriesLoadedEvent } from './loadedMemoryReceipt';
/** Pure parsing of persisted context notices; reading history never performs work. */
export interface AppliedRuleDetail {
  id: string;
  title: string;
  source: 'app' | 'personal' | 'project';
  app_id?: string | null;
  project_id?: string | null;
  revision: string;
  body: string;
}

export interface RulesLoadedEvent {
  type: 'rules_loaded';
  count: number;
  set_key: string;
  rules: AppliedRuleDetail[];
}

export interface DirectionCorrectionEvent {
  type: 'chat_direction_correction';
  notice: string;
  instruction: string;
  delivery_id: string;
}

export interface ProjectAuthoringRecommendation {
  recommendation_id: string;
  chat_id: string;
  project_id: string;
  kind: 'focus' | 'workflow';
  action: 'create' | 'update';
  target_id?: string | null;
  expected_revision?: string | null;
  expires_at?: number;
  title?: string;
  message_id?: string;
}

export interface ProjectAuthoringEvent {
  type: 'project_authoring_recommendations';
  recommendations: ProjectAuthoringRecommendation[];
}

export interface ProjectAuthoringSingleEvent extends ProjectAuthoringRecommendation {
  type: 'project_authoring_recommendation';
}

export type AgentContextEvent = MemoriesLoadedEvent | RulesLoadedEvent | DirectionCorrectionEvent | ProjectAuthoringEvent | ProjectAuthoringSingleEvent;

export interface ProjectAuthoringJobDisplay {
  job_id: string;
  recommendation_id: string;
  chat_id: string;
  kind: 'focus' | 'workflow';
  status: string;
  draft?: { question?: string; markdown?: string };
}

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function parseAgentContextEvent(content: unknown): AgentContextEvent | null {
  let value: unknown = content;
  if (typeof content === 'string') {
    if (content.length > 100_000) return null;
    try { value = JSON.parse(content); } catch { return null; }
  }
  if (!object(value)) return null;
  if (value.type === 'project_authoring_recommendation') {
    return validRecommendation(value) ? value as unknown as ProjectAuthoringSingleEvent : null;
  }
  if (value.type === 'memories_loaded') return parseMemoriesLoadedEvent(value);
  if (value.type === 'rules_loaded') {
    if (!Array.isArray(value.rules) || !value.rules.length || value.rules.length > 24
      || value.count !== value.rules.length || typeof value.set_key !== 'string') return null;
    const identities = new Set<string>();
    for (const rule of value.rules) {
      if (!object(rule) || typeof rule.id !== 'string' || identities.has(rule.id)
        || typeof rule.title !== 'string' || !rule.title || typeof rule.body !== 'string' || !rule.body
        || typeof rule.revision !== 'string' || !/^[a-f0-9]{64}$/.test(rule.revision)
        || !['app', 'personal', 'project'].includes(String(rule.source))) return null;
      identities.add(rule.id);
    }
    return value as unknown as RulesLoadedEvent;
  }
  if (value.type === 'chat_direction_correction') {
    return typeof value.notice === 'string' && !!value.notice
      && typeof value.instruction === 'string' && !!value.instruction
      && typeof value.delivery_id === 'string' && !!value.delivery_id
      ? value as unknown as DirectionCorrectionEvent : null;
  }
  if (value.type === 'project_authoring_recommendations' && Array.isArray(value.recommendations)) {
    const recommendations = value.recommendations.filter(validRecommendation);
    return recommendations.length && recommendations.length <= 16
      ? { type: 'project_authoring_recommendations', recommendations: recommendations as unknown as ProjectAuthoringRecommendation[] } : null;
  }
  return null;
}

function validRecommendation(entry: unknown): boolean {
  return object(entry) && typeof entry.recommendation_id === 'string' && !!entry.recommendation_id
    && typeof entry.chat_id === 'string' && !!entry.chat_id
    && typeof entry.project_id === 'string' && !!entry.project_id
    && ['focus', 'workflow'].includes(String(entry.kind))
    && ['create', 'update'].includes(String(entry.action))
    && (entry.expires_at === undefined || typeof entry.expires_at === 'number')
    && (entry.expected_revision == null || typeof entry.expected_revision === 'string')
    && (entry.target_id == null || typeof entry.target_id === 'string');
}
