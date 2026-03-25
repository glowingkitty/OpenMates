/**
 * Docs index page — prerender + SSR config for SEO.
 * Docs content is statically bundled at build time in docs-data.json,
 * so full prerendering is possible and desirable for search engine indexing.
 */
export const prerender = true;
export const ssr = true;
