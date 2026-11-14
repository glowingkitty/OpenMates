/**
 * Maps the plans.specification skill result (an unsaved draft) onto the
 * read-only SpecificationDocument the shared Specification components render.
 * Pure mapping, no I/O. Requirements carry no proof yet, so every one is 'open'.
 */
import type { SpecificationDocument, SpecFlow, SpecRequirement } from './SpecificationDocument';
import type { SpecificationListItem } from './SpecificationRevision';

const asText = (value: unknown): string => (typeof value === 'string' ? value : '');
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const asStrings = (value: unknown): string[] => asList(value).filter((item): item is string => typeof item === 'string');
const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {};

export function specificationDocumentFromSkill(content: Record<string, unknown>): SpecificationDocument {
  const requirements: SpecRequirement[] = asList(content.requirements).map((raw, index) => {
    const item = asRecord(raw);
    return {
      id: asText(item.id) || `requirement-${index + 1}`,
      statement: asText(item.statement),
      appliesTo: [],
      example: asText(item.example),
      proof: { state: 'open', title: '', explanation: '' },
    };
  });
  const flows: SpecFlow[] = asList(content.flows).map((raw, index) => {
    const item = asRecord(raw);
    return {
      id: asText(item.id) || `flow-${index + 1}`,
      title: asText(item.title),
      kind: item.kind === 'edge_case' ? 'edge_case' : 'user_flow',
      steps: asStrings(item.steps),
    };
  });
  const scope = asRecord(content.scope);
  return {
    title: asText(content.title),
    project: '',
    category: asText(content.category),
    summary: asText(content.summary),
    outcome: asText(content.outcome),
    scope: { included: asStrings(scope.included), excluded: asStrings(scope.excluded) },
    chapters: [{
      id: 'all', title: '', introduction: '',
      requirementIds: requirements.map((item) => item.id),
      flowIds: flows.map((item) => item.id), modelIds: [],
    }],
    requirements, flows, models: [],
  };
}

/** Card data for the shared Specification preview: a draft with no revision yet. */
export function specificationListItemFromSkill(content: Record<string, unknown>, id: string): SpecificationListItem {
  const document = specificationDocumentFromSkill(content);
  return {
    id, title: document.title, kind: document.category, status: 'draft', revisionNumber: 0,
    updatedAt: new Date().toISOString(), requirementCount: document.requirements.length,
    proof: { passed: 0, open: document.requirements.length, stale: 0 },
  };
}
