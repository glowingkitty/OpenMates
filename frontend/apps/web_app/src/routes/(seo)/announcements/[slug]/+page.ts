// frontend/apps/web_app/src/routes/(seo)/announcements/[slug]/+page.ts
//
// SSR configuration for individual announcement newsletter pages.
// Server-rendered on each request so crawlers and link-preview bots
// get a fully-rendered page with correct meta tags.

export const prerender = false;
export const ssr = true;
export const csr = true;
