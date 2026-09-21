import MarkdownIt from 'markdown-it';

const markdown = new MarkdownIt({ html: false, linkify: true, breaks: false });
const MEDIA_URL = /^https:\/\/[^\s<>()]+\.(?:avif|gif|jpe?g|png|webp|mp4|m4v|webm)(?:\?[^\s<>()]*)?$/i;
const MARKDOWN_IMAGE = /^!\[([^\]]*)\]\((https:\/\/[^\s)]+)\)$/i;

interface ParsedMedia {
	url: string;
	alt: string;
	type: 'image' | 'video';
}

function escapeHtml(value: string): string {
	return value
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#039;');
}

function parseStandaloneMedia(line: string): ParsedMedia | null {
	const trimmed = line.trim();
	const markdownImage = trimmed.match(MARKDOWN_IMAGE);
	const url = markdownImage?.[2] ?? (MEDIA_URL.test(trimmed) ? trimmed : null);
	if (!url || !MEDIA_URL.test(url)) return null;
	const type = /\.(?:mp4|m4v|webm)(?:\?|$)/i.test(url) ? 'video' : 'image';
	return {
		url,
		alt: markdownImage?.[1]?.trim() || '',
		type
	};
}

function renderMediaGroup(items: ParsedMedia[]): string {
	const media = items.map((item) => {
		const url = escapeHtml(item.url);
		const alt = escapeHtml(item.alt);
		return item.type === 'video'
			? `<video src="${url}" controls playsinline preload="metadata" aria-label="${alt || 'Publication video'}"></video>`
			: `<img src="${url}" alt="${alt}" loading="lazy" decoding="async">`;
	}).join('');
	return `<figure class="publication-media-group" data-media-count="${items.length}">${media}</figure>`;
}

/**
 * Render reviewed publication Markdown while grouping only consecutive,
 * standalone media URLs. Ordinary Markdown and fenced code retain their
 * standard meaning and raw HTML is always escaped by markdown-it.
 */
export function renderPublicationMarkdown(source: string): string {
	const output: string[] = [];
	let markdownLines: string[] = [];
	let mediaItems: ParsedMedia[] = [];
	let inFence = false;

	const flushMarkdown = () => {
		if (!markdownLines.length) return;
		output.push(markdown.render(markdownLines.join('\n')));
		markdownLines = [];
	};
	const flushMedia = () => {
		if (!mediaItems.length) return;
		output.push(renderMediaGroup(mediaItems));
		mediaItems = [];
	};

	for (const line of source.split(/\r?\n/)) {
		if (/^\s*```/.test(line)) {
			flushMedia();
			markdownLines.push(line);
			inFence = !inFence;
			continue;
		}
		if (inFence) {
			markdownLines.push(line);
			continue;
		}

		const media = parseStandaloneMedia(line);
		if (media) {
			flushMarkdown();
			mediaItems.push(media);
			continue;
		}
		if (!line.trim() && mediaItems.length) continue;

		flushMedia();
		markdownLines.push(line);
	}

	flushMedia();
	flushMarkdown();
	return output.join('\n');
}
