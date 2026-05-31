/**
 * Projects route rendering configuration.
 *
 * Projects reuses the authenticated web app UI package, which depends on
 * browser-only storage and crypto services. Keep this route client-rendered
 * like the main app shell so Vercel does not execute those services during SSR.
 */
export const ssr = false;
export const csr = true;
export const prerender = true;
