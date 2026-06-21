import { describe, expect, it } from 'vitest';

import { classifyMindMapUploadSource } from '../mindMapUploadDetection';

const validSource = JSON.stringify({
	openmatesType: 'mindmap',
	schemaVersion: 1,
	title: 'Launch Plan',
	rootId: 'root',
	nodes: [{ id: 'root', label: 'Launch Plan' }]
});

describe('mind map upload detection', () => {
	it('classifies native .ommindmap files as mindmap embeds', () => {
		const result = classifyMindMapUploadSource('launch.ommindmap', validSource);

		expect(result.accepted).toBe(true);
		expect(result.embedType).toBe('mindmaps-mindmap');
	});

	it('classifies marked .openmates-mindmap.json files as mindmap embeds', () => {
		const result = classifyMindMapUploadSource('launch.openmates-mindmap.json', validSource);

		expect(result.accepted).toBe(true);
		expect(result.embedType).toBe('mindmaps-mindmap');
	});

	it('does not classify generic JSON without the OpenMates marker', () => {
		const result = classifyMindMapUploadSource('data.json', '{"nodes":[]}');

		expect(result.accepted).toBe(false);
		expect(result.reason).toBe('not_mindmap_extension');
	});

	it('rejects unsupported schema versions visibly', () => {
		const result = classifyMindMapUploadSource(
			'future.ommindmap',
			JSON.stringify({ ...JSON.parse(validSource), schemaVersion: 999 })
		);

		expect(result.accepted).toBe(false);
		expect(result.reason).toBe('unsupported_schema');
	});

	it('rejects oversized explicit mindmap files before parsing', () => {
		const result = classifyMindMapUploadSource('huge.ommindmap', validSource, 1024 * 1024 + 1);

		expect(result.accepted).toBe(false);
		expect(result.reason).toBe('too_large');
	});

	it('rejects structurally invalid explicit mindmap files', () => {
		const result = classifyMindMapUploadSource(
			'empty.ommindmap',
			JSON.stringify({ openmatesType: 'mindmap', schemaVersion: 1, title: 'Empty', nodes: [] })
		);

		expect(result.accepted).toBe(false);
		expect(result.reason).toBe('invalid_content');
	});
});
