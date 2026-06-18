import { describe, expect, it } from 'vitest';

import {
	getPreviewTransform,
	nextZoom,
	normalizeMermaidContent,
	renderMermaidText,
	sanitizeMermaidSvg
} from '../mermaidDiagramContent';

describe('Mermaid diagram embed content helpers', () => {
	it('normalizes backend and frontend Mermaid payload aliases', () => {
		const content = normalizeMermaidContent({
			type: 'mermaid',
			title: 'Signup Flow',
			diagram_code: 'sequenceDiagram\nUser->>API: Submit email',
			status: 'finished',
			version_number: 3
		});

		expect(content.title).toBe('Signup Flow');
		expect(content.diagramKind).toBe('sequenceDiagram');
		expect(content.lineCount).toBe(2);
		expect(content.versionNumber).toBe(3);
	});

	it('sanitizes scripts, handlers, unsafe links, and external resources from SVG', () => {
		const sanitized = sanitizeMermaidSvg(`
			<svg onclick="alert(1)">
				<script>alert(1)</script>
				<foreignObject><div>unsafe</div></foreignObject>
				<a href="javascript:alert(1)"><text>bad</text></a>
				<image href="https://example.com/leak.png" />
				<rect style="fill:url(https://example.com/leak.svg)" />
			</svg>
		`);

		expect(sanitized).not.toMatch(/script/i);
		expect(sanitized).not.toMatch(/foreignObject/i);
		expect(sanitized).not.toMatch(/onclick/i);
		expect(sanitized).not.toMatch(/javascript:/i);
		expect(sanitized).not.toMatch(/https:\/\//i);
	});

	it('keeps preview scale readable instead of shrinking large diagrams completely', () => {
		expect(getPreviewTransform(1200, 800, 300, 200).scale).toBe(0.72);
	});

	it('supports bounded zoom state changes', () => {
		expect(nextZoom(1, 'in')).toBe(1.2);
		expect(nextZoom(1, 'out')).toBe(0.833);
		expect(nextZoom(10, 'in')).toBe(4);
		expect(nextZoom(0.01, 'out')).toBe(0.25);
	});

	it('renders plain text with full fenced source when requested', () => {
		const text = renderMermaidText(
			{
				title: 'Support Flow',
				diagram_kind: 'flowchart',
				diagram_code: 'flowchart TD\nA --> B',
				status: 'finished'
			},
			true
		);

		expect(text).toContain('**Mermaid Diagram** - Support Flow');
		expect(text).toContain('```mermaid');
		expect(text).toContain('A --> B');
	});
});
