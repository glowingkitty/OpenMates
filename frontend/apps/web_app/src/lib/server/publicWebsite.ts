import { env } from '$env/dynamic/public';

/** Resolve legacy app URLs to their canonical standalone website destination. */
export function publicWebsiteOrigin(url: URL): string {
  if (env.PUBLIC_LANDING_WEBSITE_URL) {
    try {
      const configured = new URL(env.PUBLIC_LANDING_WEBSITE_URL);
      if (configured.protocol === 'https:' || configured.protocol === 'http:') return configured.origin;
    } catch { /* Use the matching deployed website when configuration is invalid. */ }
  }
  const development = url.hostname === 'localhost' || url.hostname === '127.0.0.1'
    || url.hostname.includes('.dev.') || url.hostname.startsWith('dev.') || url.hostname.endsWith('.vercel.app');
  return development ? 'https://landing.dev.openmates.org' : 'https://openmates.org';
}
