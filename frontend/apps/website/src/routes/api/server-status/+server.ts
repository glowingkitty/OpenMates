import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { newsletterApiOrigin } from '$lib/server/origins';

/** Fresh public availability only; no visitor identity or incoming credentials are forwarded. */
export const GET: RequestHandler = async ({ url }) => {
  let available = false;
  try {
    const response = await fetch(`${newsletterApiOrigin(url)}/v1/settings/server-status`, {
      credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(3000),
    });
    if (response.ok) {
      const status = await response.json();
      const usage = status?.anonymous_free_usage;
      available = usage?.active === true && usage?.can_send_text !== false;
    }
  } catch { /* Conservative fallback when the API is unavailable. */ }
  return json({ anonymous_free_usage: { active: available, can_send_text: available } }, {
    headers: { 'Cache-Control': 'no-store' },
  });
};
