import { env } from '$env/dynamic/public';
import { getAllOpenMatesEvents } from '../../../../../../packages/ui/src/data/openmatesEvents';
import type { NewsroomItem } from '@repo/ui/components/newsroom/types';
import type { LandingPublication } from '@repo/ui/components/landing/landingPageContent';
import { getLandingOrigins } from '$lib/landingOrigins';
import { loadPublicationPage } from '$lib/server/publications';
import { isOfficialOpenMatesPublicationHost } from '$lib/server/publicationHosting';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url, setHeaders }) => {
	setHeaders({ 'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=3600' });
	const origins = getLandingOrigins(url, {
		webapp: env.PUBLIC_LANDING_WEBAPP_URL,
		website: env.PUBLIC_LANDING_WEBSITE_URL
	});
	// Reuse the same published records and destinations as the public newsroom.
	const publicationPage = isOfficialOpenMatesPublicationHost(new URL(origins.websiteBaseUrl).hostname) ? loadPublicationPage({
		locale: 'en', section: 'news', slug: null, url: new URL(origins.websiteBaseUrl)
	}) : null;
	const toCard = (item: NewsroomItem): LandingPublication => ({
		id: item.id, title: item.title, description: item.excerpt,
		href: new URL(publicationPage!.linksById[item.id], origins.websiteBaseUrl).href,
		image: item.media?.type === 'image' ? item.media.url : item.media?.posterUrl,
		label: item.publishedLabel
	});
	const now = Date.now();
	const events = getAllOpenMatesEvents()
		.filter((event) => !event.is_paid && Date.parse(event.date_end) >= now)
		.sort((a, b) => Date.parse(a.date_start) - Date.parse(b.date_start))
		.slice(0, 2)
		.map((event): LandingPublication => ({
			id: event.id, title: event.title, description: event.summary,
			href: `${origins.websiteBaseUrl}/events/${event.slug}`,
			image: event.image_url,
			label: new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeZone: 'Europe/Berlin' }).format(new Date(event.date_start))
		}));
	return {
		...origins,
		news: publicationPage?.surface.newsItems.slice(0, 2).map(toCard) ?? [],
		posts: publicationPage?.surface.blogItems.slice(0, 2).map(toCard) ?? [],
		events,
		canonicalUrl: `${origins.websiteBaseUrl}/landing`,
		isDevHost: url.hostname !== 'openmates.org'
	};
};
