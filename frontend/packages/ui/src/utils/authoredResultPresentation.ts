import { AUTHORED_RESULT_KIND_MAP } from '../data/embedRegistry.generated';
import type { AuthoredResultMetadata } from '../types/authoredResult';

export function authoredResultMetadata(content: Record<string, unknown>): AuthoredResultMetadata | undefined {
	const value = content.authoring;
	if (!value || typeof value !== 'object' || Array.isArray(value)) return;
	const metadata = value as AuthoredResultMetadata;
	if (typeof metadata.kind !== 'string' || !Object.prototype.hasOwnProperty.call(AUTHORED_RESULT_KIND_MAP, metadata.kind)) return;
	const identity = AUTHORED_RESULT_KIND_MAP[metadata.kind];
	if (!identity || metadata.schema_version !== 1 || !['draft', 'researched', 'user_provided'].includes(metadata.origin)
		|| !Array.isArray(metadata.sources) || content.app_id !== identity.appId
		|| content.type !== identity.backendType) return;
	return metadata;
}

/** Display links never acquire credentials or execute a URL scheme. */
export function authoredSourceUrl(value: unknown): string | undefined {
	if (typeof value !== 'string') return;
	try {
		const url = new URL(value);
		if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return;
		return url.href;
	} catch { return; }
}

/** Selected decrypted URLs belong only to this mounted view, never saved content. */
export function authoredResultMediaPresentation(content: Record<string, unknown>, selectedUrls: readonly string[]): Record<string, unknown> {
	const authoring = authoredResultMetadata(content);
	if (!authoring) return content;
	const kind = authoring.kind;
	const supplied = (authoring.images ?? []).map(image => authoredSourceUrl(typeof image === 'string' ? image : image?.url)).filter((url): url is string => !!url);
	const sourceImages = [
		...(Array.isArray(content.images) ? content.images : []),
		...(kind === 'home.listing' && Array.isArray(content.image_urls) ? content.image_urls : []),
	];
	const gallery = sourceImages.map(image => {
		if (typeof image === 'string') return authoredSourceUrl(image);
		if (!image || typeof image !== 'object') return;
		const entry = image as Record<string, unknown>;
		return authoredSourceUrl(entry.original_image ?? entry.url ?? entry.thumbnail);
	}).filter((url): url is string => !!url);
	const thumbnail = kind === 'travel.stay' ? authoredSourceUrl(content.thumbnail) : undefined;
	const urls = [...new Set([...selectedUrls, ...supplied, ...(thumbnail ? [thumbnail] : []), ...gallery])];
	if (!urls.length) return content;
	return { ...content, image_url: urls[0], cover_url: urls[0], poster_url: urls[0],
		thumbnail_url: urls[0],
		...(kind === 'models3d.model_result' ? { preview_image_url: urls[0] } : {}),
		...(kind === 'social_media.social_post' ? { media_url: urls[0] } : {}),
		...(kind === 'home.listing' ? { image_urls: [...urls] } : {}),
		...(kind === 'travel.stay' ? { thumbnail: urls[0] } : {}),
		...(kind === 'fitness.class' ? { class_image_url: urls[0] } : {}),
		...(kind === 'fitness.location' ? { venue_image_url: urls[0] } : {}),
		photos: [...urls], images: kind === 'travel.stay'
			? urls.map(url => ({ original_image: url, thumbnail: url })) : [...urls] };
}

/** Follow-up requests carry the record reference, without media transport keys. */
export function visibleAuthoredResult(value: unknown): unknown {
	if (typeof value === 'string') return value.startsWith('blob:') ? undefined : value;
	if (Array.isArray(value)) return value.map(visibleAuthoredResult).filter(item => item !== undefined);
	if (!value || typeof value !== 'object') return value;
	return Object.fromEntries(Object.entries(value).filter(([key]) =>
		key !== 'authored_media' && key !== 'source_json' && key !== 'authoring_reference_index'
		&& !/^(?:aes_|vault_wrapped_|encrypted_|s3_)/.test(key)
	).map(([key, field]) => [key, visibleAuthoredResult(field)]).filter(([, field]) => field !== undefined));
}
