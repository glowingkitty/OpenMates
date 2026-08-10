/**
 * Workflow run-history route rendering policy.
 * The page depends on authenticated browser state and the shared workspace store.
 * Server rendering and prerendering stay disabled to match the detail route.
 * Spec: docs/specs/workflows-v1/spec.yml
 */

export const ssr = false;
export const prerender = false;
