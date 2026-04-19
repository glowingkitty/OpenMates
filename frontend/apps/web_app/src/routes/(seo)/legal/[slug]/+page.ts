// frontend/apps/web_app/src/routes/(seo)/legal/[slug]/+page.ts
//
// SSR configuration for legal document pages at /legal/{slug}.
// Server-rendered so crawlers and link-preview bots get OG tags.

export const prerender = false;
export const ssr = true;
export const csr = true;
