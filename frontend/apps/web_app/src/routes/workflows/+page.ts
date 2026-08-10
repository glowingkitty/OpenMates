/**
 * Workflows route rendering configuration.
 *
 * The Workflows workspace reuses authenticated web app stores and browser-only
 * storage/crypto services from the shared UI package. Keep the index route
 * client-rendered so Vercel does not execute those services during SSR.
 * Spec: docs/specs/workflows-v1/spec.yml
 */
export const ssr = false;
export const csr = true;
export const prerender = true;
