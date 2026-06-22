/**
 * Mind map upload classification helpers.
 *
 * Only explicit OpenMates mind map files are accepted here. Generic .json files
 * remain generic code/data uploads unless they use a Mind Maps-specific filename
 * or native .ommindmap extension plus the required schema marker.
 */

import { MIND_MAP_SUPPORTED_SCHEMA_VERSION, normalizeMindMapSource } from '../../embeds/mindmaps/mindMapContent';

export const MIND_MAP_MAX_UPLOAD_BYTES = 1024 * 1024;

export type MindMapUploadClassification =
	| { accepted: true; embedType: 'mindmaps-mindmap' }
	| { accepted: false; reason: 'not_mindmap_extension' | 'too_large' | 'invalid_json' | 'missing_marker' | 'unsupported_schema' | 'invalid_content' };

export function classifyMindMapUploadSource(filename: string, source: string, sizeBytes = source.length): MindMapUploadClassification {
	const normalizedFilename = filename.toLowerCase();
	const hasMindMapExtension =
		normalizedFilename.endsWith('.ommindmap') ||
		normalizedFilename.endsWith('.openmates-mindmap.json');

	if (!hasMindMapExtension) return { accepted: false, reason: 'not_mindmap_extension' };
	if (sizeBytes > MIND_MAP_MAX_UPLOAD_BYTES) return { accepted: false, reason: 'too_large' };

	let parsed: unknown;
	try {
		parsed = JSON.parse(source);
	} catch {
		return { accepted: false, reason: 'invalid_json' };
	}

	if (!isRecord(parsed) || parsed.openmatesType !== 'mindmap') {
		return { accepted: false, reason: 'missing_marker' };
	}

	if (parsed.schemaVersion !== MIND_MAP_SUPPORTED_SCHEMA_VERSION) {
		return { accepted: false, reason: 'unsupported_schema' };
	}

	const normalized = normalizeMindMapSource(parsed);
	if (normalized.status === 'invalid_source') {
		return { accepted: false, reason: 'invalid_content' };
	}

	return { accepted: true, embedType: 'mindmaps-mindmap' };
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}
