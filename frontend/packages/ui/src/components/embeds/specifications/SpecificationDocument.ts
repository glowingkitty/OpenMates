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
  /** Projection from linked Checks; stored documents carry none and read as not proven. */
  proof?: { state: 'passed' | 'open' | 'stale'; title: string; explanation: string };
}
export interface SpecFlow {
  id: string;
  title: string;
  kind: 'user_flow' | 'edge_case';
  steps: string[];
  requiredCheckRefs?: string[];
}
/** Read-only projections of linked Project Checks, not Spec-owned definitions. */
export interface SpecCheckPreview {
  id: string;
  title: string;
  method: 'Deterministic' | 'Human confirmation';
  description: string;
  evidence: string;
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
/** Link to another Specification of the same split project. */
export interface SpecRelated {
  title: string;
  role: '' | SpecRole;
  relation: string;
}
/** Role of a Specification when a complex project is split into linked ones. */
export type SpecRole = 'product' | 'design' | 'technical';
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
  /** Optional note for design previews only; never set for real documents. */
  previewNotice?: string;
  linkedChecks?: SpecCheckPreview[];
  /** Empty for a single Specification; set when the user agreed to a split. */
  role?: '' | SpecRole;
  /** Assumptions the user has not confirmed yet. */
  assumptions?: string[];
  /** Agreed design decisions the requirements rely on. */
  designDecisions?: string[];
  relatedSpecifications?: SpecRelated[];
}
