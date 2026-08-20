/**
 * Deterministic browser-shell composition for real Playwright recordings.
 *
 * Checkpoint frames retain their exact Playwright geometry and pixels. Browser
 * domain context is captured into each attested checkpoint before rendering.
 */

import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, Sequence, staticFile} from 'remotion';

import type {BrowserTutorialProps, TutorialSegment} from './types';

const frames = (milliseconds: number, fps: number) => Math.max(1, Math.round(milliseconds * fps / 1000));

const Segment: React.FC<{segment: TutorialSegment; source: string; fps: number}> = ({segment, source, fps}) => {
	if (segment.kind === 'video') {
		return (
			<OffthreadVideo
				src={source}
				trimBefore={frames(segment.source_from_ms, fps)}
				trimAfter={frames(segment.source_to_ms, fps)}
				volume={0}
				style={{width: '100%', height: '100%', objectFit: 'fill'}}
			/>
		);
	}
	return <Img src={staticFile(segment.source_image)} style={{width: '100%', height: '100%', objectFit: 'fill'}} />;
};

export const BrowserTutorial: React.FC<BrowserTutorialProps> = (props) => {
	const source = staticFile(props.sourceVideo);
	let from = 0;
	return (
		<AbsoluteFill style={{backgroundColor: '#fff'}}>
			{props.segments.map((segment, index) => {
				const duration = frames(segment.duration_ms, props.output.fps);
				const start = from;
				from += duration;
				return <Sequence key={`${segment.kind}-${index}`} from={start} durationInFrames={duration}><Segment segment={segment} source={source} fps={props.output.fps} /></Sequence>;
			})}
		</AbsoluteFill>
	);
};

export const tutorialDurationInFrames = (props: BrowserTutorialProps) => props.segments.reduce(
	(total, segment) => total + frames(segment.duration_ms, props.output.fps),
	0
);
