import type { PageServerLoad } from './$types';
import { loadPublicationPage } from '@repo/public-site/publications/publications';
import type { PublicPublicationLocale, PublicPublicationSection } from '@repo/public-site/publications/types';
import { appOrigin } from '$lib/server/origins';

export const load: PageServerLoad = ({ params, setHeaders, url }) => {
  setHeaders({ 'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400' });
  return { ...loadPublicationPage({ locale: (params.locale === 'de' ? 'de' : 'en') as PublicPublicationLocale, section: params.section as PublicPublicationSection, slug: params.slug ?? null, url }), appBaseUrl: appOrigin(url) };
};
