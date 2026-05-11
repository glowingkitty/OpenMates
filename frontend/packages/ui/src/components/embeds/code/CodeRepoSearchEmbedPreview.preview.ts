/**
 * Preview mock data for CodeRepoSearchEmbedPreview.
 */

const defaultProps = {
  id: 'preview-code-search-repos-1',
  query: 'svelte markdown editor',
  provider: 'GitHub',
  status: 'finished' as const,
  results: [
    {
      id: 0,
      results: [
        { full_name: 'sveltejs/svelte', url: 'https://github.com/sveltejs/svelte' },
        { full_name: 'markedjs/marked', url: 'https://github.com/markedjs/marked' }
      ]
    }
  ],
  isMobile: false,
  onFullscreen: () => {}
};

export default defaultProps;

export const variants = {
  processing: {
    id: 'preview-code-search-repos-processing',
    query: 'python cli framework',
    provider: 'GitHub',
    status: 'processing' as const,
    results: [],
    isMobile: false,
    onFullscreen: () => {}
  },
  empty: {
    id: 'preview-code-search-repos-empty',
    query: 'nonexistent repo topic',
    provider: 'GitHub',
    status: 'finished' as const,
    results: [],
    isMobile: false,
    onFullscreen: () => {}
  }
};
