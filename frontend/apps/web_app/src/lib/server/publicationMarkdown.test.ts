import { describe, expect, it } from 'vitest';
import { renderPublicationMarkdown } from '../../../../../packages/public-site/src/publications/publicationMarkdown';

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

	// contract-test: supporting surface=gui.web assertions=public-publications.content.media-groups
	it.each([
		['typescript', 'const name: string = "OpenMates";', 'hljs-keyword'],
		['ts', 'const enabled = true;', 'hljs-keyword'],
		['python', 'def greet():\n    return "Hello"', 'hljs-keyword'],
		['bash', 'echo "Hello"', 'hljs-string'],
		['json', '{"enabled": true, "count": 3}', 'hljs-number'],
	])('highlights %s during server rendering', (language, source, token) => {
		const html = renderPublicationMarkdown('```' + language + '\n' + source + '\n```');
		expect(html).toContain('class="language-' + language + '"');
		expect(html).toContain(token);
	});

	// contract-test: supporting surface=gui.web assertions=public-publications.authoring.public-boundary
	it.each(['typescript', 'unknown-language', '', 'text'])('escapes hostile code with %s language', (language) => {
		const html = renderPublicationMarkdown('```' + language + '\n<script>alert("x")</script><img src=x onerror=alert(1)>\n```');
		expect(html).not.toMatch(/<(?:script|img)\b/);
		expect(html).toContain('&lt;');
		expect(html).toContain('&gt;');
		if (language !== 'typescript') expect(html).not.toContain('<span');
	});

	// contract-test: supporting surface=gui.web assertions=public-publications.authoring.public-boundary
	it('escapes malicious fence info instead of creating attributes', () => {
		const html = renderPublicationMarkdown('```unknown" onclick="alert(1)\n<unsafe>&\n```');
		expect(html).toContain('language-unknown&quot;');
		expect(html).toContain('&lt;unsafe&gt;&amp;');
		expect(html).not.toContain(' onclick=');
	});
});
