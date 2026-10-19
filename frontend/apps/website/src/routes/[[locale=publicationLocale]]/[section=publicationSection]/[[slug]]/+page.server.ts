import type { PageServerLoad } from './$types';
import { loadPublicationPage } from '@repo/public-site/publications/publications';
import type { PublicPublicationLocale, PublicPublicationSection } from '@repo/public-site/publications/types';
import { appOrigin } from '$lib/server/origins';

export const load: PageServerLoad = ({ params, locals, setHeaders, url }) => {
  const publication = loadPublicationPage({ locale: (params.locale === 'de' ? 'de' : 'en') as PublicPublicationLocale, section: params.section as PublicPublicationSection, slug: params.slug ?? null, url });
  setHeaders({ 'Cache-Control': 'private, no-store', Vary: 'Accept-Language, Cookie' });
  return { ...publication, appBaseUrl: appOrigin(url), languageMode: locals.languageMode };
};
