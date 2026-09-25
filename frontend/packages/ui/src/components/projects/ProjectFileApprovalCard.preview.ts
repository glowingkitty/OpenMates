const writeRequest = {
  projectId: 'preview-project', chatId: 'preview-chat',
  mutation: {
    operation: 'update_file' as const, operation_id: 'preview-operation',
    path: 'src/greeting.ts', expected_base: 'a'.repeat(64),
    patch: '--- a/src/greeting.ts\n+++ b/src/greeting.ts\n@@ -1 +1 @@\n-export const greeting = "Hello";\n+export const greeting = "Hello, world!";\n',
  },
};
const onDecision = (_id: string, accepted: boolean) => {
  window.dispatchEvent(new CustomEvent('project-file-preview-decision', { detail: accepted }));
};
const defaults = {
  entry: { id: 'preview-operation', kind: 'write' as const, status: 'pending' as const, request: writeRequest },
  onDecision,
};
export default defaults;
export const variants = {
  ignoredRead: {
    entry: { id: 'preview-read', kind: 'read' as const, status: 'pending' as const,
      request: { projectId: 'preview-project', sourceId: 'preview-source', chatId: 'preview-chat', operationId: 'preview-read', path: 'logs/build.log' } },
    onDecision,
  },
  applied: {
    ...defaults,
    entry: { ...defaults.entry, status: 'applied' as const },
  },
};
