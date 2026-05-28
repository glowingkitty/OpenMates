/**
 * Test recording browser route configuration.
 *
 * The /tests pages are dev-only operational tooling and fetch short-lived
 * recording URLs from the API. SSR is disabled so production can be blocked
 * by the client-side hostname gate before any recording requests are made.
 */
export const ssr = false;
export const prerender = false;
