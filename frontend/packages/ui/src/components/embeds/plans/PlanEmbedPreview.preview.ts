/** Synthetic Plan embed card states. */
import { approvedPlanData, blockedPlanData, draftPlanData, inProgressPlanData } from './planEmbedFixtures';

const onFullscreen = () => {};

export default { id: 'preview-plan', data: draftPlanData, onFullscreen };
export const variants = {
  draft: { id: 'preview-plan', onFullscreen, data: draftPlanData },
  approved: { id: 'preview-plan', onFullscreen, data: approvedPlanData },
  inProgress: { id: 'preview-plan', onFullscreen, data: inProgressPlanData },
  blocked: { id: 'preview-plan', onFullscreen, data: blockedPlanData },
};
