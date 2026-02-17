/**
 * Dev tools layout configuration — client-side only.
 *
 * All routes under /dev/ are dev-only tools (component preview, etc.)
 * that rely on browser-only APIs like import.meta.glob and dynamic
 * component loading. SSR is disabled so these routes always render
 * client-side.
 *
 * NOTE: This alone does not fix the Vercel 404 problem.
 * adapter-vercel needs the Vercel rewrite in vercel.json to serve
 * the SPA shell HTML for /dev/* paths, since there is no prerendered
 * HTML and no SSR handler for these routes.
 * See vercel.json: { "source": "/dev/:path*", "destination": "/" }
 */
export const ssr = false;
export const prerender = false;
