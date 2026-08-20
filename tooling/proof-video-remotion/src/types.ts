/**
 * Canonical input types for deterministic proof-video rendering.
 *
 * Inputs are generated from a hash-bound Playwright proof timeline. The renderer
 * does not infer actions, narration, domains, or pacing from pixels or models.
 */

export type TutorialSegment =
	| {kind: 'video'; source_from_ms: number; source_to_ms: number; duration_ms: number}
	| {kind: 'freeze'; source_at_ms: number; duration_ms: number; cue_id: string};

export interface BrowserTutorialProps extends Record<string, unknown> {
	schemaVersion: number;
	renderer: string;
	sourceVideo: string;
	domain: string;
	deviceProfile: string;
	viewport: {width: number; height: number};
	output: {width: number; height: number; fps: number};
	segments: TutorialSegment[];
	contractHash: string;
	timelineHash: string;
}
