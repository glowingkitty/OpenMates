/**
 * Maps the plans.check skill result (an unsaved draft Check) onto CheckView.
 * No runs exist yet, so the aggregate is 'never_run'. Pure mapping, no I/O.
 */
import type { DraftCheck } from '../../../services/projectCheckService';
import type { CheckView, SourceKind, SourceRole, SourceView } from './checkTypes';

const KINDS: SourceKind[] = ['e2e', 'unit', 'integration', 'static_analysis', 'deterministic_audit', 'ai_evaluation', 'human_confirmation'];
const asText = (value: unknown): string => (typeof value === 'string' ? value : '');
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {};

function sourceView(raw: unknown, index: number): SourceView {
  const item = asRecord(raw);
  const kind = KINDS.find((candidate) => candidate === item.source_kind) ?? 'e2e';
  const role: SourceRole = item.role === 'supporting' ? 'supporting' : 'required';
  const refLabel = asText(item.test_target) || asText(item.question) || asText(item.instruction);
  return {
    binding_id: asText(item.source_binding_id) || `source-${index + 1}`,
    kind, role, title: asText(item.label), ref_label: refLabel,
  };
}

export function checkViewFromSkill(content: Record<string, unknown>, id: string): CheckView {
  return {
    id, title: asText(content.title), description: asText(content.description),
    status: 'draft', revision_number: 0, aggregate: 'never_run', stale: false,
    requires_deterministic: content.requires_deterministic === true,
    covered_claims: asList(content.covered_claims).filter((item): item is string => typeof item === 'string'),
    sources: asList(content.sources).map(sourceView),
    runs: [],
  };
}

/** The definition to save into a Project: the draft's sources with their reference (test, question or instruction). */
export function draftFromSkill(content: Record<string, unknown>): DraftCheck {
  return {
    title: asText(content.title), description: asText(content.description),
    requires_deterministic: content.requires_deterministic === true,
    sources: asList(content.sources).map((raw) => {
      const item = asRecord(raw);
      const kind = KINDS.find((candidate) => candidate === item.source_kind) ?? 'e2e';
      return {
        source_kind: kind, role: item.role === 'supporting' ? 'supporting' as const : 'required' as const,
        title: asText(item.label), ref: asText(item.test_target) || asText(item.question) || asText(item.instruction),
      };
    }),
  };
}
