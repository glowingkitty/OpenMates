/** Redirect the retired Plans workspace to its replacement Tasks workspace. */

import { redirect } from '@sveltejs/kit';

export function load() {
  throw redirect(307, '/tasks');
}
