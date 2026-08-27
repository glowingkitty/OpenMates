/**
 * Deterministic browser-shell composition for real Playwright recordings.
 *
 * The real Playwright source stays chronological from start to finish. Attested
 * checkpoint holds are inserted as explicit paused states for review.
 */

import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';

import type {BrowserTutorialProps, TutorialSegment} from './types';

const frames = (milliseconds: number, fps: number) => Math.max(1, Math.round(milliseconds * fps / 1000));

const PauseBadge: React.FC = () => (
	<div style={{
		alignItems: 'center',
		background: 'rgba(100, 116, 139, 0.14)',
		border: '1px solid rgba(100, 116, 139, 0.28)',
		borderRadius: 999,
		display: 'flex',
		gap: 9,
		height: 30,
		justifyContent: 'center',
		marginRight: 16,
		width: 42,
	}}>
		<span aria-label="Paused recording" style={{display: 'inline-flex', gap: 4}}>
			<span style={{background: '#64748b', borderRadius: 2, height: 13, width: 4}} />
			<span style={{background: '#64748b', borderRadius: 2, height: 13, width: 4}} />
		</span>
	</div>
);

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

const Segments: React.FC<{segments: TutorialSegment[]; source: string; fps: number}> = ({segments, source, fps}) => {
	let from = 0;
	return (
		<>
			{segments.map((segment, index) => {
				const duration = frames(segment.duration_ms, fps);
				const start = from;
				from += duration;
				return <Sequence key={`${segment.kind}-${index}`} from={start} durationInFrames={duration}><Segment segment={segment} source={source} fps={fps} /></Sequence>;
			})}
		</>
	);
};

const isPausedFrame = (segments: TutorialSegment[], frame: number, fps: number) => {
	let cursor = 0;
	for (const segment of segments) {
		const duration = frames(segment.duration_ms, fps);
		if (frame >= cursor && frame < cursor + duration) return segment.kind === 'freeze';
		cursor += duration;
	}
	return false;
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

const PHONE_TOP_CHROME_HEIGHT = 128;
const PHONE_BOTTOM_CHROME_HEIGHT = 85;
const PHONE_STATUS_HEIGHT = 44;
const PHONE_TAB_HEIGHT = PHONE_TOP_CHROME_HEIGHT - PHONE_STATUS_HEIGHT;

const PhoneMoon: React.FC = () => (
	<span style={{backgroundColor: '#fff', borderRadius: '50%', display: 'inline-block', height: 20, marginLeft: 8, position: 'relative', width: 20}}>
		<span style={{backgroundColor: '#222', borderRadius: '50%', display: 'block', height: 20, left: 7, position: 'absolute', top: -2, width: 20}} />
	</span>
);

const PhoneSignal: React.FC = () => (
	<div style={{alignItems: 'flex-end', display: 'flex', gap: 3, height: 18, width: 25}}>
		{[8, 11, 14, 17].map((height, index) => <span key={height} style={{backgroundColor: '#fff', borderRadius: 2, height, opacity: index < 2 ? 1 : 0.36, width: 4}} />)}
	</div>
);

const PhoneWifi: React.FC = () => (
	<div style={{height: 18, position: 'relative', width: 24}}>
		<span style={{border: '3px solid #fff', borderBottomColor: 'transparent', borderLeftColor: 'transparent', borderRadius: '50%', borderRightColor: 'transparent', height: 23, left: 0, position: 'absolute', top: 2, width: 24}} />
		<span style={{border: '3px solid #fff', borderBottomColor: 'transparent', borderLeftColor: 'transparent', borderRadius: '50%', borderRightColor: 'transparent', height: 15, left: 5, position: 'absolute', top: 8, width: 14}} />
		<span style={{backgroundColor: '#fff', borderRadius: '50%', height: 4, left: 10, position: 'absolute', top: 16, width: 4}} />
	</div>
);

const PhoneBattery: React.FC = () => (
	<div style={{alignItems: 'center', display: 'flex', height: 18, width: 31}}>
		<div style={{border: '2px solid #fff', borderRadius: 6, height: 16, padding: 2, width: 25}}>
			<div style={{backgroundColor: '#fff', borderRadius: 3, height: '100%', width: '78%'}} />
		</div>
		<span style={{backgroundColor: '#fff', borderRadius: 2, height: 8, width: 2}} />
	</div>
);

const PhoneStatusBar: React.FC = () => (
	<div style={{alignItems: 'center', color: '#fff', display: 'flex', fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: 18, fontWeight: 700, height: PHONE_STATUS_HEIGHT, justifyContent: 'space-between', padding: '10px 29px 0 32px'}}>
		<div style={{alignItems: 'center', display: 'flex'}}>13:47<PhoneMoon /></div>
		<div style={{alignItems: 'center', display: 'flex', gap: 9}}><PhoneSignal /><PhoneWifi /><PhoneBattery /></div>
	</div>
);

const PhoneTabGroupBar: React.FC<{label: string}> = ({label}) => (
	<div style={{alignItems: 'center', display: 'flex', height: PHONE_TAB_HEIGHT, paddingLeft: 16}}>
		<div style={{alignItems: 'center', backgroundColor: '#0d0d0f', border: '1px solid rgba(255, 255, 255, 0.10)', borderRadius: 33, boxShadow: '0 16px 34px rgba(0, 0, 0, 0.28)', color: '#fff', display: 'flex', fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: 22, fontWeight: 750, height: 51, padding: '0 20px'}}>
			<span>{label}</span>
			<span style={{borderRight: '3px solid #a9a9b3', borderTop: '3px solid #a9a9b3', height: 10, marginLeft: 9, transform: 'rotate(45deg)', width: 10}} />
		</div>
	</div>
);

const PhoneBottomBar: React.FC<{domain: string}> = ({domain}) => (
	<div style={{alignItems: 'center', background: 'linear-gradient(180deg, rgba(34, 34, 35, 0.96) 0%, #19191a 100%)', display: 'flex', gap: 9, height: PHONE_BOTTOM_CHROME_HEIGHT, padding: '10px 33px 13px'}}>
		<div aria-label="Back" style={{alignItems: 'center', backgroundColor: '#0b0b0c', border: '1px solid rgba(255, 255, 255, 0.10)', borderRadius: '50%', color: '#fff', display: 'flex', flex: '0 0 49px', fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: 38, fontWeight: 300, height: 49, justifyContent: 'center', lineHeight: 1}}>&lt;</div>
		<div style={{alignItems: 'center', backgroundColor: '#121213', border: '1px solid rgba(255, 255, 255, 0.10)', borderRadius: 28, color: '#f3f4f6', display: 'flex', flex: 1, fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: 17, fontWeight: 650, height: 49, minWidth: 0, padding: '0 15px'}}>
			<div style={{border: '2px solid #fff', borderRadius: 4, height: 13, marginRight: 11, position: 'relative', width: 17}}><span style={{backgroundColor: '#fff', bottom: -6, height: 2, left: 2, position: 'absolute', width: 13}} /></div>
			<span style={{flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{domain}</span>
			<div aria-label="Reload" style={{border: '3px solid #fff', borderLeftColor: 'transparent', borderRadius: '50%', flex: '0 0 21px', height: 21, marginLeft: 11, transform: 'rotate(35deg)', width: 21}} />
		</div>
		<div aria-label="More" style={{alignItems: 'center', backgroundColor: '#0b0b0c', border: '1px solid rgba(255, 255, 255, 0.10)', borderRadius: '50%', color: '#fff', display: 'flex', flex: '0 0 49px', fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: 26, fontWeight: 700, height: 49, justifyContent: 'center', letterSpacing: 2, lineHeight: 1}}>...</div>
	</div>
);

const PhonePauseBadge: React.FC = () => (
	<div style={{alignItems: 'center', background: 'rgba(15, 23, 42, 0.78)', border: '1px solid rgba(255, 255, 255, 0.20)', borderRadius: 999, display: 'flex', height: 28, justifyContent: 'center', position: 'absolute', right: 15, top: PHONE_STATUS_HEIGHT + 24, width: 42, zIndex: 4}}>
		<span aria-label="Paused recording" style={{display: 'inline-flex', gap: 4}}>
			<span style={{background: '#fff', borderRadius: 2, height: 12, width: 4}} />
			<span style={{background: '#fff', borderRadius: 2, height: 12, width: 4}} />
		</span>
	</div>
);

const PhoneSafariTutorial: React.FC<BrowserTutorialProps & {source: string; paused: boolean}> = (props) => {
	const tabGroupLabel = props.browserChrome?.tabGroupLabel?.trim() || 'Personal';
	return (
		<AbsoluteFill style={{backgroundColor: '#242424', color: '#fff', overflow: 'hidden'}}>
			<PhoneStatusBar />
			<PhoneTabGroupBar label={tabGroupLabel} />
			{props.paused ? <PhonePauseBadge /> : null}
			<div style={{backgroundColor: '#fff', height: props.viewport.height, overflow: 'hidden', position: 'absolute', top: PHONE_TOP_CHROME_HEIGHT, width: props.viewport.width}}>
				<Segments segments={props.segments} source={props.source} fps={props.output.fps} />
			</div>
			<div style={{bottom: 0, left: 0, position: 'absolute', right: 0}}>
				<PhoneBottomBar domain={props.domain} />
			</div>
		</AbsoluteFill>
	);
};

export const BrowserTutorial: React.FC<BrowserTutorialProps> = (props) => {
	const source = staticFile(props.sourceVideo);
	const paused = isPausedFrame(props.segments, useCurrentFrame(), props.output.fps);
	if (props.deviceProfile === 'web-phone') return <PhoneSafariTutorial {...props} source={source} paused={paused} />;
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
					display: 'flex',
					height: layout.toolbarHeight,
					padding: '0 18px',
				}}>
					<div style={{display: 'flex', flex: 1, gap: 8}}>
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
						height: props.output.width >= 900 ? 34 : 28,
						justifyContent: 'center',
						maxWidth: props.output.width >= 900 ? 640 : 260,
						minWidth: 0,
						overflow: 'hidden',
						padding: '0 18px',
						textOverflow: 'ellipsis',
						whiteSpace: 'nowrap',
						width: '54%',
					}}>
						<span>{props.domain}</span>
					</div>
					<div style={{alignItems: 'center', display: 'flex', flex: 1, justifyContent: 'flex-end'}}>
						{paused ? <PauseBadge /> : null}
						<div aria-label="New tab" style={{color: '#64748b', fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: 26, fontWeight: 300, lineHeight: 1}}>+</div>
					</div>
				</div>
				<div style={{backgroundColor: '#fff', height: layout.contentHeight, overflow: 'hidden', position: 'relative', width: layout.contentWidth}}>
					<Segments segments={props.segments} source={source} fps={props.output.fps} />
				</div>
			</div>
		</AbsoluteFill>
	);
};

export const tutorialDurationInFrames = (props: BrowserTutorialProps) => props.segments.reduce(
	(total, segment) => total + frames(segment.duration_ms, props.output.fps),
	0
);
