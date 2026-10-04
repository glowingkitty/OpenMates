/** Focused parsed-message states for the read-only renderer. */
const defaultProps = {
  role: 'user' as const,
  content: 'A saved message.',
  chatId: '',
};

const markdownLookingFirstText = 'Synthetic storage reference. STORAGE_CAPACITY_SCENARIO:round';
const codeEmbed = {
  type: 'embed',
  attrs: {
    id: 'd1acb994-29fd-48d8-9920-c6a8e990d6d3',
    type: 'code-code',
    status: 'finished',
    // GroupRenderer resolves inline code only for preview references. This
    // static form avoids the editor's auto-upgrade path used by preview:code:.
    contentRef: 'preview:read-only-code',
    language: 'js',
    code: 'const saved = 1;',
    filename: 'saved.js',
  },
};

export default defaultProps;

export const variants = {
  parsedCode: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: markdownLookingFirstText }] },
        { type: 'paragraph', content: [codeEmbed] },
      ],
    },
  },
  parsedParagraphs: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: markdownLookingFirstText }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'Later saved paragraph.' }] },
      ],
    },
  },
  parsedInline: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [{
        type: 'paragraph',
        content: [
          { type: 'text', text: markdownLookingFirstText },
          { type: 'text', text: ' with inline saved content.' },
        ],
      }],
    },
  },
  parsedMarkedSingle: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [{
        type: 'paragraph',
        content: [{
          type: 'text',
          text: markdownLookingFirstText,
          marks: [{ type: 'bold' }],
        }],
      }],
    },
  },
  legacySingleMarkdown: {
    ...defaultProps,
    content: {
      type: 'doc',
      content: [{
        type: 'paragraph',
        content: [{ type: 'text', text: '**Legacy saved markdown**' }],
      }],
    },
  },
};
