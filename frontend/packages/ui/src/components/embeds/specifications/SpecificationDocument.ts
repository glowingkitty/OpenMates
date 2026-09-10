/**
 * Read-only view data for the Specification fullscreen component.
 * Keeps presentation independent from encrypted storage and YAML transport.
 * Chapters reference canonical requirements, flows and models by stable ID.
 * Proof is a separate revision-bound projection, never an authored boolean.
 * Contract: specifications/features/specifications/specification.yml.
 */
export interface SpecRequirement {
  id: string;
  statement: string;
  appliesTo: string[];
  example: string;
  proof: { state: 'passed' | 'open' | 'stale'; title: string; explanation: string };
}
export interface SpecFlow {
  id: string;
  title: string;
  kind: 'user_flow' | 'edge_case';
  steps: string[];
}
export interface SpecModel {
  id: string;
  description: string;
  fields: { name: string; type: string; description: string }[];
}
export interface SpecChapter {
  id: string;
  title: string;
  introduction: string;
  requirementIds: string[];
  flowIds: string[];
  modelIds: string[];
}
export interface SpecificationDocument {
  title: string;
  project: string;
  category: string;
  summary: string;
  outcome: string;
  outcomeReference?: { title: string; labels: string[]; description: string };
  scope: { included: string[]; excluded: string[] };
  chapters: SpecChapter[];
  requirements: SpecRequirement[];
  flows: SpecFlow[];
  models: SpecModel[];
  previewNotice: string;
}
