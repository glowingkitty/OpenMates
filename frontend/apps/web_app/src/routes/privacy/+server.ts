import { env } from '$env/dynamic/public';
import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

/** Preserve the legacy chat link until the standalone website is configured. */
export const GET: RequestHandler = () => {
  let target = '/#chat-id=legal-privacy';
  if (env.PUBLIC_LANDING_WEBSITE_URL) {
    try {
      const website = new URL(env.PUBLIC_LANDING_WEBSITE_URL);
      if (website.protocol === 'http:' || website.protocol === 'https:') {
        target = new URL('/legal/privacy', website.origin).href;
      }
    } catch {
      // A malformed optional origin cannot make the legacy privacy link fail.
    }
  }
  redirect(302, target);
};
