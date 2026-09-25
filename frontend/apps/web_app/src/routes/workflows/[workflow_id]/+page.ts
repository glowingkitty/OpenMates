/**
 * Legacy Workflow detail route.
 * Workflow details now live in the root app shell's hash state. Redirect old
 * nested links before loading authenticated browser state.
 * Spec: docs/specs/workflows-v1/spec.yml
 */

import { redirect } from '@sveltejs/kit';

export const ssr = false;
export const prerender = false;

export function load({ params }: { params: { workflow_id?: string } }) {
	throw redirect(307, `/#workflow-id=${encodeURIComponent(params.workflow_id ?? '')}`);
}
