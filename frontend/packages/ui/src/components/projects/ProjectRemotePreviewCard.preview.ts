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
  onOpenFullscreen: () => window.dispatchEvent(new CustomEvent('project-preview-action', { detail: 'open' })),
};

export default defaultProps;

export const variants = {
  pending: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        content: { ...completePreview.embed.content, snippet: '', size_bytes: 2048 },
      },
    },
  },
  sheet: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        embed_id: 'remote:preview-source:budget.xlsx',
        content: { ...completePreview.embed.content, path: 'budget.xlsx', display_name: 'budget.xlsx', snippet: '', size_bytes: 4096, preview_policy: 'unsupported_binary' },
      },
    },
  },
  plist: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        embed_id: 'remote:preview-source:Info.plist',
        content: { ...completePreview.embed.content, path: 'Info.plist', display_name: 'Info.plist', snippet: '', size_bytes: 1240 },
      },
    },
  },
  unsupported: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        embed_id: 'remote:preview-source:diagram.png',
        content: {
          ...completePreview.embed.content,
          path: 'diagram.png',
          display_name: 'diagram.png',
          snippet: '',
          preview_policy: 'unsupported_binary',
        },
      },
    },
  },
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
  },
  pythonPending: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        content: { ...completePreview.embed.content, path: 'src/main.py', display_name: 'main.py', language: 'python', snippet: '' },
      },
    },
  },
  yamlPending: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        content: { ...completePreview.embed.content, path: 'config.yml', display_name: 'config.yml', language: 'yaml', snippet: '' },
      },
    },
  },
  markdownPending: {
    ...defaultProps,
    preview: {
      ...completePreview,
      embed: {
        ...completePreview.embed,
        content: { ...completePreview.embed.content, path: 'README.md', display_name: 'README.md', language: 'markdown', snippet: '' },
      },
    },
  },
};
