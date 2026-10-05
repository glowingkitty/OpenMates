const onAuthoring = (recommendation: unknown) => {
  window.dispatchEvent(new CustomEvent('agent-context-preview-authoring', { detail: recommendation }));
};
const onSaveJob = (jobId: string) => {
  window.dispatchEvent(new CustomEvent('agent-context-preview-save', { detail: jobId }));
};
const defaults = {
  event: {
    type: 'rules_loaded', count: 2, set_key: 'a'.repeat(64), rules: [
      { id: 'app:code:python', title: 'Python coding rules', source: 'app', app_id: 'code', revision: 'b'.repeat(64), body: '- Preserve task cancellation.\n- Release resources with context managers.' },
      { id: 'project:preview:design', title: 'Mobile first design', source: 'project', project_id: 'Preview Project', revision: 'c'.repeat(64), body: '- Keep primary actions visible.\n- Reflow text at narrow widths.' },
    ],
  },
  onAuthoring,
  jobs: [], onSaveJob,
};
export default defaults;
export const variants = {
  correction: { event: { type: 'chat_direction_correction', delivery_id: 'preview-delivery', notice: 'Chat is drifting too far away from the goals. Correction instruction was sent.', instruction: 'Return to the approved signup accessibility fix. Keep the related screen-reader discovery; leave the unrelated dashboard redesign for a separate task.' }, onAuthoring, jobs: [], onSaveJob },
  recommendations: { event: { type: 'project_authoring_recommendations', recommendations: [
    { recommendation_id: 'preview-create', chat_id: 'preview-chat', project_id: 'preview-project', kind: 'focus', action: 'create', target_id: null, expected_revision: null, expires_at: 4_000_000_000 },
    { recommendation_id: 'preview-update', chat_id: 'preview-chat', project_id: 'preview-project', kind: 'workflow', action: 'update', target_id: 'preview-workflow', expected_revision: 'v2', expires_at: 4_000_000_000 },
  ] }, onAuthoring, jobs: [], onSaveJob },
  error: { event: { type: 'project_authoring_recommendations', recommendations: [
    { recommendation_id: 'preview-error', chat_id: 'preview-chat', project_id: 'preview-project', kind: 'focus', action: 'create', target_id: null, expected_revision: null, expires_at: 4_000_000_000 },
  ] }, onAuthoring: () => { throw new Error('Preview failure'); }, jobs: [], onSaveJob },
  draft: { event: { type: 'project_authoring_recommendation', recommendation_id: 'preview-draft', chat_id: 'preview-chat', project_id: 'preview-project', kind: 'focus', action: 'update', title: 'Debugging', target_id: 'preview-focus', expected_revision: 'v1' },
    onAuthoring, onSaveJob, jobs: [{ job_id: 'preview-job', recommendation_id: 'preview-draft', chat_id: 'preview-chat', kind: 'focus', status: 'needs_save', draft: { markdown: '---\nname: Debugging\ndescription: Investigate failures.\npreprocessor_hint: Debugging services.\n---\nKeep the approved goal and investigate its failing dependency first.' } }] },
  clarification: { event: { type: 'project_authoring_recommendation', recommendation_id: 'preview-question', chat_id: 'preview-chat', project_id: 'preview-project', kind: 'focus', action: 'create' },
    onAuthoring, onSaveJob, jobs: [{ job_id: 'preview-question-job', recommendation_id: 'preview-question', chat_id: 'preview-chat', kind: 'focus', status: 'needs_input', draft: { question: 'Which repository should this Focus cover?' } }] },
};
