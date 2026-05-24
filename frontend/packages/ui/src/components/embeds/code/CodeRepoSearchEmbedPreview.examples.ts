/**
 * App-store examples for the code/search_repos skill.
 *
 * Uses public GitHub repository metadata fetched from api.github.com for known
 * open-source projects. The shape matches the real GitHub provider response.
 */

export interface CodeRepoSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  status: 'finished';
  resultCount: number;
  results: Array<Record<string, unknown>>;
}

const examples: CodeRepoSearchStoreExample[] = [
  {
    "id": "store-example-code-search-repos-1",
    "query": "React UI library",
    "query_translation_key": "settings.app_store_examples.code.search_repos.1",
    "provider": "GitHub",
    "status": "finished",
    "resultCount": 1,
    "results": [{
      "url": "https://github.com/facebook/react",
      "html_url": "https://github.com/facebook/react",
      "full_name": "facebook/react",
      "owner_login": "facebook",
      "owner_avatar_url": "https://avatars.githubusercontent.com/u/69631?v=4",
      "name": "react",
      "description": "The library for web and native user interfaces.",
      "primary_language": "JavaScript",
      "license_name": "MIT License",
      "license_spdx_id": "MIT",
      "stars": 245247,
      "forks": 51098,
      "open_issues": 1308,
      "updated_at": "2026-05-24T17:47:10Z"
    }]
  },
  {
    "id": "store-example-code-search-repos-2",
    "query": "SvelteKit framework",
    "query_translation_key": "settings.app_store_examples.code.search_repos.2",
    "provider": "GitHub",
    "status": "finished",
    "resultCount": 1,
    "results": [{
      "url": "https://github.com/sveltejs/kit",
      "html_url": "https://github.com/sveltejs/kit",
      "full_name": "sveltejs/kit",
      "owner_login": "sveltejs",
      "owner_avatar_url": "https://avatars.githubusercontent.com/u/23617963?v=4",
      "name": "kit",
      "description": "web development, streamlined",
      "primary_language": "JavaScript",
      "license_name": "MIT License",
      "license_spdx_id": "MIT",
      "stars": 20529,
      "forks": 2255,
      "open_issues": 1018,
      "updated_at": "2026-05-24T16:35:57Z"
    }]
  },
  {
    "id": "store-example-code-search-repos-3",
    "query": "FastAPI framework",
    "query_translation_key": "settings.app_store_examples.code.search_repos.3",
    "provider": "GitHub",
    "status": "finished",
    "resultCount": 1,
    "results": [{
      "url": "https://github.com/fastapi/fastapi",
      "html_url": "https://github.com/fastapi/fastapi",
      "full_name": "fastapi/fastapi",
      "owner_login": "fastapi",
      "owner_avatar_url": "https://avatars.githubusercontent.com/u/156354296?v=4",
      "name": "fastapi",
      "description": "FastAPI framework, high performance, easy to learn, fast to code, ready for production",
      "primary_language": "Python",
      "license_name": "MIT License",
      "license_spdx_id": "MIT",
      "stars": 98485,
      "forks": 9340,
      "open_issues": 96,
      "updated_at": "2026-05-24T17:29:50Z"
    }]
  }
];

export default examples;
