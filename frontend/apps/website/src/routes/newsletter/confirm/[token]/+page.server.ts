import type { PageServerLoad } from './$types';
import { newsletterApiOrigin } from '$lib/server/origins';
import { signalGroupUrl } from '@repo/public-site/data/siteMetadata';
export const load: PageServerLoad = ({ params, url, request, setHeaders }) => {
  setHeaders({ 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'private, no-store' });
  const language: 'en' | 'de' = url.searchParams.get('lang') === 'de' || (!url.searchParams.has('lang') && request.headers.get('accept-language')?.toLowerCase().startsWith('de')) ? 'de' : 'en';
  return { apiBaseUrl: newsletterApiOrigin(url), signalUrl: signalGroupUrl, token: params.token, language };
};
