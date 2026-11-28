/** Fullscreen fixture for the plans.check skill result. Design to refine: shared Check view as is. */
import { checkSkillContent } from './CheckSkillEmbedPreview.preview';
import { fixtureAssumption } from '../plans/planEmbedFixtures';

const defaultProps = { data: { decodedContent: checkSkillContent }, embedId: 'preview-check-skill', onClose: () => {} };
export default defaultProps;

export const variants = {
  'with-checking-chat': {
    ...defaultProps,
    relatedPlan: {
      planId: 'preview-plan',
      tasks: [],
      assumptions: [fixtureAssumption('delivery', 'Orders reach the checkout service', 'checking', 'preview-chat-assumption-delivery')],
    },
  },
};
