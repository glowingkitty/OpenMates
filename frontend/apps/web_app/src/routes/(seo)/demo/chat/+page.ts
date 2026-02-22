// frontend/apps/web_app/src/routes/(seo)/demo/chat/+page.ts
//
// Page options for the demo chat listing page at /demo/chat/.
//
// prerender='auto': if all slugs are known at build time, prerender as static HTML.
// ssr=true: server-renders for crawlers (main purpose of this page).
// csr=true: client-side hydration fires the onMount redirect for human browsers.

// Use 'auto' so the page can be prerendered as a static file if no dynamic data
// is required. If the backend is unavailable at build time, SSR serves it on demand.
export const prerender = 'auto';

// SSR must be true — this page exists for crawlers that need server-rendered HTML.
export const ssr = true;

// CSR allows client-side hydration so the onMount redirect in +page.svelte fires.
export const csr = true;
