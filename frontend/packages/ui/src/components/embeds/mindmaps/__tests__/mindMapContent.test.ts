import { describe, expect, it } from 'vitest';

import {
	buildMindMapLayout,
	normalizeMindMapSource,
	serializeMindMapDocument,
	toMindMapOutline,
	type MindMapDocument
} from '../mindMapContent';

function validMap(): MindMapDocument {
	return {
		openmatesType: 'mindmap',
		schemaVersion: 1,
		title: 'Launch Plan',
		rootId: 'root',
		nodes: [
			{ id: 'root', label: 'Launch Plan', children: ['research', 'ship'] },
			{ id: 'research', label: 'Audience Research', color: '#0f766e', icon: 'search' },
			{ id: 'ship', label: 'Ship', icon: 'circle-check' }
		],
		edges: [
			{ source: 'research', target: 'ship', type: 'dependency' }
		],
		view: { layout: 'radial-tree', collapsedNodeIds: [] }
	};
}

describe('mind map content helpers', () => {
	it('normalizes valid canonical JSON into a renderable model', () => {
		const result = normalizeMindMapSource(JSON.stringify(validMap()));

		expect(result.status).toBe('valid');
		expect(result.model?.title).toBe('Launch Plan');
		expect(result.nodeCount).toBe(3);
		expect(result.edgeCount).toBe(1);
		expect(result.model?.nodes.find((node) => node.id === 'research')?.color).toBe('#0f766e');
		expect(result.model?.nodes.find((node) => node.id === 'ship')?.icon).toBe('circle-check');
		expect(result.warnings).toEqual([]);
	});

	it('drops unsafe color values but preserves lucide icon names', () => {
		const result = normalizeMindMapSource(JSON.stringify({
			...validMap(),
			nodes: [
				{ id: 'root', label: 'Root', children: ['child'], color: 'url(javascript:alert(1))', icon: 'shield-check' },
				{ id: 'child', label: 'Child', color: '#fff' }
			]
		}));

		expect(result.status).toBe('partial');
		expect(result.model?.nodes.find((node) => node.id === 'root')?.color).toBeUndefined();
		expect(result.model?.nodes.find((node) => node.id === 'root')?.icon).toBe('shield-check');
		expect(result.model?.nodes.find((node) => node.id === 'child')?.color).toBe('#fff');
		expect(result.warnings.some((warning) => warning.code === 'invalid_color')).toBe(true);
	});

	it('keeps recoverable invalid nodes as visible placeholders and drops broken edges', () => {
		const source = JSON.stringify({
			...validMap(),
			nodes: [
				{ id: 'root', label: 'Root', children: ['missing-label'] },
				{ id: 'missing-label' },
				{ id: 'root', label: 'Duplicate root' }
			],
			edges: [{ source: 'root', target: 'missing-node', type: 'related' }]
		});

		const result = normalizeMindMapSource(source);

		expect(result.status).toBe('partial');
		expect(result.model?.nodes.find((node) => node.id === 'missing-label')?.label).toBe('Invalid content');
		expect(result.edgeCount).toBe(0);
		expect(result.warnings.some((warning) => warning.code === 'missing_label')).toBe(true);
		expect(result.warnings.some((warning) => warning.code === 'duplicate_node_id')).toBe(true);
		expect(result.warnings.some((warning) => warning.code === 'missing_edge_target')).toBe(true);
	});

	it('returns invalid-source fallback data for unparseable JSON', () => {
		const result = normalizeMindMapSource('{"openmatesType":"mindmap",');

		expect(result.status).toBe('invalid_source');
		expect(result.model).toBeNull();
		expect(result.parseError).toContain('JSON');
	});

	it('rejects maps where every node is structurally invalid', () => {
		const result = normalizeMindMapSource(JSON.stringify({
			...validMap(),
			nodes: [{ label: 'Missing id' }]
		}));

		expect(result.status).toBe('invalid_source');
		expect(result.model).toBeNull();
	});

	it('serializes canonical .ommindmap JSON with stable formatting', () => {
		const result = normalizeMindMapSource(JSON.stringify(validMap()));
		const serialized = serializeMindMapDocument(result.model!);

		expect(serialized).toContain('"openmatesType": "mindmap"');
		expect(serialized).toContain('"schemaVersion": 1');
		expect(JSON.parse(serialized).rootId).toBe('root');
	});

	it('renders a compact outline from the root for CLI/text views', () => {
		const result = normalizeMindMapSource(JSON.stringify(validMap()));
		const outline = toMindMapOutline(result.model!);

		expect(outline).toContain('- Launch Plan');
		expect(outline).toContain('  - Audience Research');
		expect(outline).toContain('  - Ship');
	});

	it('lays out hierarchy top-to-bottom', () => {
		const result = normalizeMindMapSource(JSON.stringify(validMap()));
		const layout = buildMindMapLayout(result.model!);
		const root = layout.nodes.find((node) => node.id === 'root')!;
		const research = layout.nodes.find((node) => node.id === 'research')!;

		expect(research.y).toBeGreaterThan(root.y);
		expect(research.depth).toBe(root.depth + 1);
	});
});
