import { env } from '$env/dynamic/public';
import { getLandingOrigins } from '$lib/landingOrigins';
import type { PageServerLoad } from './$types';
import { loadPublicationPage } from '$lib/server/publications';
import type { PublicPublicationLocale, PublicPublicationSection } from '$lib/publications/types';

export const load: PageServerLoad = async ({ params, setHeaders, url }) => {
	setHeaders({
		'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400'
	});

	return {
		...getLandingOrigins(url, {
			webapp: env.PUBLIC_LANDING_WEBAPP_URL,
			website: env.PUBLIC_LANDING_WEBSITE_URL
		}),
		...loadPublicationPage({
			locale: (params.locale === 'de' ? 'de' : 'en') as PublicPublicationLocale,
			section: params.section as PublicPublicationSection,
			slug: params.slug ?? null,
			url
		})
	};
};
