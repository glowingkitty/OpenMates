/**
 * Preview fixtures for the Specification embed card.
 * Variants: draft, approved, changes-since-approval (Design to refine: badge colors, proof line).
 * Synthetic data only; open /dev/preview/embeds/specifications/SpecificationEmbedPreview.
 */
import type { SpecificationListItem } from './SpecificationRevision';

const item: SpecificationListItem = {
  id: 'preview-spec-teams', title: 'Teams', kind: 'Feature', status: 'draft', revisionNumber: 3,
  updatedAt: '2026-11-10T09:30:00Z', requirementCount: 3, proof: { passed: 1, open: 1, stale: 1 },
};

export default { id: 'preview-specification', item, isMobile: false, onFullscreen: () => {} };

export const variants = {
  approved: { id: 'preview-specification-approved', item: { ...item, status: 'approved', proof: { passed: 3, open: 0, stale: 0 } }, isMobile: false, onFullscreen: () => {} },
  'changes-since-approval': { id: 'preview-specification-changes', item: { ...item, status: 'approved', changesSinceApproval: true, revisionNumber: 4 }, isMobile: false, onFullscreen: () => {} },
  mobile: { id: 'preview-specification-mobile', item, isMobile: true, onFullscreen: () => {} },
};
