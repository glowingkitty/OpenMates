/**
 * Mind map embed content helpers.
 *
 * Pure functions live outside Svelte components so validation, text export,
 * upload detection, and CLI-like rendering contracts can be tested without a
 * browser-mounted embed.
 */

export const MIND_MAP_SUPPORTED_SCHEMA_VERSION = 1;
export const INVALID_MIND_MAP_LABEL = 'Invalid content';

export type MindMapStatus = 'valid' | 'partial' | 'invalid_source';

export interface MindMapNode {
	id: string;
	label: string;
	description?: string;
	color?: string;
	icon?: string;
	children?: string[];
}

export interface MindMapEdge {
	source: string;
	target: string;
	type?: string;
	label?: string;
}

export interface MindMapDocument {
	[key: string]: unknown;
	openmatesType: 'mindmap';
	schemaVersion: 1;
	title: string;
	rootId: string;
	nodes: MindMapNode[];
	edges?: MindMapEdge[];
	view?: {
		layout?: string;
		collapsedNodeIds?: string[];
	};
}

export interface MindMapWarning {
	code: string;
	path: string;
}

export interface MindMapNormalizationResult {
	status: MindMapStatus;
	model: MindMapDocument | null;
	sourceJson: string;
	title: string;
	nodeCount: number;
	edgeCount: number;
	warnings: MindMapWarning[];
	parseError?: string;
}

export function normalizeMindMapSource(source: string | Record<string, unknown> | null | undefined): MindMapNormalizationResult {
	const parsed = parseMindMapSource(source);
	if (!parsed.ok) {
		return invalidSource(typeof source === 'string' ? source : '', parsed.error);
	}

	const raw = parsed.value;
	if (!isRecord(raw)) return invalidSource(JSON.stringify(raw), 'Mind map root must be an object');
	if (raw.openmatesType !== 'mindmap') return invalidSource(JSON.stringify(raw), 'Missing openmatesType: mindmap');
	if (raw.schemaVersion !== MIND_MAP_SUPPORTED_SCHEMA_VERSION) {
		return invalidSource(JSON.stringify(raw), 'Unsupported mind map schemaVersion');
	}

	const title = stringValue(raw.title) ?? 'Mind Map';
	const rootIdCandidate = stringValue(raw.rootId) ?? '';
	const rawNodes = Array.isArray(raw.nodes) ? raw.nodes : [];
	if (rawNodes.length === 0) return invalidSource(JSON.stringify(raw), 'Mind map must contain nodes');

	const warnings: MindMapWarning[] = [];
	const nodes: MindMapNode[] = [];
	const seen = new Set<string>();

	for (const [index, node] of rawNodes.entries()) {
		if (!isRecord(node)) {
			warnings.push({ code: 'invalid_node', path: `nodes[${index}]` });
			continue;
		}

		const id = stringValue(node.id);
		if (!id) {
			warnings.push({ code: 'missing_node_id', path: `nodes[${index}].id` });
			continue;
		}
		if (seen.has(id)) {
			warnings.push({ code: 'duplicate_node_id', path: `nodes[${index}].id` });
			continue;
		}
		seen.add(id);

		let label = stringValue(node.label);
		if (!label) {
			warnings.push({ code: 'missing_label', path: `nodes[${index}].label` });
			label = INVALID_MIND_MAP_LABEL;
		}

		const normalizedNode: MindMapNode = { id, label };
		for (const key of ['description', 'color', 'icon'] as const) {
			const value = stringValue(node[key]);
			if (value) normalizedNode[key] = value;
		}
		if (Array.isArray(node.children)) {
			const children = node.children.filter((child): child is string => typeof child === 'string' && child.length > 0);
			if (children.length > 0) normalizedNode.children = children;
		}
		nodes.push(normalizedNode);
	}
	if (nodes.length === 0) return invalidSource(JSON.stringify(raw), 'Mind map must contain at least one valid node');

	const knownIds = new Set(nodes.map((node) => node.id));
	let rootId = rootIdCandidate;
	if (!knownIds.has(rootId)) {
		warnings.push({ code: 'missing_root', path: 'rootId' });
		rootId = nodes[0]?.id ?? '';
	}

	for (const node of nodes) {
		if (!node.children) continue;
		const children = node.children.filter((child) => knownIds.has(child));
		if (children.length !== node.children.length) {
			warnings.push({ code: 'missing_child', path: `nodes.${node.id}.children` });
		}
		if (children.length > 0) node.children = children;
		else delete node.children;
	}

	const edges = normalizeEdges(raw.edges, knownIds, warnings);
	const model: MindMapDocument = {
		openmatesType: 'mindmap',
		schemaVersion: MIND_MAP_SUPPORTED_SCHEMA_VERSION,
		title,
		rootId,
		nodes,
		edges,
		view: normalizeView(raw.view)
	};

	return {
		status: warnings.length > 0 ? 'partial' : 'valid',
		model,
		sourceJson: serializeMindMapDocument(model),
		title,
		nodeCount: nodes.length,
		edgeCount: edges.length,
		warnings
	};
}

export function serializeMindMapDocument(document: MindMapDocument): string {
	return `${JSON.stringify(document, null, 2)}\n`;
}

export function toMindMapOutline(document: MindMapDocument, maxNodes = 100): string {
	const nodesById = new Map(document.nodes.map((node) => [node.id, node]));
	const lines: string[] = [];
	const visited = new Set<string>();

	function visit(nodeId: string, depth: number) {
		if (visited.size >= maxNodes || visited.has(nodeId)) return;
		const node = nodesById.get(nodeId);
		if (!node) return;
		visited.add(nodeId);
		lines.push(`${'  '.repeat(depth)}- ${node.label}`);
		for (const childId of node.children ?? []) visit(childId, depth + 1);
	}

	visit(document.rootId, 0);
	for (const node of document.nodes) {
		if (visited.size >= maxNodes) break;
		if (!visited.has(node.id)) visit(node.id, 0);
	}
	return lines.join('\n');
}

export function renderMindMapText(content: Record<string, unknown>, full = false): string {
	const source = typeof content.source_json === 'string' ? content.source_json : content.model;
	const normalized = normalizeMindMapSource(source as string | Record<string, unknown> | null | undefined);
	const title = stringValue(content.title) ?? normalized.title;
	const lines = [`**Mind Map** - ${title}`];

	if (normalized.status === 'invalid_source') {
		lines.push('Invalid mind map JSON');
		if (normalized.parseError) lines.push(normalized.parseError);
		return lines.join('\n');
	}

	lines.push(`${normalized.nodeCount} nodes · ${normalized.edgeCount} edges`);
	if (normalized.warnings.length > 0) {
		lines.push(`${normalized.warnings.length} validation warning${normalized.warnings.length === 1 ? '' : 's'}`);
	}
	if (!normalized.model) return lines.join('\n');

	lines.push('', toMindMapOutline(normalized.model));
	if (full) {
		lines.push('', '```openmates_mindmap', serializeMindMapDocument(normalized.model).trim(), '```');
	}
	return lines.join('\n');
}

function normalizeEdges(value: unknown, knownIds: Set<string>, warnings: MindMapWarning[]): MindMapEdge[] {
	if (!Array.isArray(value)) return [];
	const edges: MindMapEdge[] = [];
	for (const [index, edge] of value.entries()) {
		if (!isRecord(edge)) {
			warnings.push({ code: 'invalid_edge', path: `edges[${index}]` });
			continue;
		}
		const source = stringValue(edge.source);
		const target = stringValue(edge.target);
		if (!source || !knownIds.has(source)) {
			warnings.push({ code: 'missing_edge_source', path: `edges[${index}].source` });
			continue;
		}
		if (!target || !knownIds.has(target)) {
			warnings.push({ code: 'missing_edge_target', path: `edges[${index}].target` });
			continue;
		}
		const normalized: MindMapEdge = { source, target };
		const type = stringValue(edge.type);
		const label = stringValue(edge.label);
		if (type) normalized.type = type;
		if (label) normalized.label = label;
		edges.push(normalized);
	}
	return edges;
}

function normalizeView(value: unknown): MindMapDocument['view'] {
	if (!isRecord(value)) return { layout: 'radial-tree', collapsedNodeIds: [] };
	const collapsed = Array.isArray(value.collapsedNodeIds)
		? value.collapsedNodeIds.filter((item): item is string => typeof item === 'string')
		: [];
	return {
		layout: stringValue(value.layout) ?? 'radial-tree',
		collapsedNodeIds: collapsed
	};
}

function parseMindMapSource(source: string | Record<string, unknown> | null | undefined):
	| { ok: true; value: unknown }
	| { ok: false; error: string } {
	if (isRecord(source)) return { ok: true, value: source };
	if (typeof source !== 'string') return { ok: false, error: 'Invalid mind map JSON' };
	try {
		return { ok: true, value: JSON.parse(source) };
	} catch (error) {
		return { ok: false, error: `Invalid mind map JSON: ${(error as Error).message}` };
	}
}

function invalidSource(sourceJson: string, parseError: string): MindMapNormalizationResult {
	return {
		status: 'invalid_source',
		model: null,
		sourceJson,
		title: 'Invalid mind map JSON',
		nodeCount: 0,
		edgeCount: 0,
		warnings: [],
		parseError
	};
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | null {
	return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null;
}
