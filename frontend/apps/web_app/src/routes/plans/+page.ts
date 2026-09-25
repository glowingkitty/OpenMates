/** Redirect the legacy Plans path to the shared root shell. */

import { redirect } from '@sveltejs/kit';

export function load() {
  throw redirect(307, '/#plans');
}
