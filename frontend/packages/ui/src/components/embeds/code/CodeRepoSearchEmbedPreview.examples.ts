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
    "query": "svelte",
    "query_translation_key": "settings.app_store_examples.code.search_repos.1",
    "provider": "GitHub",
    "status": "finished",
    "resultCount": 1,
    "results": [{
      "url": "https://github.com/immich-app/immich",
      "html_url": "https://github.com/immich-app/immich",
      "full_name": "immich-app/immich",
      "owner_login": "immich-app",
      "owner_avatar_url": "https://avatars.githubusercontent.com/u/109746326?v=4",
      "name": "immich",
      "description": "High performance self-hosted photo and video management solution.",
      "visibility": "public",
      "private": false,
      "fork": false,
      "archived": false,
      "disabled": false,
      "is_template": false,
      "default_branch": "main",
      "primary_language": "TypeScript",
      "languages": [],
      "topics": [
        "backup-tool",
        "flutter",
        "google-photos",
        "google-photos-alternative",
        "javascript",
        "mobile-app",
        "nestjs",
        "nodejs",
        "photo-gallery",
        "photos",
        "photos-management",
        "self-hosted",
        "svelte",
        "sveltekit",
        "typescript",
        "videos"
      ],
      "license_name": "GNU Affero General Public License v3.0",
      "license_spdx_id": "AGPL-3.0",
      "stars": 101646,
      "forks": 5686,
      "watchers": 101646,
      "open_issues": 678,
      "created_at": "2022-02-03T15:56:27Z",
      "updated_at": "2026-05-24T20:27:06Z",
      "pushed_at": "2026-05-24T19:54:34Z",
      "latest_release_tag": null,
      "latest_release_name": null,
      "latest_release_published_at": null,
      "latest_commit_sha": null,
      "latest_commit_message": null,
      "latest_commit_date": null,
      "contributors": [],
      "site_name": "GitHub",
      "fetched_at": "2026-05-24T20:32:03.698378Z"
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
