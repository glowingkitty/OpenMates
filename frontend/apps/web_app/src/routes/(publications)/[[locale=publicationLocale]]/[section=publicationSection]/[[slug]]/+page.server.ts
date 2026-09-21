import type { PageServerLoad } from './$types';
import { loadPublicationPage } from '$lib/server/publications';
import type { PublicPublicationLocale, PublicPublicationSection } from '$lib/publications/types';

export const load: PageServerLoad = async ({ params, setHeaders, url }) => {
	setHeaders({
		'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400'
	});

	return loadPublicationPage({
		locale: (params.locale === 'de' ? 'de' : 'en') as PublicPublicationLocale,
		section: params.section as PublicPublicationSection,
		slug: params.slug ?? null,
		url
	});
};
