import { getApiEndpoint } from '../config/api';
import type { AppsDecisionAssets } from './appsWorkspaceAttachmentService';
import type { AppsSkillResponse } from '../types/appsWorkspace';

/** Bounded image-aware scoring reorders existing result objects; it never creates cards. */
export async function rankAppsWorkspaceImageResults(response: AppsSkillResponse, options: {
  appId: string; text: string; prepareModelText: (value: string) => string; expectedUserId?: string; assets: AppsDecisionAssets; teamId?: string; signal?: AbortSignal; assertCurrent: () => void;
}): Promise<AppsSkillResponse> {
  const copy = structuredClone(response);
  const groups: unknown[][] = [];
  const visit = (value: unknown, depth = 0): void => {
    if (!value || typeof value !== 'object' || depth > 4) return;
    if (Array.isArray(value)) { for (const item of value) visit(item, depth + 1); return; }
    const record = value as Record<string, unknown>;
    if (record.data) visit(record.data, depth + 1);
    if (Array.isArray(record.results)) {
      if (record.results.some(item => item && typeof item === 'object' && Array.isArray((item as Record<string, unknown>).results))) visit(record.results, depth + 1);
      else groups.push(record.results);
    }
  };
  visit(copy);
  const items = groups.flat().filter((item): item is Record<string, unknown> => !!item && typeof item === 'object').slice(0, 30);
  if (items.length < 2) return response;
  const ids = new Map(items.map((item, index) => [item, `result-${index}`]));
  const candidates = items.map(item => ({ id: ids.get(item)!,
    title: options.prepareModelText(String(item.title ?? item.name ?? '')).slice(0, 200),
    text: options.prepareModelText(['description', 'snippet', 'summary', 'text', 'address'].map(key => typeof item[key] === 'string' ? item[key] : '').filter(Boolean).join('\n')).slice(0, 800) }));
  try {
    options.assertCurrent();
    const result = await fetch(getApiEndpoint('/v1/apps/workspace/rank'), { method: 'POST', credentials: 'include', signal: options.signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app_id: options.appId, request_id: crypto.randomUUID(),
        text: options.prepareModelText(options.text), ...(options.expectedUserId ? { expected_user_id: options.expectedUserId } : {}), assets: options.assets, candidates, ...(options.teamId ? { team_id: options.teamId } : {}) }) });
    const body = await result.json(); options.assertCurrent();
    if (!result.ok || !Array.isArray(body.ranked_ids)) return response;
    const ranks = new Map<string, number>();
    for (const id of body.ranked_ids) if (typeof id === 'string' && !ranks.has(id)) ranks.set(id, ranks.size);
    const rank = (value: unknown) => ranks.get(ids.get(value as Record<string, unknown>) ?? '') ?? Number.MAX_SAFE_INTEGER;
    for (const group of groups) group.sort((a, b) => rank(a) - rank(b));
    return copy;
  } catch {
    options.assertCurrent();
    // A scoring outage must preserve the accepted, paid native result.
    return response;
  }
}
