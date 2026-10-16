import type { RequestHandler } from './$types';
import { isDevelopmentHost, siteOrigin } from '$lib/server/origins';
export const GET: RequestHandler = ({ url }) => new Response(isDevelopmentHost(url)
  ? 'User-agent: *\nDisallow: /\n'
  : `User-agent: *\nAllow: /\nSitemap: ${siteOrigin(url)}/sitemap.xml\n`, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
