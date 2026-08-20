/**
 * Deterministic browser-shell composition for real Playwright recordings.
 *
 * The page viewport remains real source video pixels. Only stable browser chrome
 * and address-bar domain context are composed around it for tutorial playback.
 */

import React from 'react';
import {AbsoluteFill, Freeze, OffthreadVideo, Sequence, staticFile} from 'remotion';

import type {BrowserTutorialProps, TutorialSegment} from './types';

const TOOLBAR_HEIGHT = 72;
const FRAME_PADDING = 16;

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
	return (
		<Freeze frame={0}>
			<OffthreadVideo
				src={source}
				trimBefore={frames(segment.source_at_ms, fps)}
				volume={0}
				style={{width: '100%', height: '100%', objectFit: 'fill'}}
			/>
		</Freeze>
	);
};

export const BrowserTutorial: React.FC<BrowserTutorialProps> = (props) => {
	const source = staticFile(props.sourceVideo);
	let from = 0;
	return (
		<AbsoluteFill style={{backgroundColor: '#d9d9dd', padding: FRAME_PADDING, fontFamily: 'Arial, sans-serif'}}>
			<div style={{width: props.output.width - FRAME_PADDING * 2, height: props.output.height - FRAME_PADDING * 2, borderRadius: 14, overflow: 'hidden', background: '#fff', boxShadow: '0 18px 55px rgba(22, 24, 31, 0.28)'}}>
				<div style={{height: TOOLBAR_HEIGHT, background: '#f2f2f4', display: 'flex', alignItems: 'center', gap: 18, padding: '0 20px', borderBottom: '1px solid #d4d4d8'}}>
					<div style={{display: 'flex', gap: 8}}>
						<span style={{width: 13, height: 13, borderRadius: 99, background: '#ff5f57'}} />
						<span style={{width: 13, height: 13, borderRadius: 99, background: '#febc2e'}} />
						<span style={{width: 13, height: 13, borderRadius: 99, background: '#28c840'}} />
					</div>
					<div style={{height: 40, flex: 1, borderRadius: 10, background: '#fff', border: '1px solid #d4d4d8', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#34343a', fontSize: 17}}>
						<span style={{fontSize: 13, marginRight: 8}}>●</span>{props.domain}
					</div>
				</div>
				<div style={{position: 'relative', width: props.output.width - FRAME_PADDING * 2, height: props.output.height - TOOLBAR_HEIGHT - FRAME_PADDING * 2}}>
					{props.segments.map((segment, index) => {
						const duration = frames(segment.duration_ms, props.output.fps);
						const start = from;
						from += duration;
						return <Sequence key={`${segment.kind}-${index}`} from={start} durationInFrames={duration}><Segment segment={segment} source={source} fps={props.output.fps} /></Sequence>;
					})}
				</div>
			</div>
		</AbsoluteFill>
	);
};

export const tutorialDurationInFrames = (props: BrowserTutorialProps) => props.segments.reduce(
	(total, segment) => total + frames(segment.duration_ms, props.output.fps),
	0
);
