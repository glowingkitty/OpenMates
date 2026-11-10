/**
 * The `app_skill_use` parent embed ids a chat message renders, in order, read
 * from what ChatHistory already holds: the saved markdown's embed reference
 * blocks and the rendered TipTap document's skill-use nodes. Shell glue for
 * messageEmbedVersion.ts; the version rule itself runs in the Rust core.
 */
import { extractEmbedReferences } from '../../embedResolver';

/** The fields of a ChatHistory message this module reads. */
export interface OrderedMessage {
	id: string;
	content?: unknown;
	original_message?: { content?: unknown } | null;
}

const SKILL_USE_NODE = new Set(['app-skill-use', 'app_skill_use']);

function idFromAttrs(attrs: Record<string, unknown>): string | null {
	for (const key of ['contentRef', 'id', 'embedId']) {
		const value = attrs[key];
		if (typeof value === 'string' && value.length > 0) return value.replace(/^embed:/, '');
	}
	return null;
}

function visit(node: unknown, out: string[]): void {
	if (!node || typeof node !== 'object') return;
	const record = node as Record<string, unknown>;
	const attrs = record.attrs as Record<string, unknown> | undefined;
	if (attrs) {
		if (SKILL_USE_NODE.has(String(attrs.type))) {
			const id = idFromAttrs(attrs);
			if (id) out.push(id);
		}
		if (Array.isArray(attrs.groupedItems)) for (const item of attrs.groupedItems) visit({ attrs: item }, out);
	}
	if (Array.isArray(record.content)) for (const child of record.content) visit(child, out);
}

/** Parent ids of one message, deduplicated in first-seen order. */
export function appSkillParentIds(message: OrderedMessage): string[] {
	const ids: string[] = [];
	const markdown = message.original_message?.content;
	if (typeof markdown === 'string') {
		for (const ref of extractEmbedReferences(markdown)) {
			if (SKILL_USE_NODE.has(ref.type)) ids.push(ref.embed_id);
		}
	}
	visit(message.content, ids);
	return [...new Set(ids)];
}
