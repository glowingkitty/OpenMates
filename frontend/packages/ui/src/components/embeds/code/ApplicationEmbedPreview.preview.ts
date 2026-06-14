/**
 * Preview mock data for ApplicationEmbedPreview.
 * Access at: /dev/preview/embeds/code/ApplicationEmbedPreview
 */

const defaultProps = {
  id: 'preview-application-1',
  name: 'Recipe Manager',
  framework: 'Svelte',
  runtime: 'Node',
  file_refs: [
    { path: 'package.json', embed_id: 'file-package', role: 'dependency_manifest' },
    { path: 'src/App.svelte', embed_id: 'file-app', role: 'source' },
    { path: 'src/main.ts', embed_id: 'file-main', role: 'source' },
  ],
  entrypoints: [{ name: 'frontend', command: 'npm run dev', port: 5173 }],
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-application-processing',
    status: 'processing' as const,
  },
  error: {
    ...defaultProps,
    id: 'preview-application-error',
    status: 'error' as const,
  },
  mobile: {
    ...defaultProps,
    id: 'preview-application-mobile',
    isMobile: true,
  },
};
