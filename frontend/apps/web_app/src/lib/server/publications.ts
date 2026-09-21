import { error } from '@sveltejs/kit';
import { getActiveNewsletterChatsByKind } from '@repo/ui/demo_chats';
import type {
	NewsroomArticleContent,
	NewsroomHero,
	NewsroomItem,
	NewsroomMediaSource,
	NewsroomSurfaceData,
	SocialPostLink
} from '@repo/ui/components/newsroom/types';
import {
	resolveI18nKeyForLocale,
	type ServerContentLocale
} from '@repo/ui/src/demo_chats/resolveI18nServer';
import type {
	PublicPublicationLocale,
	PublicPublicationPageData,
	PublicPublicationSection,
	PublicationSitemapEntry
} from '$lib/publications/types';
import { renderPublicationMarkdown } from './publicationMarkdown';
import { publicPublicationManifest } from './publicationManifest';

const RELEASE_SLUGS = new Set([
	'introducing-openmates-v09',
	'introducing-openmates-v010',
	'introducing-openmates-v011'
]);

const RELEASE_FALLBACK_MEDIA: NewsroomMediaSource = {
	type: 'image',
	url: '/publications/openmates-ui-fallback.png',
	alt: 'OpenMates web app showing the daily inspiration interface'
};

interface LocalizedCopy {
	title: string;
	description: string;
	bodyMarkdown: string;
}

interface PublicationRecord {
	id: string;
	slug: string;
	kind: 'release' | 'blog' | 'social' | 'coverage';
	copy: LocalizedCopy;
	publishedAt: string;
	updatedAt: string;
	author: string;
	media?: NewsroomMediaSource;
	socialLinks?: SocialPostLink[];
	externalUrl?: string;
}

function manifestRecords(
	kind: 'blog' | 'social',
	locale: PublicPublicationLocale
): PublicationRecord[] {
	return publicPublicationManifest.publications
		.filter((record) => record.kind === kind)
		.map((record) => ({
			id: record.id,
			slug: record.slug,
			kind,
			copy: record.locales[locale] ?? record.locales.en as LocalizedCopy,
			publishedAt: record.publishedAt,
			updatedAt: record.updatedAt,
			author: record.author,
			media: record.media,
			socialLinks: record.socialLinks
		}))
		.sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
}

const socialRecords = manifestRecords('social', 'en');

function formatDate(value: string, locale: PublicPublicationLocale): string {
	return new Intl.DateTimeFormat(locale === 'de' ? 'de-DE' : 'en-US', {
		dateStyle: 'long',
		timeZone: 'Europe/Berlin'
	}).format(new Date(value));
}

function publicationPath(locale: PublicPublicationLocale, section: PublicPublicationSection, slug?: string): string {
	const prefix = locale === 'de' ? '/de' : '';
	return `${prefix}/${section}${slug ? `/${slug}` : ''}`;
}

function newsRecords(locale: ServerContentLocale): PublicationRecord[] {
	return getActiveNewsletterChatsByKind('announcements')
		.filter((chat) => RELEASE_SLUGS.has(chat.slug) && Boolean(chat.metadata.publishedAt))
		.map((chat) => {
			const publishedAt = chat.metadata.publishedAt as string;
			const videoUrl = chat.metadata.video_mp4_url;
			const thumbnailUrl = chat.metadata.video_thumbnail_url;
			return {
				id: `news-${chat.slug}`,
				slug: chat.slug,
				kind: 'release' as const,
				copy: {
					title: resolveI18nKeyForLocale(chat.title, locale),
					description: resolveI18nKeyForLocale(chat.description, locale),
					bodyMarkdown: resolveI18nKeyForLocale(chat.messages[0]?.content ?? '', locale)
				},
				publishedAt,
				updatedAt: publishedAt,
				author: 'OpenMates',
				media: videoUrl
					? {
						type: 'video' as const,
						url: videoUrl,
						posterUrl: thumbnailUrl,
						alt: `${resolveI18nKeyForLocale(chat.title, locale)} video`
					}
					: thumbnailUrl
						? {
							type: 'image' as const,
							url: thumbnailUrl,
							alt: `${resolveI18nKeyForLocale(chat.title, locale)} screenshot`
						}
						: RELEASE_FALLBACK_MEDIA
			};
		})
		.sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
}

function blogRecords(locale: PublicPublicationLocale): PublicationRecord[] {
	return manifestRecords('blog', locale);
}

function coverageRecords(locale: PublicPublicationLocale): PublicationRecord[] {
	return [{
		id: 'coverage-zdf-privacy-alternatives',
		slug: 'zdf-privacy-alternatives',
		kind: 'coverage',
		copy: locale === 'de'
			? {
				title: 'Datenschutzfreundliche Alternativen zu Big-Tech-KI',
				description: 'Externer ZDF-Bericht – öffnet beim ursprünglichen Herausgeber.',
				bodyMarkdown: ''
			}
			: {
				title: 'Privacy-focused alternatives to big-tech AI',
				description: 'External ZDF report — opens at the original publisher.',
				bodyMarkdown: ''
			},
		publishedAt: '2025-12-28T12:00:00.000Z',
		updatedAt: '2025-12-28T12:00:00.000Z',
		author: 'ZDF',
		externalUrl: 'https://www.zdfheute.de/wirtschaft/39c3-hamburg-ki-alternativen-chatgpt-100.html'
	}];
}

function toItem(record: PublicationRecord, locale: PublicPublicationLocale): NewsroomItem {
	const kind = record.kind === 'release' ? 'release' : record.kind;
	const eyebrow = record.kind === 'release'
		? 'Release'
		: record.kind === 'blog'
			? (locale === 'de' ? 'Blogbeitrag' : 'Blog post')
			: record.kind === 'coverage'
				? 'ZDF · Germany'
				: 'OpenMates';
	return {
		id: record.id,
		kind,
		eyebrow,
		title: record.copy.title,
		excerpt: record.copy.description,
		bodyText: record.kind === 'social' ? record.copy.bodyMarkdown : undefined,
		publishedLabel: formatDate(record.publishedAt, locale),
		readTime: record.kind === 'blog' ? (locale === 'de' ? '4 Min. Lesezeit' : '4 min read') : undefined,
		author: record.author,
		language: record.kind === 'coverage' ? (locale === 'de' ? 'Deutsch' : 'German') : undefined,
		socialLinks: record.socialLinks?.map((link) => ({
			...link,
			label: locale === 'de'
				? `Diesen Beitrag auf ${link.platform === 'bluesky' ? 'Bluesky' : link.platform === 'instagram' ? 'Instagram' : 'Mastodon'} öffnen`
				: link.label
		})),
		media: record.media,
		mediaShape: record.kind === 'social' ? 'portrait' : record.media ? 'landscape' : 'none'
	};
}

function toHero(record: PublicationRecord, locale: PublicPublicationLocale): NewsroomHero {
	return {
		eyebrow: record.kind === 'blog' ? (locale === 'de' ? 'Blogbeitrag' : 'Blog post') : 'Release',
		kicker: record.kind === 'blog' ? (locale === 'de' ? 'Empfohlen' : 'Featured') : undefined,
		title: record.copy.title,
		meta: record.kind === 'blog'
			? `${formatDate(record.publishedAt, locale)} · ${locale === 'de' ? '4 Min. Lesezeit' : '4 min read'}`
			: formatDate(record.publishedAt, locale),
		actionLabel: record.kind === 'blog'
			? (locale === 'de' ? 'Blogbeitrag lesen' : 'Read the blog post')
			: (locale === 'de' ? 'Release lesen' : 'Read the release'),
		media: record.media
	};
}

function toArticle(record: PublicationRecord, locale: PublicPublicationLocale): NewsroomArticleContent {
	return {
		byline: record.kind === 'blog'
			? (locale === 'de' ? 'Marco\nGründer von OpenMates.' : 'Marco\nCreator of OpenMates.')
			: (locale === 'de' ? 'OpenMates Newsroom · Berlin' : 'OpenMates newsroom · Berlin, Germany'),
		publishedLabel: formatDate(record.publishedAt, locale),
		intro: record.copy.description,
		bodyHtml: renderPublicationMarkdown(record.copy.bodyMarkdown),
		media: record.media ? [record.media] : undefined
	};
}

const EMPTY_ARTICLE: NewsroomArticleContent = {
	byline: '',
	publishedLabel: '',
	intro: ''
};

function labels(locale: PublicPublicationLocale) {
	return locale === 'de'
		? {
			brand: 'OpenMates', newsLabel: 'Newsroom', blogLabel: 'Blog', openAppLabel: 'Web-App öffnen', tryItLabel: 'Ausprobieren', searchLabel: 'Suchen', latestNewsLabel: 'Neueste Meldungen', latestBlogLabel: 'Neueste Blogbeiträge', socialLabel: 'Social Media', coverageLabel: 'Pressestimmen', morePostsLabel: 'Weitere Beiträge', moreBlogPostsLabel: 'Weitere Blogbeiträge', pressKitLabel: 'Pressemappe herunterladen', pressInquiryLabel: 'Presseanfragen', subscribeLabel: 'News abonnieren', followLabel: 'Folge uns', emptyStateLabel: 'Keine passenden Beiträge.', showMoreLabel: 'Mehr anzeigen', copyLabel: 'Kopieren', previousMediaLabel: 'Vorheriges Medium', nextMediaLabel: 'Nächstes Medium', articleMediaLabel: 'Artikelmedium', closeSocialLabel: 'Social-Media-Beitrag schließen', originalPostNavLabel: 'Originalbeitrag öffnen', releaseContactLabel: 'Für weitere Fragen: press@openmates.org', blogContactLabel: 'Fragen oder Feedback? marco@openmates.org'
		}
		: {
			brand: 'OpenMates', newsLabel: 'Newsroom', blogLabel: 'Blog', openAppLabel: 'Open web app', tryItLabel: 'Try it out', searchLabel: 'Search', latestNewsLabel: 'Latest news', latestBlogLabel: 'Latest blog posts', socialLabel: 'Social media', coverageLabel: 'Press coverage', morePostsLabel: 'More posts', moreBlogPostsLabel: 'More blog posts', pressKitLabel: 'Download press kit', pressInquiryLabel: 'Press inquiries', subscribeLabel: 'Subscribe to news', followLabel: 'Follow us', emptyStateLabel: 'No matching posts.', showMoreLabel: 'Show more', copyLabel: 'Copy', previousMediaLabel: 'Previous media', nextMediaLabel: 'Next media', articleMediaLabel: 'Article media', closeSocialLabel: 'Close social post', originalPostNavLabel: 'Open original post', releaseContactLabel: 'For further questions, contact press@openmates.org', blogContactLabel: 'Questions or feedback? marco@openmates.org'
		};
}

function buildSurface(
	locale: PublicPublicationLocale,
	section: PublicPublicationSection,
	selectedSlug: string | null
): { surface: NewsroomSurfaceData; selected: PublicationRecord | null; linksById: Record<string, string> } {
	const news = newsRecords(locale);
	const blogs = blogRecords(locale);
	const coverage = coverageRecords(locale);
	const selectedPool = section === 'news' ? news : section === 'blog' ? blogs : socialRecords;
	const selected = selectedSlug ? selectedPool.find((record) => record.slug === selectedSlug) ?? null : null;
	if (selectedSlug && !selected) error(404, 'Publication not found');

	const orderedSocial = selected?.kind === 'social'
		? [selected, ...socialRecords.filter((record) => record.id !== selected.id)]
		: socialRecords;
	const activeNews = selected?.kind === 'release'
		? [selected, ...news.filter((record) => record.id !== selected.id)]
		: news;
	const activeBlogs = selected?.kind === 'blog'
		? [selected, ...blogs.filter((record) => record.id !== selected.id)]
		: blogs;
	const linksById: Record<string, string> = {};
	for (const record of news) linksById[record.id] = publicationPath(locale, 'news', record.slug);
	for (const record of blogs) linksById[record.id] = publicationPath(locale, 'blog', record.slug);
	for (const record of socialRecords) linksById[record.id] = publicationPath(locale, 'social', record.slug);
	for (const record of coverage) linksById[record.id] = record.externalUrl as string;

	const releaseArticle = selected?.kind === 'release'
		? toArticle(selected, locale)
		: EMPTY_ARTICLE;
	const blogArticle = selected?.kind === 'blog'
		? toArticle(selected, locale)
		: EMPTY_ARTICLE;
	return {
		selected,
		linksById,
		surface: {
			...labels(locale),
			heroNews: toHero(selected?.kind === 'release' ? selected : news[0], locale),
			heroBlog: blogs.length > 0
				? toHero(selected?.kind === 'blog' ? selected : blogs[0], locale)
				: null,
			newsItems: activeNews.map((record) => toItem(record, locale)),
			blogItems: activeBlogs.map((record) => toItem(record, locale)),
			socialItems: orderedSocial.map((record) => toItem(record, locale)),
			coverageItems: coverage.map((record) => toItem(record, locale)),
			releaseArticle,
			blogArticle
		}
	};
}

function isDevelopmentHostname(hostname: string): boolean {
	return hostname.includes('.dev.') || hostname.startsWith('dev.') || hostname.endsWith('.vercel.app') || hostname === 'localhost' || hostname === '127.0.0.1';
}

export function loadPublicationPage(args: {
	locale: PublicPublicationLocale;
	section: PublicPublicationSection;
	slug: string | null;
	url: URL;
}): PublicPublicationPageData {
	const { locale, section, slug, url } = args;
	if (section === 'social' && !slug) error(404, 'Social archive entries require a post slug');
	const { surface, selected, linksById } = buildSurface(locale, section, slug);
	const path = publicationPath(locale, section, slug ?? undefined);
	const alternateLocale: PublicPublicationLocale = locale === 'de' ? 'en' : 'de';
	const canonicalUrl = `${url.origin}${path}`;
	const alternateUrl = `${url.origin}${publicationPath(alternateLocale, section, slug ?? undefined)}`;
	const pageTitle = selected?.copy.title ?? (section === 'blog'
		? (locale === 'de' ? 'OpenMates Blog' : 'OpenMates Blog')
		: (locale === 'de' ? 'OpenMates Newsroom' : 'OpenMates Newsroom'));
	const pageDescription = selected?.copy.description ?? (section === 'blog'
		? (locale === 'de' ? 'Einblicke in den Aufbau nützlicher, datenschutzfreundlicher KI-Werkzeuge.' : 'Ideas and lessons from building useful, privacy-focused AI tools.')
		: (locale === 'de' ? 'Produkt-Releases, Updates, Pressestimmen und offizielle OpenMates-Beiträge.' : 'Product releases, updates, press coverage, and official OpenMates posts.'));
	const indexRecords = section === 'blog' ? blogRecords(locale) : newsRecords(locale);
	const previewRecord = selected ?? indexRecords[0];
	const titleCardSlugs = new Set(['privacy-as-a-product-feature', 'introducing-openmates-v011']);
	const selectedImage = previewRecord?.media?.posterUrl
		?? (previewRecord?.media?.type === 'image' ? previewRecord.media.url : null)
		?? (previewRecord && titleCardSlugs.has(previewRecord.slug)
			? `/publications/previews/${previewRecord.slug}-${locale}.jpg`
			: '/images/og-image.jpg');
	const selectedImageUrl = selectedImage ? new URL(selectedImage, url.origin).href : null;
	const jsonLd = selected
		? {
			'@context': 'https://schema.org',
			'@type': selected.kind === 'blog' ? 'BlogPosting' : selected.kind === 'social' ? 'SocialMediaPosting' : 'NewsArticle',
			headline: selected.copy.title,
			description: selected.copy.description,
			datePublished: selected.publishedAt,
			dateModified: selected.updatedAt,
			inLanguage: locale,
			author: selected.kind === 'blog'
				? { '@type': 'Person', name: 'Marco', url: `${url.origin}/intro/who-develops-openmates` }
				: { '@type': 'Organization', name: 'OpenMates', url: url.origin },
			publisher: { '@type': 'Organization', name: 'OpenMates', url: url.origin },
			mainEntityOfPage: { '@type': 'WebPage', '@id': canonicalUrl },
			articleBody: selected.copy.bodyMarkdown,
			...(selectedImageUrl ? { image: selectedImageUrl } : {}),
			...(selected.socialLinks ? { sameAs: selected.socialLinks.map((link) => link.href) } : {})
		}
		: {
			'@context': 'https://schema.org',
			'@type': 'CollectionPage',
			name: pageTitle,
			description: pageDescription,
			inLanguage: locale,
			url: canonicalUrl,
			mainEntity: {
				'@type': 'ItemList',
				itemListElement: indexRecords.map((record, index) => ({
					'@type': 'ListItem',
					position: index + 1,
					name: record.copy.title,
					url: `${url.origin}${publicationPath(locale, section, record.slug)}`
				}))
			}
		};

	return {
		locale,
		section,
		view: section === 'news' ? (slug ? 'release' : 'news') : section === 'blog' ? (slug ? 'blog-post' : 'blog') : 'social-post',
		selectedSlug: slug,
		surface,
		linksById,
		indexUrl: publicationPath(locale, section === 'social' ? 'news' : section),
		canonicalUrl,
		alternateUrl,
		alternateLocale,
		pageTitle,
		pageDescription,
		jsonLd: JSON.stringify(jsonLd),
		ogImage: selectedImageUrl,
		isDevHost: isDevelopmentHostname(url.hostname)
	};
}

export function getPublicationSitemapEntries(): PublicationSitemapEntry[] {
	const recordsBySection: Array<[PublicPublicationSection, PublicationRecord[]]> = [
		['news', newsRecords('en')],
		['blog', blogRecords('en')],
		['social', socialRecords]
	];
	const entries: PublicationSitemapEntry[] = [];
	for (const locale of ['en', 'de'] as const) {
		for (const section of ['news', 'blog'] as const) {
			entries.push({
				path: publicationPath(locale, section),
				alternatePath: publicationPath(locale === 'en' ? 'de' : 'en', section),
				locale,
				lastModified: '2026-09-21'
			});
		}
		for (const [section, records] of recordsBySection) {
			for (const record of records) {
				entries.push({
					path: publicationPath(locale, section, record.slug),
					alternatePath: publicationPath(locale === 'en' ? 'de' : 'en', section, record.slug),
					locale,
					lastModified: record.updatedAt.slice(0, 10)
				});
			}
		}
	}
	return entries;
}
