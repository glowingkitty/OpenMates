/**
 * Canonical input types for deterministic proof-video rendering.
 *
 * Inputs are generated from a hash-bound Playwright proof timeline. The renderer
 * does not infer actions, narration, domains, or pacing from pixels or models.
 */

export type TutorialSegment = {kind: 'video'; source_from_ms: number; source_to_ms: number; duration_ms: number};

export interface BrowserTutorialProps extends Record<string, unknown> {
	schemaVersion: number;
	renderer: string;
	presentationMode: 'browser-frame-scaled-full-viewport';
	sourceVideo: string;
	sourceHash: string;
	sourceFrameRate?: number;
	sourceClockOffsetMs?: number;
	domain: string;
	deviceProfile: string;
	viewport: {width: number; height: number};
	browserChrome?: {
		kind: string;
		tabGroupLabel?: string;
		backgroundColor?: string;
		topInset?: number;
		bottomInset?: number;
		devicePixelRatio?: number;
	};
	output: {width: number; height: number; fps: number};
	segments: TutorialSegment[];
	contractHash: string;
	timelineHash: string;
}

export interface TerminalTutorialProps extends Record<string, unknown> {
	schemaVersion: number;
	renderer: string;
	sourceVideo: string;
	sourceSha256: string;
	terminalTitle: string;
	deviceProfile: 'cli-terminal';
	viewport: {width: number; height: number};
	output: {width: number; height: number; fps: number};
	durationSeconds: number;
	contractHash: string;
	timelineHash: string;
}
