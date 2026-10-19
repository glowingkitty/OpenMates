import { redirect, type Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
  const response = await resolve(event);
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
