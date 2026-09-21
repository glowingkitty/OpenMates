import type { NewsroomSurfaceData, NewsroomView } from '@repo/ui/components/newsroom/types';

export type PublicPublicationLocale = 'en' | 'de';
export type PublicPublicationSection = 'news' | 'blog' | 'social';

export interface PublicPublicationPageData {
	locale: PublicPublicationLocale;
	section: PublicPublicationSection;
	view: NewsroomView;
	selectedSlug: string | null;
	surface: NewsroomSurfaceData;
	linksById: Record<string, string>;
	indexUrl: string;
	canonicalUrl: string;
	alternateUrl: string;
	alternateLocale: PublicPublicationLocale;
	pageTitle: string;
	pageDescription: string;
	jsonLd: string;
	ogImage: string | null;
	isDevHost: boolean;
}

export interface PublicationSitemapEntry {
	path: string;
	alternatePath: string;
	locale: PublicPublicationLocale;
	lastModified: string;
}
