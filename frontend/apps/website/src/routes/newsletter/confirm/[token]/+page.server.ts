import type { PageServerLoad } from './$types';
import { newsletterApiOrigin } from '$lib/server/origins';
import { signalGroupUrl } from '@repo/public-site/data/siteMetadata';
export const load: PageServerLoad = ({ params, url, locals, setHeaders }) => {
  setHeaders({ 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'private, no-store' });
  const language = locals.language;
  return { apiBaseUrl: newsletterApiOrigin(url), signalUrl: signalGroupUrl, token: params.token, language };
};
