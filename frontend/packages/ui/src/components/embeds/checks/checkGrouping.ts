/**
 * frontend/packages/ui/src/components/embeds/checks/checkGrouping.ts
 *
 * Presentation grouping helpers for Check embeds: sources grouped by type and
 * the per-type mini status shown in the preview chips. No gating logic: the
 * aggregate always comes from the Check view model.
 */
import type { CheckView, SourceKind, SourceView } from './checkTypes';

export type SourceGroupId = 'e2e' | 'unit' | 'integration' | 'audit' | 'ai' | 'human';

export const SOURCE_GROUP_ORDER: SourceGroupId[] = ['e2e', 'unit', 'integration', 'audit', 'ai', 'human'];

const GROUP_OF: Record<SourceKind, SourceGroupId> = {
  e2e: 'e2e',
  unit: 'unit',
  integration: 'integration',
  static_analysis: 'audit',
  deterministic_audit: 'audit',
  ai_evaluation: 'ai',
  human_confirmation: 'human',
};

export interface SourceGroup {
  id: SourceGroupId;
  sources: SourceView[];
}

export interface GroupSummary {
  id: SourceGroupId;
  total: number;
  passed: number;
  failed: number;
  pending: number;
}

export function groupSources(check: CheckView): SourceGroup[] {
  return SOURCE_GROUP_ORDER
    .map((id) => ({ id, sources: check.sources.filter((s) => GROUP_OF[s.kind] === id) }))
    .filter((g) => g.sources.length > 0);
}

export function summarizeGroup(group: SourceGroup): GroupSummary {
  let passed = 0;
  let failed = 0;
  let pending = 0;
  for (const s of group.sources) {
    const st = s.latest_result?.status;
    if (st === 'passed') passed += 1;
    else if (st === 'failed' || st === 'error') failed += 1;
    else pending += 1;
  }
  return { id: group.id, total: group.sources.length, passed, failed, pending };
}
