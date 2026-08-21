// frontend/apps/web_app/src/routes/(seo)/events/+page.ts
//
// Prerender configuration for the public events index. This route is static and
// crawlable so Google can use its titles, headings, and internal links as
// stronger sitelink candidates than SPA interest labels.

export const prerender = true;
export const ssr = true;
export const csr = true;
