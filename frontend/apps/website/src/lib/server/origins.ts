import { env } from '$env/dynamic/public';

export function isDevelopmentHost(url: URL): boolean {
  return url.hostname === 'localhost' || url.hostname === '127.0.0.1' || url.hostname.includes('.dev.') || url.hostname.startsWith('dev.') || url.hostname.endsWith('.vercel.app');
}

export function siteOrigin(url: URL): string {
  if (env.PUBLIC_WEBSITE_URL) return env.PUBLIC_WEBSITE_URL.replace(/\/$/, '');
  if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return url.origin;
  return isDevelopmentHost(url) ? 'https://landing.dev.openmates.org' : 'https://openmates.org';
}

export function appOrigin(url: URL): string {
  if (env.PUBLIC_WEBAPP_URL) return env.PUBLIC_WEBAPP_URL.replace(/\/$/, '');
  if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:5173';
  return isDevelopmentHost(url) ? 'https://app.dev.openmates.org' : 'https://app.openmates.org';
}

export function newsletterApiOrigin(url: URL): string {
  if (env.PUBLIC_NEWSLETTER_API_BASE_URL) return env.PUBLIC_NEWSLETTER_API_BASE_URL.replace(/\/$/, '');
  if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:8000';
  return isDevelopmentHost(url) ? 'https://api.dev.openmates.org' : 'https://api.openmates.org';
}
