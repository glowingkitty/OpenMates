/** Synthetic Plan fullscreen states. */
import { approvedPlanData, blockedPlanData, draftPlanData, inProgressPlanData } from './planEmbedFixtures';

export default { data: draftPlanData };
export const variants = {
  draft: { data: draftPlanData },
  approved: { data: approvedPlanData },
  inProgress: { data: inProgressPlanData },
  blocked: { data: blockedPlanData },
};
