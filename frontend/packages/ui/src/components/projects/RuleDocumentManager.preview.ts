const document = '---\ntitle: Testing best practices\ndescription: Verify meaningful behavior.\nwhen_to_use: Adding or changing software tests.\n---\n- Assert caller-visible outcomes.\n- Keep disposable test data separate.\n';
function props(projectId: string | null, fail = false) {
  let saved = [{ id: 'preview-rule', source: projectId ? 'project' : 'personal', ...(projectId ? { project_id: projectId } : {}), document }];
  return {
    projectId,
    onClose: () => window.dispatchEvent(new CustomEvent('rule-preview-close')),
    service: {
      list: async () => saved,
      save: async (source: 'personal' | 'project', project: string | null, next: string, existing: { id: string } | null) => {
        if (fail) throw new Error('Preview save failure');
        saved = [{ id: existing?.id ?? 'preview-new-rule', source, ...(project ? { project_id: project } : {}), document: next }];
        window.dispatchEvent(new CustomEvent('rule-preview-saved', { detail: { source, document: next } }));
      },
    },
  };
}
export default props(null);
export const variants = { project: props('preview-project'), error: props(null, true) };
