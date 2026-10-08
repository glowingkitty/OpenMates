import type { RequestHandler } from './$types';
import { getPublicationSitemapEntries } from '@repo/public-site/publications/publications';
import { isDevelopmentHost, siteOrigin } from '$lib/server/origins';
export const GET: RequestHandler = ({ url }) => {
  if (isDevelopmentHost(url)) return new Response('', { status: 404 });
  const origin = siteOrigin(url);
  const paths = ['/', '/legal/privacy', '/legal/terms', '/legal/imprint', ...getPublicationSitemapEntries().map(entry => entry.path)];
  const body = `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${paths.map(path => `<url><loc>${origin}${path}</loc></url>`).join('')}</urlset>`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
