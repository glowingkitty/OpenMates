/**
 * Text-only renderers for image embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:images:generate / app:images:generate_draft */
export function renderImageGenerate(c: Record<string, unknown>): string {
	const model = str(c.model);
	const prompt = str(c.prompt);
	const lines: string[] = ['**Generated Image**'];
	if (model) lines.push(`Model: ${model}`);
	if (prompt) lines.push(`Prompt: ${trunc(prompt, 100)}`);
	lines.push('[image]');
	return lines.join('\n');
}

/** app:images:search — composite */
export function renderImagesSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? '';
	const lines: string[] = [];
	lines.push(`**Image Search**${query ? ` — "${trunc(query, 60)}"` : ''}`);
	const count = children?.length ?? resolveResultCount(c);
	if (count !== null) lines.push(`${count} images`);
	return lines.join('\n');
}

/** image — direct image embed */
export function renderImage(c: Record<string, unknown>): string {
	const alt = str(c.alt) ?? str(c.caption) ?? str(c.filename) ?? '';
	const lines: string[] = [];
	if (alt) lines.push(`**${alt}**`);
	lines.push('[image]');
	return lines.join('\n');
}

/** images-image-result — individual search result */
export function renderImageResult(c: Record<string, unknown>): string {
	const title = str(c.title) ?? '';
	const source = str(c.source) ?? str(c.url) ?? '';
	const lines: string[] = [];
	if (title) lines.push(title);
	if (source) lines.push(source);
	return lines.length > 0 ? lines.join('\n') : '[Image]';
}
