/**
 * Workflow detail route rendering policy.
 * Workflow metadata requires authenticated browser state and client stores.
 * Server rendering and prerendering are disabled to match the workspace route.
 * Spec: docs/specs/workflows-v1/spec.yml
 */

export const ssr = false;
export const prerender = false;
