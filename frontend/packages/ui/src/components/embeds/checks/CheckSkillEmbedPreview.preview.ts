/**
 * Preview fixture for the plans.check skill card (unsaved draft, never run).
 * Design to refine: reuses the shared Check card unchanged.
 */
export const checkSkillContent = {
  type: 'check', title: 'Shared list items sync between members',
  description: 'Proves that an item added by one member shows up for the others.',
  covered_claims: ['shared-lists.items.add', 'shared-lists.items.tick'],
  requires_deterministic: true,
  sources: [
    { source_binding_id: 'src-e2e-1', source_kind: 'e2e', role: 'required', label: 'Two members see the same list', test_target: 'shared-lists.spec.ts' },
    { source_binding_id: 'src-ai-1', source_kind: 'ai_evaluation', role: 'supporting', label: 'List reads clearly', question: 'Is the done section easy to tell apart?', threshold: 0.8 },
    { source_binding_id: 'src-human-1', source_kind: 'human_confirmation', role: 'supporting', label: 'Owner confirms the invite flow', instruction: 'Invite a second member and confirm they can edit.' },
  ],
  chat_id: 'preview-chat',
};

export default { presentationOnly: true, id: 'preview-check-skill', data: checkSkillContent, isMobile: false, onFullscreen: () => {} };
