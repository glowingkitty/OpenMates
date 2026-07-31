/**
 * Legacy Project detail redirect loader.
 *
 * Projects now keep the authenticated shell mounted at /projects and store the
 * selected project in hash state, matching Workflows. This server-side redirect
 * keeps direct nested links deterministic before the Svelte component hydrates.
 */

import { redirect } from '@sveltejs/kit';

export function load({ params }: { params: { project_id?: string } }) {
  throw redirect(307, `/projects#project-id=${encodeURIComponent(params.project_id ?? '')}`);
}
