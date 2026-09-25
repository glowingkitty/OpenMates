/**
 * Legacy Workflow run-history route.
 * Run history now lives in the root app shell's hash state.
 * Spec: docs/specs/workflows-v1/spec.yml
 */

import { redirect } from '@sveltejs/kit';

export const ssr = false;
export const prerender = false;

export function load({ params }: { params: { workflow_id?: string } }) {
	throw redirect(
		307,
		`/#workflow-id=${encodeURIComponent(params.workflow_id ?? '')}&workflow-tab=runs`
	);
}
