/**
 * Batch embed content resolver for text rendering.
 *
 * Wraps the existing resolveEmbed() + decodeToonContent() pipeline into a
 * simple batch API that returns decoded content ready for renderEmbedAsText().
 *
 * Used by: tipTapToReadableMarkdown() in serializers.ts, zipExportService.ts
 */

import { resolveEmbed, decodeToonContent } from '../services/embedResolver';

/** Resolved embed with decoded content ready for text rendering */
export interface ResolvedEmbedContent {
	type: string;
	appId: string | null;
	skillId: string | null;
	content: Record<string, unknown>;
	/** Child embed IDs for composite embeds (pipe-separated or array) */
	childEmbedIds: string[];
}

/**
 * Parse embed_ids field which can be a pipe-separated string or an array.
 */
function parseEmbedIds(raw: unknown): string[] {
	if (typeof raw === 'string') return raw.split('|').filter(Boolean);
	if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
	return [];
}

/**
 * Resolve a single embed ID to its decoded content.
 *
 * @param embedId - The embed ID (bare UUID or "embed:uuid" prefix)
 * @returns Resolved content or null if unavailable
 */
export async function resolveEmbedContent(
	embedId: string
): Promise<ResolvedEmbedContent | null> {
	const embedData = await resolveEmbed(embedId);
	if (!embedData) return null;

	const decoded = await decodeToonContent(embedData.content);
	if (!decoded || typeof decoded !== 'object') return null;

	const content = decoded as Record<string, unknown>;

	return {
		type: embedData.type ?? (content.type as string) ?? '',
		appId: (content.app_id as string) ?? null,
		skillId: (content.skill_id as string) ?? null,
		content,
		childEmbedIds: parseEmbedIds(
			embedData.embed_ids ?? content.embed_ids
		)
	};
}

/**
 * Batch-resolve multiple embed IDs to their decoded content.
 * Resolves in parallel. Failed resolutions are silently excluded.
 *
 * @param embedIds - Array of embed IDs to resolve
 * @returns Map from embed_id to resolved content
 */
export async function resolveEmbedContents(
	embedIds: string[]
): Promise<Map<string, ResolvedEmbedContent>> {
	const results = new Map<string, ResolvedEmbedContent>();
	if (embedIds.length === 0) return results;

	const settled = await Promise.allSettled(
		embedIds.map(async (id) => {
			const resolved = await resolveEmbedContent(id);
			return { id, resolved };
		})
	);

	for (const result of settled) {
		if (result.status === 'fulfilled' && result.value.resolved) {
			const bareId = result.value.id.startsWith('embed:')
				? result.value.id.slice('embed:'.length)
				: result.value.id;
			results.set(bareId, result.value.resolved);
		}
	}

	return results;
}

/**
 * Resolve child embeds for a composite embed.
 * Returns an array of decoded content objects for each child.
 *
 * @param childEmbedIds - Array of child embed IDs
 * @returns Array of decoded content objects (order matches input, failed ones excluded)
 */
export async function resolveChildEmbedContents(
	childEmbedIds: string[]
): Promise<Record<string, unknown>[]> {
	if (childEmbedIds.length === 0) return [];

	const resolved = await resolveEmbedContents(childEmbedIds);
	const results: Record<string, unknown>[] = [];

	for (const id of childEmbedIds) {
		const bareId = id.startsWith('embed:') ? id.slice('embed:'.length) : id;
		const entry = resolved.get(bareId);
		if (entry) {
			results.push(entry.content);
		}
	}

	return results;
}
