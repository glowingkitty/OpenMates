import { env } from '$env/dynamic/public';
import { env as serverEnv } from '$env/dynamic/private';
import { getUpcomingOpenMatesEventCards } from '@repo/public-site/data/events';
import type { NewsroomItem } from '@repo/ui/components/newsroom/types';
import type { LandingPublication } from '@repo/ui/components/landing/landingPageContent';
import { getLandingOrigins } from '$lib/landingOrigins';
import { getBackendUrl } from '$lib/backendUrl';
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
	const events = getUpcomingOpenMatesEventCards(new Date(), origins.appBaseUrl);
	return {
		...origins,
		apiBaseUrl: env.PUBLIC_API_URL || serverEnv.VITE_API_URL || getBackendUrl(url),
		news: publicationPage?.surface.newsItems.slice(0, 2).map(toCard) ?? [],
		posts: publicationPage?.surface.blogItems.slice(0, 2).map(toCard) ?? [],
		events,
		canonicalUrl: `${origins.websiteBaseUrl}/landing`,
		isDevHost: url.hostname !== 'openmates.org'
	};
};
