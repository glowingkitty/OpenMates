// frontend/apps/web_app/src/routes/s/+page.ts
//
// Client-only route config for the short URL redirect page.
// SSR must be disabled because the page reads window.location.hash
// which is not available server-side (fragments are never sent to servers).

export const ssr = false;
export const prerender = false;
