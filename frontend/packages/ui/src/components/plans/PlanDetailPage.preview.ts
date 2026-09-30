/**
 * Sanitized Plan detail fixture matching the Apple Tasks workspace preview.
 * The component uses these explicit props without account/API reads or writes.
 */
import type {
  UserPlanDetailState,
  UserPlanViewModel,
} from '../../services/userPlanService';

const createdAt = 1_788_883_200;
const planId = 'preview-plan-draft';

const previewPlan = {
  plan_id: planId,
  title: 'Prepare the OpenMates launch plan',
  goal: 'Coordinate the work and verify the outcome before completion.',
  scopeIn: '',
  scopeOut: '',
  userFlows: [],
  assumptions: '',
  openQuestions: '',
  constraints: '',
  decisions: '',
  risks: '',
  status: 'draft',
  primaryChatId: null,
  linkedProjectIds: ['project-openmates'],
  plannerFocusId: null,
  version: 1,
  createdAt,
  updatedAt: createdAt,
  completedAt: null,
  encrypted: {
    plan_id: planId,
    encrypted_title: 'preview-ciphertext',
    encrypted_goal: 'preview-ciphertext',
    status: 'draft',
    created_at: createdAt,
    updated_at: createdAt,
  },
} satisfies UserPlanViewModel;

const previewDetailState = {
  assumptions: [{
    assumptionId: 'preview-assumption',
    text: 'Launch requirements are confirmed',
    category: 'requirement',
    status: 'unchecked',
    requiredBefore: 'implementation',
    linkedSubChatId: null,
    linkedTaskId: null,
    linkedCriterionIds: [],
    sourceCount: 0,
    correctedText: '',
    evidenceSummary: '',
    blockerReason: '',
    waiverReason: '',
    sources: '',
    version: 1,
    createdAt,
    updatedAt: createdAt,
    encrypted: { assumption_id: 'preview-assumption', status: 'unchecked' },
  }],
  criteria: [{
    criterionId: 'preview-criterion',
    text: 'The release is ready for users',
    type: 'acceptance',
    status: 'pending',
    required: true,
    linkedTaskIds: [],
    verificationIds: [],
    coverageStatus: 'uncovered',
    verificationScope: '',
    evidence: '',
    coverageNote: '',
    waiverReason: '',
    version: 1,
    createdAt,
    updatedAt: createdAt,
    encrypted: { criterion_id: 'preview-criterion', status: 'pending' },
  }],
  verifications: [],
  referencePatterns: [],
} satisfies UserPlanDetailState;

export default { planId, previewPlan, previewDetailState };
