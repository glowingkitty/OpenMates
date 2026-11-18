/**
 * Preview mock data for DocsEditor.
 * Access at: /dev/preview/embeds/docs/DocsEditor
 *
 * onSave stores the saved HTML on window.__docsEditorSaved (preview-only stub;
 * the real save path is proven by the real-stack E2E). Variant `saveFails`
 * rejects, variant `conflict` rejects with the version-conflict code.
 */
const sampleHtml = `<h1>Garden volunteer notes</h1>
<p>Welcome to the garden. Please read this before your first shift.</p>
<h2>Tools</h2>
<ul><li>Gloves</li><li>Watering can</li></ul>`;

declare global {
  interface Window {
    __docsEditorSaved?: string;
  }
}

const base = {
  html: sampleHtml,
  onSave: async (html: string) => {
    window.__docsEditorSaved = html;
  },
  onCancel: () => {}
};

export default base;

export const variants = {
  blank: { ...base, html: '' },
  saveFails: {
    ...base,
    onSave: async () => {
      throw new Error('Your edit could not be saved. Please try again.');
    }
  },
  conflict: {
    ...base,
    onSave: async () => {
      throw Object.assign(new Error('This was changed elsewhere, so your edit was not saved. Reload and try again.'), {
        code: 'embed_version_conflict'
      });
    }
  }
};
