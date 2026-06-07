/**
 * Preview mock data for ApplicationEmbedFullscreen.
 * Access at: /dev/preview/embeds/code/ApplicationEmbedFullscreen
 */

export default {
  data: {
    decodedContent: {
      type: 'application',
      name: 'Recipe Manager',
      framework: 'Svelte',
      runtime: 'Node',
      file_refs: [
        { path: 'package.json', embed_id: 'file-package', role: 'dependency_manifest' },
        { path: 'src/App.svelte', embed_id: 'file-app', role: 'source' },
        { path: 'src/main.ts', embed_id: 'file-main', role: 'source' },
      ],
      entrypoints: [{ name: 'frontend', command: 'npm run dev', port: 5173 }],
    },
    attrs: {},
    embedData: { version_number: 1 },
  },
  embedId: 'preview-application-1',
  chatId: 'preview-chat-1',
  onClose: () => {},
};
