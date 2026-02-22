// frontend/apps/web_app/src/routes/(seo)/demo/chat/+page.ts
//
// Page options for the demo chat listing page at /demo/chat/.
//
// prerender=false: always SSR on request — the demo chat list changes over time and
// BACKEND_URL is not forwarded through Turborepo at Vercel build time, so prerendering
// would produce an empty page. SSR ensures crawlers always get live data.
// ssr=true: server-renders for crawlers (main purpose of this page).
// csr=true: client-side hydration fires the onMount redirect for human browsers.

// Never prerender — always SSR at request time so the backend is reachable.
export const prerender = false;

// SSR must be true — this page exists for crawlers that need server-rendered HTML.
export const ssr = true;

// CSR allows client-side hydration so the onMount redirect in +page.svelte fires.
export const csr = true;
