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

const browserLayout = (props: BrowserTutorialProps) => {
	const toolbarHeight = props.output.width >= 900 ? 56 : 46;
	const padding = Math.max(16, Math.round(Math.min(props.output.width, props.output.height) * 0.036));
	const sourceRatio = props.viewport.width / props.viewport.height;
	const maxContentWidth = props.output.width - padding * 2;
	const maxContentHeight = props.output.height - padding * 2 - toolbarHeight;
	const contentWidth = Math.min(maxContentWidth, Math.round(maxContentHeight * sourceRatio));
	const contentHeight = Math.min(maxContentHeight, Math.round(contentWidth / sourceRatio));
	return {
		padding,
		toolbarHeight,
		contentWidth,
		contentHeight,
		windowWidth: contentWidth,
		windowHeight: contentHeight + toolbarHeight,
	};
};

export const BrowserTutorial: React.FC<BrowserTutorialProps> = (props) => {
	const source = staticFile(props.sourceVideo);
	let from = 0;
	const layout = browserLayout(props);
	return (
		<AbsoluteFill style={{alignItems: 'center', background: 'linear-gradient(135deg, #dbeafe 0%, #f8fafc 45%, #e0e7ff 100%)', display: 'flex', justifyContent: 'center'}}>
			<div style={{
				backgroundColor: '#f7f7f8',
				border: '1px solid rgba(15, 23, 42, 0.16)',
				borderRadius: props.output.width >= 900 ? 18 : 14,
				boxShadow: '0 28px 80px rgba(15, 23, 42, 0.24), 0 4px 16px rgba(15, 23, 42, 0.12)',
				height: layout.windowHeight,
				overflow: 'hidden',
				width: layout.windowWidth,
			}}>
				<div style={{
					alignItems: 'center',
					background: 'linear-gradient(180deg, #fbfbfc 0%, #eceef2 100%)',
					borderBottom: '1px solid rgba(15, 23, 42, 0.12)',
					display: 'grid',
					gridTemplateColumns: '92px 1fr 92px',
					height: layout.toolbarHeight,
					padding: '0 18px',
				}}>
					<div style={{display: 'flex', gap: 8}}>
						<span style={{backgroundColor: '#ff5f57', borderRadius: '50%', height: 12, width: 12}} />
						<span style={{backgroundColor: '#febc2e', borderRadius: '50%', height: 12, width: 12}} />
						<span style={{backgroundColor: '#28c840', borderRadius: '50%', height: 12, width: 12}} />
					</div>
					<div style={{
						alignItems: 'center',
						backgroundColor: '#ffffff',
						border: '1px solid rgba(15, 23, 42, 0.16)',
						borderRadius: 999,
						boxShadow: 'inset 0 1px 2px rgba(15, 23, 42, 0.06)',
						color: '#1f2937',
						display: 'flex',
						fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
						fontSize: props.output.width >= 900 ? 16 : 12,
						fontWeight: 500,
						gap: 8,
						height: props.output.width >= 900 ? 34 : 28,
						justifyContent: 'center',
						minWidth: 0,
						overflow: 'hidden',
						padding: '0 18px',
						textOverflow: 'ellipsis',
						whiteSpace: 'nowrap',
					}}>
						<span style={{backgroundColor: '#22c55e', borderRadius: '50%', display: 'inline-block', height: 8, width: 8}} />
						<span>{props.domain}</span>
					</div>
					<div style={{color: '#64748b', fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: 14, textAlign: 'right'}}>OpenMates</div>
				</div>
				<div style={{backgroundColor: '#fff', height: layout.contentHeight, overflow: 'hidden', position: 'relative', width: layout.contentWidth}}>
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
