// frontend/apps/web_app/src/routes/(seo)/events/[slug]/+page.server.ts
//
// Server-side loader for public OpenMates event pages at /events/{slug}.
// The visible page is crawlable and exposes schema.org/Event JSON-LD.
// Human browsers are forwarded to the interactive SPA embed fullscreen on mount.

import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { getOpenMatesEventBySlug } from '@repo/ui';
import { getSiteOrigin } from '$lib/backendUrl';

function isDevelopmentHost(hostname: string): boolean {
	return hostname.includes('.dev.') ||
		hostname.startsWith('dev.') ||
		hostname.endsWith('.vercel.app') ||
		hostname === 'localhost' ||
		hostname === '127.0.0.1';
}

export const load: PageServerLoad = async ({ params, setHeaders, url }) => {
	const event = getOpenMatesEventBySlug(params.slug);
	if (!event) {
		error(404, 'Event not found');
	}

	setHeaders({
		'Cache-Control': 'public, s-maxage=86400, stale-while-revalidate=604800'
	});

	const siteOrigin = getSiteOrigin(url);
	const canonicalUrl = `${siteOrigin}/events/${event.slug}`;
	const location = `${event.venue.name}, ${event.venue.address}, ${event.venue.city}, ${event.venue.country}`;
	const jsonLd = {
		'@context': 'https://schema.org',
		'@type': 'Event',
		name: event.title,
		description: event.summary,
		startDate: event.date_start,
		endDate: event.date_end,
		eventAttendanceMode: 'https://schema.org/OfflineEventAttendanceMode',
		eventStatus: 'https://schema.org/EventScheduled',
		image: [event.image_url],
		url: canonicalUrl,
		organizer: {
			'@type': 'Organization',
			name: event.organizer.name,
			url: `${siteOrigin}/events/${event.slug}`
		},
		location: {
			'@type': 'Place',
			name: event.venue.name,
			address: {
				'@type': 'PostalAddress',
				streetAddress: event.venue.address,
				addressLocality: event.venue.city,
				addressCountry: event.venue.country
			},
			geo: {
				'@type': 'GeoCoordinates',
				latitude: event.venue.lat,
				longitude: event.venue.lon
			}
		},
		offers: {
			'@type': 'Offer',
			url: event.url,
			price: '0',
			priceCurrency: 'EUR',
			availability: 'https://schema.org/InStock'
		}
	};

	return {
		event,
		canonicalUrl,
		location,
		jsonLd: JSON.stringify(jsonLd),
		isDevHost: isDevelopmentHost(url.hostname),
		spaUrl: `${siteOrigin}/#embed-id=${encodeURIComponent(event.embed_id)}`
	};
};
