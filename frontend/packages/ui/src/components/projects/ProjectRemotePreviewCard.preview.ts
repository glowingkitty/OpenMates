/**
 * Synthetic remote-file cards for the bare component preview gallery.
 * The fixture contains no real path or account data and never performs an upload.
 */
const completePreview = {
  isVirtual: true as const,
  persistAsEmbed: false as const,
  embed: {
    embed_id: 'remote:preview-source:src/example.ts',
    type: 'code-code' as const,
    status: 'finished' as const,
    content: {
      type: 'remote_file_preview',
      source_id: 'preview-source',
      path: 'src/example.ts',
      display_name: 'example.ts',
      kind: 'file' as const,
      language: 'typescript',
      snippet: 'export const greeting = "hello";\n',
      snippet_truncated: false,
      size_bytes: 33,
      line_count: 1,
      preview_policy: 'bounded_full_text',
      safety_flags: [],
    },
  },
};

const defaultProps = {
  preview: completePreview,
  sourceLabel: 'Example repository',
  canUpload: true,
  isUploading: false,
  onOpenFullscreen: () => window.dispatchEvent(new CustomEvent('project-preview-action', { detail: 'open' })),
  onUpload: () => window.dispatchEvent(new CustomEvent('project-preview-action', { detail: 'import' })),
};

export default defaultProps;

export const variants = {
  truncated: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        embed_id: 'remote:preview-source:src/large-example.ts',
        content: {
          ...completePreview.embed.content,
          path: 'src/large-example.ts',
          display_name: 'large-example.ts',
          snippet: '// A safely bounded preview of a larger remote source file.\n',
          snippet_truncated: true,
          size_bytes: 250_000,
          line_count: 4_500,
          preview_policy: 'bounded_truncated_text',
          safety_flags: ['truncated'],
        },
      },
    },
    canUpload: false,
  },
  loadingImport: {
    ...defaultProps,
    isUploading: true,
  },
};
