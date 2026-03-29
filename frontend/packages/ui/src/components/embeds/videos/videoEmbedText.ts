/**
 * Text-only renderers for video embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:videos:search — composite */
export function renderVideosSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? '';
	const lines: string[] = [];
	lines.push(`**Video Search**${query ? ` — "${trunc(query, 60)}"` : ''}`);

	if (children && children.length > 0) {
		lines.push(`${children.length} videos:`);
		for (const r of children.slice(0, 5)) {
			const title = str(r.title) ?? '';
			const channel = str(r.channel) ?? str(r.author) ?? '';
			const url = str(r.url) ?? str(r.link) ?? '';
			if (title) lines.push(`  ${title}`);
			if (channel) lines.push(`  ${channel}`);
			if (url) lines.push(`  ${url}`);
			lines.push('');
		}
		if (children.length > 5) lines.push(`  + ${children.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} videos`);
	}
	return lines.join('\n');
}

/** app:videos:get_transcript */
export function renderVideoTranscript(c: Record<string, unknown>): string {
	const title = str(c.title) ?? str(c.video_title) ?? '';
	const url = str(c.url) ?? str(c.video_url) ?? '';
	const channel = str(c.channel) ?? str(c.author) ?? '';
	const lines: string[] = ['**Video Transcript**'];
	if (title) lines.push(title);
	if (channel) lines.push(channel);
	if (url) lines.push(url);
	return lines.join('\n');
}

/** videos-video — individual video */
export function renderVideo(c: Record<string, unknown>): string {
	const title = str(c.title) ?? '';
	const channel = str(c.channel) ?? str(c.author) ?? '';
	const duration = str(c.duration) ?? '';
	const url = str(c.url) ?? str(c.link) ?? '';
	const lines: string[] = [];
	if (title) lines.push(`**${title}**`);
	if (channel || duration) lines.push([channel, duration].filter(Boolean).join('  '));
	if (url) lines.push(url);
	return lines.length > 0 ? lines.join('\n') : '[Video]';
}
