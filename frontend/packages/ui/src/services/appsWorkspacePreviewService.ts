import { EMBED_CHILD_TYPE_MAP } from '../data/embedRegistry.generated';
import type { AppsRecommendation } from './appsWorkspaceLibraryService';

/** Present native result children without persisting an expiring recommendation. */
export function recommendationPreviewItems(appId: string, batch: AppsRecommendation): Array<{ id: string; type: string; content: Record<string, unknown> }> {
  const children: Record<string, unknown>[] = [];
  const visit = (value: unknown, depth: number): void => {
    if (depth > 6 || children.length >= 40) return;
    if (Array.isArray(value)) { for (const child of value) visit(child, depth + 1); return; }
    if (!value || typeof value !== 'object') return;
    const row = value as Record<string, unknown>;
    for (const key of ['data', 'results', 'items', 'connections', 'stays', 'repositories', 'articles', 'videos', 'models']) {
      if (Array.isArray(row[key]) || (key === 'data' && row[key] && typeof row[key] === 'object')) {
        visit(row[key], depth + 1); return;
      }
    }
    children.push(row);
  };
  visit(batch.result, 0);
  return (children.length ? children : [batch.result]).map((content, index) => ({
    id: batch.id + ':' + index,
    type: typeof content.type === 'string' ? content.type : EMBED_CHILD_TYPE_MAP[appId + ':' + batch.skill_id] ?? 'app-skill-use',
    content: { ...content, app_id: appId, skill_id: batch.skill_id },
  }));
}
