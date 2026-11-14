/**
 * Preview fixtures for the Project Specifications section (populated and empty).
 * Open /dev/preview/projects/ProjectSpecificationsSection.
 */
import type { SpecificationListItem } from '../embeds/specifications/SpecificationRevision';

const base: SpecificationListItem = {
  id: 'teams', title: 'Teams', kind: 'Feature', status: 'draft', revisionNumber: 3,
  updatedAt: '2026-11-10T09:30:00Z', requirementCount: 3, proof: { passed: 1, open: 1, stale: 1 },
};
const items: SpecificationListItem[] = [
  base,
  { ...base, id: 'billing', title: 'Billing', status: 'approved', revisionNumber: 5, proof: { passed: 4, open: 0, stale: 0 } },
  { ...base, id: 'sync', title: 'Sync', status: 'approved', changesSinceApproval: true, revisionNumber: 7 },
];
export default { items, onOpen: () => {} };
export const variants = { empty: { items: [], onOpen: () => {} } };
