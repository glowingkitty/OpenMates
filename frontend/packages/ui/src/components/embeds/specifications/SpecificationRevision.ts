/**
 * Typed view data for Specification revisions and approval state.
 * Props-driven: the parent supplies it from the client core, never from storage here.
 * Approval always names an exact revision and its content hash.
 * Contract: specifications/features/specifications/specification.yml.
 */
export type SpecificationStatus = 'draft' | 'approved' | 'superseded';

export interface SpecificationRevisionSummary {
  revision_id: string;
  revision_number: number;
  created_at: string;
  author_label: string;
  summary: string;
  status: SpecificationStatus;
  content_hash: string;
}

export interface SpecificationApproval {
  /** stale: an approved revision exists but newer changes were made after it. */
  state: 'draft' | 'approved' | 'stale';
  approved_revision_id: string | null;
  approved_at: string | null;
}

export interface SpecificationProofSummary {
  passed: number;
  open: number;
  stale: number;
}

/** Item shown by the Project Specifications section and the embed preview. */
export interface SpecificationListItem {
  id: string;
  title: string;
  kind: string;
  status: SpecificationStatus;
  revisionNumber: number;
  updatedAt: string;
  requirementCount: number;
  proof: SpecificationProofSummary;
  changesSinceApproval?: boolean;
}
