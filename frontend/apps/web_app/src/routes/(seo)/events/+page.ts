// frontend/apps/web_app/src/routes/(seo)/events/+page.ts
//
// SSR configuration for the public events index. This route is crawlable and
// intentionally JavaScript-free so Google can use its titles, headings, and
// internal links as stronger sitelink candidates than SPA interest labels.

export const prerender = false;
export const ssr = true;
export const csr = false;
