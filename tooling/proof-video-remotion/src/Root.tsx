/**
 * Remotion composition registration for OpenMates proof tutorials.
 *
 * Composition metadata comes entirely from canonical render input props so one
 * source hash and timeline always resolve to the same dimensions and duration.
 */

import React from 'react';
import {Composition} from 'remotion';

import {BrowserTutorial, tutorialDurationInFrames} from './BrowserTutorial';
import {TerminalTutorial, terminalDurationInFrames} from './TerminalTutorial';
import type {BrowserTutorialProps, TerminalTutorialProps} from './types';

const defaults: BrowserTutorialProps = {
	schemaVersion: 1,
	renderer: 'openmates-remotion-browser-v1',
	presentationMode: 'browser-frame-scaled-full-viewport',
	sourceVideo: 'source.webm',
	sourceHash: 'sha256:default',
	sourceFrameRate: 30,
	domain: 'app.dev.openmates.org',
	deviceProfile: 'web-laptop',
	viewport: {width: 1440, height: 900},
	output: {width: 1440, height: 900, fps: 30},
	segments: [{kind: 'video', source_from_ms: 0, source_to_ms: 1000, duration_ms: 1000}],
	contractHash: 'sha256:default',
	timelineHash: 'sha256:default'
};

const terminalDefaults: TerminalTutorialProps = {
	schemaVersion: 1,
	renderer: 'openmates-remotion-terminal-v1',
	sourceVideo: 'source.mp4',
	sourceSha256: 'sha256:default',
	terminalTitle: 'Terminal',
	deviceProfile: 'cli-terminal',
	viewport: {width: 1280, height: 720},
	output: {width: 1280, height: 720, fps: 30},
	durationSeconds: 1,
	contractHash: 'sha256:default',
	timelineHash: 'sha256:default',
};

export const RemotionRoot: React.FC = () => (
	<>
		<Composition
			id="OpenMatesBrowserTutorial"
			component={BrowserTutorial}
			width={defaults.output.width}
			height={defaults.output.height}
			fps={defaults.output.fps}
			durationInFrames={30}
			defaultProps={defaults}
			calculateMetadata={({props}) => ({
				width: props.output.width,
				height: props.output.height,
				fps: props.output.fps,
				durationInFrames: tutorialDurationInFrames(props)
			})}
		/>
		<Composition
			id="OpenMatesTerminalTutorial"
			component={TerminalTutorial}
			width={terminalDefaults.output.width}
			height={terminalDefaults.output.height}
			fps={terminalDefaults.output.fps}
			durationInFrames={30}
			defaultProps={terminalDefaults}
			calculateMetadata={({props}) => ({
				width: props.output.width,
				height: props.output.height,
				fps: props.output.fps,
				durationInFrames: terminalDurationInFrames(props)
			})}
		/>
	</>
);
