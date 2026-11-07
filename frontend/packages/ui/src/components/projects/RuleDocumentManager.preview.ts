const document = '---\ntitle: Testing best practices\ndescription: Verify meaningful behavior.\nwhen_to_use: Adding or changing software tests.\n---\n- Assert caller-visible outcomes.\n- Keep disposable test data separate.\n';
const embedDocument = '---\ntitle: Launch plan\nreferences:\n  - kind: embed\n    id: preview-embed\n---\nCheck the launch page:\n```json\n{\n  "type": "website",\n  "embed_id": "preview-embed",\n  "reference_only": true\n}\n```\nThen announce it.\n';
const expiredDocument = '---\ntitle: Old travel plan\nload_mode: ask_first\nvalid_until: 2020-01-01T00:00:00.000Z\n---\nPrefer night trains.\n';
function props(projectId: string | null, fail = false, extra: { expired?: boolean; deepLink?: boolean; embed?: boolean } = {}) {
  let saved = [{ id: 'preview-rule', source: projectId ? 'project' : 'personal', ...(projectId ? { project_id: projectId } : {}), document },
    ...(extra.embed ? [{ id: 'preview-embed-rule', source: 'personal', document: embedDocument }] : []),
    ...(extra.expired ? [{ id: 'preview-expired', source: 'personal', document: expiredDocument }] : [])];
  return {
    projectId,
    ...(extra.deepLink ? { initialMemoryId: 'preview-rule', suggestion: { title: 'Testing habits', memory: 'Always add regression tests.', when_to_use: 'Writing tests.' } } : {}),
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
export const variants = {
  project: props('preview-project'), error: props(null, true),
  expired: props(null, false, { expired: true }), deeplink: props(null, false, { deepLink: true }), embed: props(null, false, { embed: true }),
};
