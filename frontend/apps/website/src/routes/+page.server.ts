import type { PageServerLoad } from './$types';
import { loadPublicationPage } from '@repo/public-site/publications/publications';
import { getUpcomingOpenMatesEventCards } from '@repo/public-site/data/events';
import { siteOrigin, appOrigin, newsletterApiOrigin, isDevelopmentHost } from '$lib/server/origins';
import type { LandingPublication } from '@repo/public-site/components/landing/landingPageContent';

export const load: PageServerLoad = ({ url, setHeaders }) => {
  setHeaders({ 'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400' });
  const websiteBaseUrl = siteOrigin(url);
  const appBaseUrl = appOrigin(url);
  const news = loadPublicationPage({ locale: 'en', section: 'news', slug: null, url });
  const blog = loadPublicationPage({ locale: 'en', section: 'blog', slug: null, url });
  const cards = (items: typeof news.surface.newsItems, links: Record<string,string>): LandingPublication[] => items.slice(0, 2).map(item => ({
    id: item.id, title: item.title, description: item.excerpt,
    href: `${websiteBaseUrl}${links[item.id]}`, image: item.media?.posterUrl ?? (item.media?.type === 'image' ? item.media.url : undefined), label: item.publishedLabel
  }));
  return {
    appBaseUrl, websiteBaseUrl, apiBaseUrl: newsletterApiOrigin(url),
    events: getUpcomingOpenMatesEventCards(new Date(), appBaseUrl),
    news: cards(news.surface.newsItems, news.linksById),
    posts: cards(blog.surface.blogItems, blog.linksById),
    canonicalUrl: `${websiteBaseUrl}/`, isDevHost: isDevelopmentHost(url)
  };
};
