/** Synthetic Plan data for component previews and specs. No account or API reads. */
import type {
  UserPlanAssumptionViewModel,
  UserPlanCriterionViewModel,
  UserPlanVerificationViewModel,
  UserPlanViewModel,
  UserPlanStatus,
  UserPlanAssumptionStatus,
  UserPlanVerificationStatus,
} from '../../../services/userPlanService';
import type { PlanEmbedData, PlanLinkedTask } from './planEmbedModel';

const at = 1_788_883_200;

export function fixturePlan(overrides: Partial<UserPlanViewModel> & { status?: UserPlanStatus }): UserPlanViewModel {
  const status = overrides.status ?? 'draft';
  return {
    plan_id: 'preview-plan', title: 'Prepare the OpenMates launch plan',
    goal: 'Coordinate the work and verify the outcome before completion.',
    scopeIn: '', scopeOut: '', userFlows: [], assumptions: '', openQuestions: '', constraints: '',
    decisions: '', risks: '', status, primaryChatId: 'preview-chat', linkedProjectIds: [], plannerFocusId: null,
    version: 1, createdAt: at, updatedAt: at, completedAt: null,
    encrypted: { plan_id: 'preview-plan', encrypted_title: 'x', encrypted_goal: 'x', status, created_at: at, updated_at: at },
    ...overrides,
  };
}

export function fixtureAssumption(id: string, text: string, status: UserPlanAssumptionStatus, linkedSubChatId: string | null = null): UserPlanAssumptionViewModel {
  return {
    assumptionId: id, text, category: 'requirement', status, requiredBefore: 'implementation', linkedSubChatId,
    linkedTaskId: null, linkedCriterionIds: [], sourceCount: 0, correctedText: '', evidenceSummary: '', blockerReason: '',
    waiverReason: '', sources: '', version: 1, createdAt: at, updatedAt: at, encrypted: { assumption_id: id, status },
  };
}

export function fixtureCriterion(id: string, text: string, verificationIds: string[]): UserPlanCriterionViewModel {
  return {
    criterionId: id, text, type: 'acceptance', status: 'pending', required: true, linkedTaskIds: [], verificationIds,
    coverageStatus: verificationIds.length > 0 ? 'covered' : 'uncovered', verificationScope: '', evidence: '',
    coverageNote: '', waiverReason: '', version: 1, createdAt: at, updatedAt: at, encrypted: { criterion_id: id, status: 'pending' },
  };
}

export function fixtureCheck(
  id: string, description: string, status: UserPlanVerificationStatus,
  options: { required?: boolean; lifecycleStatus?: string; covers?: string[] } = {},
): UserPlanVerificationViewModel {
  return {
    verificationId: id, kind: 'manual', phase: '', status, requiredForDone: options.required ?? true,
    covers: options.covers ?? [], lifecycleStatus: options.lifecycleStatus ?? '', sourceHash: null, threshold: null, score: null,
    confidence: null, linkedTaskId: null, linkedSubChatId: null, sourceEmbedId: null, runnerKind: null, runId: null,
    description, command: '', evaluationPrompt: '', evaluatorInstructions: '', expectedResult: '', resultSummary: '',
    requiredFixes: '', sourcePath: '', redPhaseReason: '', createdAt: at, updatedAt: at,
    encrypted: { verification_id: id, kind: 'manual', status },
  };
}

const tasks: PlanLinkedTask[] = [
  { taskId: 'task-1', title: 'Write the release notes', status: 'done' },
  { taskId: 'task-2', title: 'Review the release checklist', status: 'in_progress' },
  { taskId: 'task-3', title: 'Announce the launch', status: 'todo' },
];

export const draftPlanData: PlanEmbedData = {
  plan: fixturePlan({ status: 'draft', submittedRevisionId: 'rev-1' }),
  tasks: tasks.map((task) => ({ ...task, status: 'todo' })),
  assumptions: [
    fixtureAssumption('a1', 'Launch requirements are confirmed', 'unchecked'),
    fixtureAssumption('a2', 'The announcement channel is available', 'checking', 'preview-sub-chat'),
  ],
  criteria: [fixtureCriterion('c1', 'The release is ready for users', ['v1'])],
  checks: [fixtureCheck('v1', 'Release checklist is complete', 'pending', { covers: ['c1'] })],
  revisionId: 'rev-1', revisionNumber: 1,
};

export const approvedPlanData: PlanEmbedData = {
  plan: fixturePlan({ status: 'active', approvalState: 'approved', submittedRevisionId: 'rev-2', approvedRevisionId: 'rev-2' }),
  tasks: tasks.map((task) => ({ ...task, status: 'todo' })),
  assumptions: [fixtureAssumption('a1', 'Launch requirements are confirmed', 'confirmed'), fixtureAssumption('a2', 'The announcement channel is available', 'corrected')],
  criteria: [fixtureCriterion('c1', 'The release is ready for users', ['v1', 'v2'])],
  checks: [
    fixtureCheck('v1', 'Release checklist is complete', 'passed', { covers: ['c1'] }),
    fixtureCheck('v2', 'Smoke test of the signup flow', 'pending', { covers: ['c1'], required: false }),
  ],
  revisionId: 'rev-2', revisionNumber: 2,
};

export const inProgressPlanData: PlanEmbedData = {
  ...approvedPlanData,
  plan: fixturePlan({ status: 'executing', approvalState: 'approved', submittedRevisionId: 'rev-2', approvedRevisionId: 'rev-2' }),
  tasks,
  checks: [
    fixtureCheck('v1', 'Release checklist is complete', 'passed', { covers: ['c1'] }),
    fixtureCheck('v2', 'Signup flow works end to end', 'pending', { covers: ['c1'], lifecycleStatus: 'waiting_for_confirmation' }),
    fixtureCheck('v3', 'Pricing page copy matches', 'passed', { covers: ['c1'], lifecycleStatus: 'stale' }),
  ],
};

export const blockedPlanData: PlanEmbedData = {
  ...approvedPlanData,
  plan: fixturePlan({ status: 'blocked', approvalState: 'approved', submittedRevisionId: 'rev-3', approvedRevisionId: 'rev-2' }),
  tasks: [tasks[0], { ...tasks[1], status: 'blocked' }, tasks[2]],
  assumptions: [fixtureAssumption('a1', 'Launch requirements are confirmed', 'blocked', 'preview-sub-chat')],
  checks: [fixtureCheck('v1', 'Release checklist is complete', 'failed', { covers: ['c1'] })],
  revisionId: 'rev-3', revisionNumber: 3,
};
