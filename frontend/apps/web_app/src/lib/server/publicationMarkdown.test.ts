import { describe, expect, it } from 'vitest';
import { renderPublicationMarkdown } from './publicationMarkdown';

describe('renderPublicationMarkdown', () => {
	// contract-test: direct surface=gui.web assertions=public-publications.content.media-groups
	it('groups adjacent image and video URLs across blank lines', () => {
		const html = renderPublicationMarkdown(`https://media.openmates.org/one.webp

https://media.openmates.org/two.mp4

Following paragraph.`);
		expect(html).toContain('class="publication-media-group"');
		expect(html).toContain('data-media-count="2"');
		expect(html.indexOf('</figure>')).toBeLessThan(html.indexOf('Following paragraph'));
	});

	// contract-test: direct surface=gui.web assertions=public-publications.content.media-groups
	it('keeps media separated when prose interrupts the run', () => {
		const html = renderPublicationMarkdown(`https://media.openmates.org/one.webp
Explanation
https://media.openmates.org/two.webp`);
		expect(html.match(/publication-media-group/g)).toHaveLength(2);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.content.media-groups
	it('does not reinterpret ordinary links, lists, or fenced code as media', () => {
		const html = renderPublicationMarkdown(`[Source](https://media.openmates.org/one.webp)
- https://media.openmates.org/two.webp
\`\`\`
https://media.openmates.org/three.webp
\`\`\``);
		expect(html).not.toContain('publication-media-group');
		expect(html).toContain('<code>https://media.openmates.org/three.webp');
	});

	// contract-test: supporting surface=gui.web assertions=public-publications.authoring.public-boundary
	it('escapes raw HTML', () => {
		const html = renderPublicationMarkdown('<script>alert(1)</script>');
		expect(html).not.toContain('<script>');
		expect(html).toContain('&lt;script&gt;');
	});

	// contract-test: direct surface=gui.web assertions=public-publications.content.media-groups
	it('opens external article links and linked images in a new tab', () => {
		const html = renderPublicationMarkdown(`[GitHub](https://github.com/glowingkitty/OpenMates)

[![Diagram](/publications/blog/diagram.webp)](https://media.openmates.org/diagram.png)`);
		expect(html.match(/target="_blank"/g)).toHaveLength(2);
		expect(html.match(/rel="noopener noreferrer"/g)).toHaveLength(2);
	});
});
