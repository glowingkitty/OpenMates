import { redirect, type Handle } from '@sveltejs/kit';
import { readLanguageCookie, resolveLanguage } from '@repo/public-site/languagePreference';

export const handle: Handle = async ({ event, resolve }) => {
  const preference = readLanguageCookie(event.request.headers.get('cookie') ?? '', event.url.hostname);
  event.locals.language = resolveLanguage({
    // Publication paths already encode their locale, including English's
    // unprefixed path. Keep article slugs and their canonical language aligned.
    urlLanguage: event.params.section ? event.params.locale ?? 'en' : event.url.searchParams.get('lang'),
    preference,
    browserLanguages: event.request.headers.get('accept-language'),
    supported: ['en', 'de'],
  }) as 'en' | 'de';
  event.locals.languageMode = preference?.mode ?? 'auto';
  const response = await resolve(event, {
    transformPageChunk: ({ html }) => html.replace('%openmates.language%', event.locals.language),
  });
  const { locale, section, slug } = event.params;
  // The shared publication loader recovers missing articles at their archive.
  // On the website, all broken page links should recover at the landing page.
  const missingPublication = slug && (section === 'blog' || section === 'news') &&
    response.status === 307 &&
    response.headers.get('location') === `${locale === 'de' ? '/de' : ''}/${section}`;
  const missingHtmlPage = response.status === 404 &&
    response.headers.get('content-type')?.startsWith('text/html');

  // Existing page routes can also fail, for example a removed article or legal document.
  // Preserve intentional non-HTML 404s from endpoints such as the development sitemap.
  if (
    (event.request.method === 'GET' || event.request.method === 'HEAD') &&
    (missingHtmlPage || missingPublication)
  ) {
    redirect(302, '/');
  }

  return response;
};
