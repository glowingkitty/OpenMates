import rawManifest from '../publications/publicationManifest.v1.json';

type ManifestLocale = 'en' | 'de';
type ManifestKind = 'blog' | 'social';
type SocialPlatform = 'bluesky' | 'instagram' | 'mastodon';

export interface PublicManifestCopy {
	title: string;
	description: string;
	bodyMarkdown: string;
}

export interface PublicManifestRecord {
	id: string;
	slug: string;
	kind: ManifestKind;
	publishedAt: string;
	updatedAt: string;
	author: string;
	locales: Partial<Record<ManifestLocale, PublicManifestCopy>>;
	media?: {
		type: 'image' | 'video';
		url: string;
		alt: string;
		posterUrl?: string;
	};
	socialLinks?: Array<{
		platform: SocialPlatform;
		label: string;
		href: string;
	}>;
}

export interface PublicPublicationManifest {
	schemaVersion: 1;
	revision: string;
	generatedAt: string;
	publications: PublicManifestRecord[];
}

const ROOT_KEYS = new Set(['schemaVersion', 'revision', 'generatedAt', 'publications']);
const RECORD_KEYS = new Set(['id', 'slug', 'kind', 'publishedAt', 'updatedAt', 'author', 'locales', 'media', 'socialLinks']);
const COPY_KEYS = new Set(['title', 'description', 'bodyMarkdown']);
const MEDIA_KEYS = new Set(['type', 'url', 'alt', 'posterUrl']);
const SOCIAL_LINK_KEYS = new Set(['platform', 'label', 'href']);
const MEDIA_HOSTS = new Set(['openmates-buffer-media.nbg1.your-objectstorage.com']);
const PLATFORM_HOSTS: Record<SocialPlatform, Set<string>> = {
	bluesky: new Set(['bsky.app']),
	instagram: new Set(['instagram.com', 'www.instagram.com']),
	mastodon: new Set(['mastodon.social'])
};

function objectValue(value: unknown, label: string): Record<string, unknown> {
	if (!value || typeof value !== 'object' || Array.isArray(value)) {
		throw new Error(`${label} must be an object`);
	}
	return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, allowed: Set<string>, label: string): void {
	for (const key of Object.keys(value)) {
		if (!allowed.has(key)) throw new Error(`${label} contains non-public field: ${key}`);
	}
}

function requiredString(value: unknown, label: string): string {
	if (typeof value !== 'string' || !value.trim()) throw new Error(`${label} must be a non-empty string`);
	return value;
}

function isoDate(value: unknown, label: string): string {
	const parsed = requiredString(value, label);
	if (!/^\d{4}-\d{2}-\d{2}T/.test(parsed) || Number.isNaN(Date.parse(parsed))) {
		throw new Error(`${label} must be an ISO date`);
	}
	return parsed;
}

function safeUrl(value: unknown, label: string, hosts: Set<string>): string {
	const input = requiredString(value, label);
	if (label.includes('.media.') && /^\/publications\/social\/[a-z0-9][a-z0-9.-]+$/i.test(input)) {
		return input;
	}
	const parsed = new URL(input);
	if (parsed.protocol !== 'https:' || !hosts.has(parsed.hostname)) {
		throw new Error(`${label} must use an approved HTTPS host`);
	}
	return parsed.href;
}

function parseCopy(value: unknown, label: string): PublicManifestCopy {
	const copy = objectValue(value, label);
	exactKeys(copy, COPY_KEYS, label);
	return {
		title: requiredString(copy.title, `${label}.title`),
		description: requiredString(copy.description, `${label}.description`),
		bodyMarkdown: requiredString(copy.bodyMarkdown, `${label}.bodyMarkdown`)
	};
}

function parseRecord(value: unknown, index: number): PublicManifestRecord {
	const label = `publications[${index}]`;
	const record = objectValue(value, label);
	exactKeys(record, RECORD_KEYS, label);
	const kind = requiredString(record.kind, `${label}.kind`);
	if (kind !== 'blog' && kind !== 'social') throw new Error(`${label}.kind is unsupported`);
	const localesValue = objectValue(record.locales, `${label}.locales`);
	exactKeys(localesValue, new Set(['en', 'de']), `${label}.locales`);
	const locales: PublicManifestRecord['locales'] = {};
	for (const locale of ['en', 'de'] as const) {
		if (localesValue[locale]) locales[locale] = parseCopy(localesValue[locale], `${label}.locales.${locale}`);
	}
	if (!locales.en) throw new Error(`${label} requires an English source locale`);

	let media: PublicManifestRecord['media'];
	if (record.media) {
		const mediaValue = objectValue(record.media, `${label}.media`);
		exactKeys(mediaValue, MEDIA_KEYS, `${label}.media`);
		const type = requiredString(mediaValue.type, `${label}.media.type`);
		if (type !== 'image' && type !== 'video') throw new Error(`${label}.media.type is unsupported`);
		media = {
			type,
			url: safeUrl(mediaValue.url, `${label}.media.url`, MEDIA_HOSTS),
			alt: requiredString(mediaValue.alt, `${label}.media.alt`),
			...(mediaValue.posterUrl
				? { posterUrl: safeUrl(mediaValue.posterUrl, `${label}.media.posterUrl`, MEDIA_HOSTS) }
				: {})
		};
	}

	let socialLinks: PublicManifestRecord['socialLinks'];
	if (record.socialLinks) {
		if (!Array.isArray(record.socialLinks)) throw new Error(`${label}.socialLinks must be an array`);
		socialLinks = record.socialLinks.map((entry, linkIndex) => {
			const linkLabel = `${label}.socialLinks[${linkIndex}]`;
			const link = objectValue(entry, linkLabel);
			exactKeys(link, SOCIAL_LINK_KEYS, linkLabel);
			const platform = requiredString(link.platform, `${linkLabel}.platform`) as SocialPlatform;
			if (!(platform in PLATFORM_HOSTS)) throw new Error(`${linkLabel}.platform is unsupported`);
			return {
				platform,
				label: requiredString(link.label, `${linkLabel}.label`),
				href: safeUrl(link.href, `${linkLabel}.href`, PLATFORM_HOSTS[platform])
			};
		});
	}
	if (kind === 'social' && !socialLinks?.length) throw new Error(`${label} requires an original social permalink`);

	return {
		id: requiredString(record.id, `${label}.id`),
		slug: requiredString(record.slug, `${label}.slug`),
		kind,
		publishedAt: isoDate(record.publishedAt, `${label}.publishedAt`),
		updatedAt: isoDate(record.updatedAt, `${label}.updatedAt`),
		author: requiredString(record.author, `${label}.author`),
		locales,
		...(media ? { media } : {}),
		...(socialLinks ? { socialLinks } : {})
	};
}

export function parsePublicPublicationManifest(value: unknown): PublicPublicationManifest {
	const root = objectValue(value, 'manifest');
	exactKeys(root, ROOT_KEYS, 'manifest');
	if (root.schemaVersion !== 1) throw new Error('manifest.schemaVersion must be 1');
	if (!Array.isArray(root.publications)) throw new Error('manifest.publications must be an array');
	const publications = root.publications.map(parseRecord);
	const ids = new Set<string>();
	const slugs = new Set<string>();
	for (const publication of publications) {
		if (ids.has(publication.id)) throw new Error(`duplicate publication id: ${publication.id}`);
		if (slugs.has(publication.slug)) throw new Error(`duplicate publication slug: ${publication.slug}`);
		ids.add(publication.id);
		slugs.add(publication.slug);
	}
	return {
		schemaVersion: 1,
		revision: requiredString(root.revision, 'manifest.revision'),
		generatedAt: isoDate(root.generatedAt, 'manifest.generatedAt'),
		publications
	};
}

export const publicPublicationManifest = parsePublicPublicationManifest(rawManifest);
