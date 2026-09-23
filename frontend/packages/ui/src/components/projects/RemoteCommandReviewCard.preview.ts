const entry = {
  id: 'preview-execution', chatId: 'preview-chat', projectId: 'preview-project', sourceId: 'preview-source',
  projectName: 'Greeting app', sourceName: 'Development laptop',
  status: 'pending' as const, latestOutput: '',
  review: {
    protocol_version: 1 as const, execution_id: 'preview-execution', chat_id: 'preview-chat', project_id: 'preview-project', source_id: 'preview-source',
    state: 'REVIEW_REQUIRED' as const, created_at: 1, review_expires_at: 4_102_444_800, approval_requirement: 'one_run' as const,
    command: { argv: ['npm', 'test', '--', 'src/greeting.test.ts'], cwd: '.', mode: 'foreground' as const, source_access: 'read_write' as const,
      deadline_ms: 120_000, writable_profiles: [], network_profile: null, credential_profiles: [] },
    explanation: { summary: 'Runs the greeting test suite in this project.', effects: ['Test tools may update generated files.'], risks: [], uncertainty: [] },
  },
};
const onDecision = (_id: string, accepted: boolean) => {
  window.dispatchEvent(new CustomEvent('remote-command-preview-decision', { detail: accepted ? 'approve' : 'reject' }));
};
const onStop = () => {
  window.dispatchEvent(new CustomEvent('remote-command-preview-decision', { detail: 'stop' }));
};
export default { entry, onDecision, onStop };
export const variants = {
  running: { entry: { ...entry, status: 'running', latestOutput: 'Running greeting tests…\n' }, onDecision, onStop },
  succeeded: { entry: { ...entry, status: 'succeeded', latestOutput: '2 tests passed\n' }, onDecision, onStop },
};
