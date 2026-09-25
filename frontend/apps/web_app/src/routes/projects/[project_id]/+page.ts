/**
 * Legacy Project detail redirect loader.
 *
 * Projects now keep the root authenticated shell mounted and store the selected
 * project in hash state, matching Workflows. This server-side redirect
 * keeps direct nested links deterministic before the Svelte component hydrates.
 */

import { redirect } from '@sveltejs/kit';

export function load({ params }: { params: { project_id?: string } }) {
  throw redirect(307, `/#project-id=${encodeURIComponent(params.project_id ?? '')}`);
}
