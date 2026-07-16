/**
 * Privacy PII short-link route.
 *
 * Redirects before the client app boots so settings receives the hash-only
 * deep link during initial startup. Keeping the destination in the fragment
 * avoids sending the selected settings page through query parameters.
 */

import { redirect } from '@sveltejs/kit';

export function load(): never {
  redirect(307, '/#settings/privacy/pii');
}
