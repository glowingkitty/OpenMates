// frontend/apps/web_app/src/routes/(seo)/events/+page.server.ts
//
// Server-side data loader for the public events index at /events. All events
// come from the shared static OpenMates event list; no backend fetch is needed.

import type { PageServerLoad } from './$types';
import { getAllOpenMatesEvents } from '@repo/ui';
import { getSiteOrigin } from '$lib/backendUrl';

function isDevelopmentHost(hostname: string): boolean {
	return hostname.includes('.dev.') ||
		hostname.startsWith('dev.') ||
		hostname.endsWith('.vercel.app') ||
		hostname === 'localhost' ||
		hostname === '127.0.0.1';
}

export const load: PageServerLoad = async ({ setHeaders, url }) => {
	setHeaders({
		'Cache-Control': 'public, s-maxage=86400, stale-while-revalidate=604800'
	});

	const siteOrigin = getSiteOrigin(url);
	const canonicalUrl = `${siteOrigin}/events`;
	const events = getAllOpenMatesEvents();
	const jsonLd = {
		'@context': 'https://schema.org',
		'@type': 'CollectionPage',
		'@id': `${canonicalUrl}#webpage`,
		name: 'OpenMates Events',
		description: 'Upcoming OpenMates community events and meetups.',
		url: canonicalUrl,
		mainEntity: {
			'@type': 'ItemList',
			itemListElement: events.map((event, index) => ({
				'@type': 'ListItem',
				position: index + 1,
				url: `${siteOrigin}/events/${event.slug}`,
				name: event.title
			}))
		},
		breadcrumb: {
			'@type': 'BreadcrumbList',
			itemListElement: [
				{
					'@type': 'ListItem',
					position: 1,
					name: 'OpenMates',
					item: siteOrigin
				},
				{
					'@type': 'ListItem',
					position: 2,
					name: 'Events',
					item: canonicalUrl
				}
			]
		}
	};

	return {
		events,
		canonicalUrl,
		jsonLd: JSON.stringify(jsonLd),
		isDevHost: isDevelopmentHost(url.hostname)
	};
};
