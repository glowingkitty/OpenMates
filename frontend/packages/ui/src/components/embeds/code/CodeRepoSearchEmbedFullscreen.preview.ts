/**
 * Preview mock data for CodeRepoSearchEmbedFullscreen.
 */

const defaultProps = {
  data: {
    decodedContent: {
      query: 'svelte markdown editor',
      provider: 'GitHub',
      results: [
        {
          id: 0,
          results: [
            {
              url: 'https://github.com/sveltejs/svelte',
              full_name: 'sveltejs/svelte',
              name: 'svelte',
              owner_login: 'sveltejs',
              description: 'Cybernetically enhanced web apps',
              primary_language: 'TypeScript',
              license_spdx_id: 'MIT',
              stars: 82000,
              forks: 4300,
              open_issues: 900,
              updated_at: '2026-05-01T00:00:00Z'
            }
          ]
        }
      ]
    },
    embedData: { status: 'finished' }
  },
  onClose: () => {}
};

export default defaultProps;
