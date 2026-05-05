/**
 * Remotion Timeline Parser — extracts timeline structure from Remotion TSX code.
 *
 * Parses Remotion temporal primitives (Sequence, Series.Sequence, Composition,
 * Audio, OffthreadVideo, AbsoluteFill) via regex-based extraction and builds
 * a structured timeline manifest for visualization.
 *
 * This runs client-side for the dev preview page. In production, it will run
 * in the E2B sandbox via a proper Babel AST parser for full accuracy.
 */

// ─── Types ──────────────────────────────────────────────────────────

export interface VideoManifest {
	meta: {
		title: string;
		durationInFrames: number;
		fps: number;
		width: number;
		height: number;
		durationSeconds: number;
	};
	tracks: Track[];
}

export interface Track {
	name: string;
	type: 'visual' | 'text' | 'audio' | 'effect';
	items: TrackItem[];
}

export interface TrackItem {
	id: string;
	label: string;
	from: number;
	durationInFrames: number;
	color: string;
	details?: string;
}

// ─── Track colors (one per track for visual distinction) ────────────

const TRACK_COLORS = [
	'#3B82F6', // blue
	'#8B5CF6', // violet
	'#EC4899', // pink
	'#F59E0B', // amber
	'#10B981', // emerald
	'#EF4444', // red
	'#06B6D4', // cyan
	'#F97316', // orange
];

const AUDIO_COLOR = '#22C55E';
const VIDEO_COLOR = '#6366F1';
const _EFFECT_COLOR = '#A855F7';

// ─── Helpers ────────────────────────────────────────────────────────

/** Extract a numeric JSX prop value. Handles simple expressions like {30 * 5}. */
function extractNumericProp(tag: string, propName: string): number | null {
	// Match propName={...} or propName=N
	const pattern = new RegExp(`${propName}=\\{([^}]+)\\}|${propName}=(\\d+)`);
	const match = tag.match(pattern);
	if (!match) return null;

	const raw = (match[1] || match[2]).trim();

	// Try direct number
	const direct = Number(raw);
	if (!isNaN(direct)) return direct;

	// Try simple arithmetic: N * N, N + N, N - N
	const arith = raw.match(/^(\d+(?:\.\d+)?)\s*([+\-*/])\s*(\d+(?:\.\d+)?)$/);
	if (arith) {
		const [, a, op, b] = arith;
		switch (op) {
			case '*': return Number(a) * Number(b);
			case '+': return Number(a) + Number(b);
			case '-': return Number(a) - Number(b);
			case '/': return Number(a) / Number(b);
		}
	}

	// Try fps reference: fps * N or N * fps (common pattern)
	const fpsArith = raw.match(/^(?:fps\s*\*\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*\*\s*fps)$/);
	if (fpsArith) {
		const multiplier = Number(fpsArith[1] || fpsArith[2]);
		return multiplier * 30; // assume 30fps default
	}

	return null;
}

/** Extract a string JSX prop value. */
function extractStringProp(tag: string, propName: string): string | null {
	const pattern = new RegExp(`${propName}=["']([^"']+)["']|${propName}=\\{["']([^"']+)["']\\}`);
	const match = tag.match(pattern);
	return match ? (match[1] || match[2]) : null;
}

/** Get the first component name inside a JSX element (for labeling). */
function extractChildComponent(content: string): string | null {
	const match = content.match(/<([A-Z]\w+)/);
	return match ? match[1] : null;
}

/** Convert camelCase/PascalCase to readable label. */
function toLabel(name: string): string {
	return name
		.replace(/([a-z])([A-Z])/g, '$1 $2')
		.replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
		.toLowerCase()
		.replace(/^./, (c) => c.toUpperCase());
}

// ─── Parser ─────────────────────────────────────────────────────────

interface ParsedBlock {
	type: 'sequence' | 'series-sequence' | 'audio' | 'video' | 'absolutefill';
	from: number | null;
	durationInFrames: number | null;
	label: string;
	children: string;
	depth: number;
}

/**
 * Parse Remotion TSX code and extract a VideoManifest for timeline visualization.
 *
 * This is a regex-based parser optimized for the patterns LLMs generate.
 * It handles: Composition, Sequence, Series.Sequence, AbsoluteFill, Audio,
 * OffthreadVideo, and simple arithmetic in prop values.
 */
export function parseRemotionTimeline(code: string): VideoManifest {
	// ── Extract Composition metadata ──
	const compMatch = code.match(/<Composition[^>]*>/);
	let fps = 30;
	let totalDuration = 300;
	let width = 1920;
	let height = 1080;
	let title = 'Untitled';

	if (compMatch) {
		fps = extractNumericProp(compMatch[0], 'fps') ?? 30;
		totalDuration = extractNumericProp(compMatch[0], 'durationInFrames') ?? 300;
		width = extractNumericProp(compMatch[0], 'width') ?? 1920;
		height = extractNumericProp(compMatch[0], 'height') ?? 1080;
		title = extractStringProp(compMatch[0], 'id') ?? 'Untitled';
	}

	// Also check for durationInFrames in the main component's config/const
	if (!compMatch) {
		const durMatch = code.match(/durationInFrames[:\s=]+(\d+)/);
		if (durMatch) totalDuration = Number(durMatch[1]);
		const fpsMatch = code.match(/fps[:\s=]+(\d+)/);
		if (fpsMatch) fps = Number(fpsMatch[1]);
	}

	const tracks: Track[] = [];
	// ── Extract all Sequence/Series.Sequence blocks linearly ──
	const allSequences: ParsedBlock[] = [];

	// Match <Sequence ...>
	const seqPattern = /<Sequence\b([^>]*)>([^]*?)(?:<\/Sequence>)/g;
	let seqMatch;
	while ((seqMatch = seqPattern.exec(code)) !== null) {
		const props = seqMatch[1];
		const children = seqMatch[2];
		const from = extractNumericProp(`<Sequence ${props}>`, 'from');
		const dur = extractNumericProp(`<Sequence ${props}>`, 'durationInFrames');
		const childComp = extractChildComponent(children);
		const name = extractStringProp(`<Sequence ${props}>`, 'name');

		allSequences.push({
			type: 'sequence',
			from,
			durationInFrames: dur,
			label: name || (childComp ? toLabel(childComp) : 'Scene'),
			children,
			depth: 0,
		});
	}

	// Match <Series.Sequence ...>
	const seriesSeqPattern = /<Series\.Sequence\b([^>]*)>([^]*?)(?:<\/Series\.Sequence>)/g;
	let seriesOffset = 0;
	while ((seqMatch = seriesSeqPattern.exec(code)) !== null) {
		const props = seqMatch[1];
		const children = seqMatch[2];
		const dur = extractNumericProp(`<S ${props}>`, 'durationInFrames');
		const offset = extractNumericProp(`<S ${props}>`, 'offset');
		const childComp = extractChildComponent(children);
		const name = extractStringProp(`<S ${props}>`, 'name');

		const effectiveFrom = seriesOffset + (offset ?? 0);

		allSequences.push({
			type: 'series-sequence',
			from: effectiveFrom,
			durationInFrames: dur,
			label: name || (childComp ? toLabel(childComp) : 'Scene'),
			children,
			depth: 0,
		});

		if (dur) {
			seriesOffset = effectiveFrom + dur;
		}
	}

	// Match <Audio ...> and <OffthreadVideo ...>
	const mediaPattern = /<(Audio|OffthreadVideo|Video)\b([^>]*?)\/?>(?:([^]*?)<\/\1>)?/g;
	while ((seqMatch = mediaPattern.exec(code)) !== null) {
		const tagName = seqMatch[1];
		const props = seqMatch[2];
		const src = extractStringProp(`<${tagName} ${props}>`, 'src') || '';
		const srcLabel = src.split('/').pop()?.replace(/['"]/g, '') || tagName;

		allSequences.push({
			type: tagName === 'Audio' ? 'audio' : 'video',
			from: null,
			durationInFrames: null,
			label: srcLabel,
			children: '',
			depth: 0,
		});
	}

	// ── Group sequences into tracks ──
	// Heuristic: sequences with explicit `from` values are on the main visual track.
	// Series sequences are on a sequential track. Audio/Video get their own tracks.

	const visualItems: TrackItem[] = [];
	const audioItems: TrackItem[] = [];
	const videoItems: TrackItem[] = [];
	let itemId = 0;

	for (const seq of allSequences) {
		const item: TrackItem = {
			id: `item-${itemId++}`,
			label: seq.label,
			from: seq.from ?? 0,
			durationInFrames: seq.durationInFrames ?? Math.round(totalDuration / allSequences.length),
			color: TRACK_COLORS[itemId % TRACK_COLORS.length],
			details: seq.children.trim().slice(0, 100),
		};

		if (seq.type === 'audio') {
			item.color = AUDIO_COLOR;
			item.durationInFrames = totalDuration; // audio typically spans full duration
			audioItems.push(item);
		} else if (seq.type === 'video') {
			item.color = VIDEO_COLOR;
			videoItems.push(item);
		} else {
			visualItems.push(item);
		}
	}

	// ── Detect if sequences are layered (overlapping from values) or sequential ──
	const hasOverlaps = visualItems.some((a, i) =>
		visualItems.some((b, j) =>
			i !== j &&
			a.from < b.from + b.durationInFrames &&
			a.from + a.durationInFrames > b.from
		)
	);

	if (hasOverlaps) {
		// Split into separate tracks by overlap groups
		const assigned = new Set<number>();
		const trackGroups: TrackItem[][] = [];

		for (let i = 0; i < visualItems.length; i++) {
			if (assigned.has(i)) continue;

			const group: TrackItem[] = [visualItems[i]];
			assigned.add(i);

			// Find non-overlapping items for this track
			for (let j = i + 1; j < visualItems.length; j++) {
				if (assigned.has(j)) continue;
				const canFit = group.every(
					(existing) =>
						visualItems[j].from >= existing.from + existing.durationInFrames ||
						visualItems[j].from + visualItems[j].durationInFrames <= existing.from
				);
				if (canFit) {
					group.push(visualItems[j]);
					assigned.add(j);
				}
			}

			trackGroups.push(group);
		}

		trackGroups.forEach((group, i) => {
			group.forEach((item) => {
				item.color = TRACK_COLORS[i % TRACK_COLORS.length];
			});
			tracks.push({
				name: i === 0 ? 'Background' : `Layer ${i + 1}`,
				type: 'visual',
				items: group.sort((a, b) => a.from - b.from),
			});
		});
	} else if (visualItems.length > 0) {
		// All sequential — single track
		visualItems.forEach((item, i) => {
			item.color = TRACK_COLORS[i % TRACK_COLORS.length];
		});
		tracks.push({
			name: 'Scenes',
			type: 'visual',
			items: visualItems,
		});
	}

	if (audioItems.length > 0) {
		tracks.push({ name: 'Audio', type: 'audio', items: audioItems });
	}
	if (videoItems.length > 0) {
		tracks.push({ name: 'Video', type: 'visual', items: videoItems });
	}

	// ── If no sequences found, create a single-scene fallback ──
	if (tracks.length === 0) {
		tracks.push({
			name: 'Scenes',
			type: 'visual',
			items: [{
				id: 'item-0',
				label: title,
				from: 0,
				durationInFrames: totalDuration,
				color: TRACK_COLORS[0],
			}],
		});
	}

	return {
		meta: {
			title: toLabel(title),
			durationInFrames: totalDuration,
			fps,
			width,
			height,
			durationSeconds: Math.round((totalDuration / fps) * 10) / 10,
		},
		tracks,
	};
}
