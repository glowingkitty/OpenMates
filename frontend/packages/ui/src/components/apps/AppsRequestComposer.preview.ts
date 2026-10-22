export default { appId: 'web', onSubmit: async (text: string, attachments: File[]) => {
  window.dispatchEvent(new CustomEvent('apps-request-preview-submit', { detail: { text, filenames: attachments.map(file => file.name) } }));
} };
export const variants = { embed: { appId: 'web', presentation: 'embed', onSubmit: async () => false }, submitting: { appId: 'web', value: 'Find quiet cafés in Berlin', submitting: true, onSubmit: async () => false } };
