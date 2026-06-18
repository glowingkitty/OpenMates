/**
 * Mermaid diagram embed helpers.
 *
 * Pure functions live outside Svelte components so rendering, sanitization, text
 * export, and CLI-like contracts can be tested without a browser-mounted embed.
 */

export interface MermaidDiagramContent {
	title: string;
	diagramKind: string;
	diagramCode: string;
	status: 'processing' | 'finished' | 'error' | 'cancelled';
	lineCount: number;
	versionNumber?: number;
}

const UNSAFE_SVG_TAG_PATTERN = /<\/?(?:script|foreignObject|iframe|object|embed|link|meta|style)\b[^>]*>/gi;
const EVENT_HANDLER_PATTERN = /\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi;
const UNSAFE_URL_ATTR_PATTERN = /\s+(?:href|xlink:href|src)\s*=\s*("|')\s*(?:javascript:|data:|http:|https:)[\s\S]*?\1/gi;
const EXTERNAL_STYLE_URL_PATTERN = /url\(\s*(?:"|')?\s*(?:https?:|data:|javascript:)[^)]+\)/gi;

export function normalizeMermaidContent(content: Record<string, unknown>): MermaidDiagramContent {
	const diagramCode = stringValue(content.diagram_code) ?? stringValue(content.code) ?? stringValue(content.source) ?? '';
	return {
		title: stringValue(content.title) ?? 'Mermaid Diagram',
		diagramKind: stringValue(content.diagram_kind) ?? inferDiagramKind(diagramCode),
		diagramCode,
		status: normalizeStatus(content.status),
		lineCount: typeof content.line_count === 'number' ? content.line_count : countLines(diagramCode),
		versionNumber: typeof content.version_number === 'number' ? content.version_number : undefined
	};
}

export function inferDiagramKind(source: string): string {
	for (const rawLine of source.split('\n')) {
		const line = rawLine.trim();
		if (!line || line.startsWith('%%')) continue;
		return line.split(/\s+/, 1)[0] || 'mermaid';
	}
	return 'mermaid';
}

export function countLines(source: string): number {
	return source ? source.split('\n').length : 0;
}

export function sanitizeMermaidSvg(svg: string): string {
	return svg
		.replace(UNSAFE_SVG_TAG_PATTERN, '')
		.replace(EVENT_HANDLER_PATTERN, '')
		.replace(UNSAFE_URL_ATTR_PATTERN, '')
		.replace(EXTERNAL_STYLE_URL_PATTERN, 'none');
}

export function getPreviewTransform(svgWidth: number, svgHeight: number, viewportWidth: number, viewportHeight: number) {
	if (svgWidth <= 0 || svgHeight <= 0 || viewportWidth <= 0 || viewportHeight <= 0) {
		return { scale: 1, offsetX: 0, offsetY: 0 };
	}
	const fitScale = Math.min(viewportWidth / svgWidth, viewportHeight / svgHeight);
	const readableScale = Math.max(0.72, fitScale);
	return {
		scale: Math.min(1, readableScale),
		offsetX: 0,
		offsetY: 0
	};
}

export function nextZoom(current: number, direction: 'in' | 'out'): number {
	const next = direction === 'in' ? current * 1.2 : current / 1.2;
	return Math.min(4, Math.max(0.25, Number(next.toFixed(3))));
}

export function renderMermaidText(content: Record<string, unknown>, full = false): string {
	const normalized = normalizeMermaidContent(content);
	const lines = [`**Mermaid Diagram** - ${normalized.title}`, normalized.diagramKind];
	if (normalized.status) lines.push(`status: ${normalized.status}`);
	if (!normalized.diagramCode) return lines.join('\n');
	lines.push('');
	if (full) {
		lines.push('```mermaid', normalized.diagramCode.trim(), '```');
	} else {
		lines.push(truncate(normalized.diagramCode, 500));
	}
	return lines.join('\n');
}

function normalizeStatus(value: unknown): MermaidDiagramContent['status'] {
	if (value === 'finished' || value === 'error' || value === 'cancelled') return value;
	return 'processing';
}

function stringValue(value: unknown): string | null {
	return typeof value === 'string' && value.length > 0 ? value : null;
}

function truncate(value: string, max: number): string {
	return value.length > max ? `${value.slice(0, max)}...` : value;
}
