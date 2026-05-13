// frontend/apps/web_app/src/routes/(seo)/events/[slug]/+page.ts
//
// SSR configuration for public event SEO pages. Event pages are server-rendered
// so crawlers and link-preview bots receive canonical metadata and Event
// structured data before the browser forwards humans into the SPA embed view.

export const prerender = false;
export const ssr = true;
export const csr = true;
