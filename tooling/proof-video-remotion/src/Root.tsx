/**
 * Remotion composition registration for OpenMates proof tutorials.
 *
 * Composition metadata comes entirely from canonical render input props so one
 * source hash and timeline always resolve to the same dimensions and duration.
 */

import React from 'react';
import {Composition} from 'remotion';

import {BrowserTutorial, tutorialDurationInFrames} from './BrowserTutorial';
import type {BrowserTutorialProps} from './types';

const defaults: BrowserTutorialProps = {
	schemaVersion: 1,
	renderer: 'openmates-remotion-browser-v1',
	sourceVideo: 'source.webm',
	domain: 'app.dev.openmates.org',
	deviceProfile: 'web-laptop',
	viewport: {width: 1440, height: 900},
	output: {width: 1440, height: 900, fps: 30},
	segments: [{kind: 'freeze', source_image: '', source_sha256: 'sha256:default', duration_ms: 1000, cue_id: 'default'}],
	contractHash: 'sha256:default',
	timelineHash: 'sha256:default'
};

export const RemotionRoot: React.FC = () => (
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
);
