/**
 * Deterministic macOS-style terminal composition for real CLI recordings.
 *
 * The captured source video is real terminal pixels. Remotion only adds the
 * surrounding terminal chrome and stable background for OpenCode proof playback.
 */

import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile} from 'remotion';

import type {TerminalTutorialProps} from './types';

const terminalLayout = (props: TerminalTutorialProps) => {
	const padding = 32;
	const toolbarHeight = 42;
	const contentRatio = props.viewport.width / props.viewport.height;
	const maxContentWidth = props.output.width - padding * 2;
	const maxContentHeight = props.output.height - padding * 2 - toolbarHeight;
	const contentWidth = Math.min(maxContentWidth, Math.round(maxContentHeight * contentRatio));
	const contentHeight = Math.min(maxContentHeight, Math.round(contentWidth / contentRatio));
	return {
		contentWidth,
		contentHeight,
		toolbarHeight,
		windowWidth: contentWidth,
		windowHeight: contentHeight + toolbarHeight,
	};
};

export const TerminalTutorial: React.FC<TerminalTutorialProps> = (props) => {
	const source = staticFile(props.sourceVideo);
	const layout = terminalLayout(props);
	return (
		<AbsoluteFill style={{alignItems: 'center', background: 'linear-gradient(135deg, #dbeafe 0%, #f8fafc 45%, #e0e7ff 100%)', display: 'flex', justifyContent: 'center'}}>
			<div style={{
				backgroundColor: '#111827',
				border: '1px solid rgba(15, 23, 42, 0.18)',
				borderRadius: 18,
				boxShadow: '0 30px 86px rgba(15, 23, 42, 0.25), 0 5px 18px rgba(15, 23, 42, 0.14)',
				height: layout.windowHeight,
				overflow: 'hidden',
				width: layout.windowWidth,
			}}>
				<div style={{
					alignItems: 'center',
					background: 'linear-gradient(180deg, #f8fafc 0%, #dbe1ea 100%)',
					borderBottom: '1px solid rgba(15, 23, 42, 0.18)',
					display: 'flex',
					height: layout.toolbarHeight,
					padding: '0 16px',
				}}>
					<div style={{display: 'flex', gap: 8, width: 86}}>
						<span style={{backgroundColor: '#ff5f57', borderRadius: '50%', height: 12, width: 12}} />
						<span style={{backgroundColor: '#febc2e', borderRadius: '50%', height: 12, width: 12}} />
						<span style={{backgroundColor: '#28c840', borderRadius: '50%', height: 12, width: 12}} />
					</div>
					<div style={{
						color: '#334155',
						flex: 1,
						fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
						fontSize: 15,
						fontWeight: 600,
						letterSpacing: '-0.01em',
						overflow: 'hidden',
						textAlign: 'center',
						textOverflow: 'ellipsis',
						whiteSpace: 'nowrap',
					}}>
						Terminal
					</div>
					<div style={{width: 86}} />
				</div>
				<div style={{backgroundColor: '#111827', height: layout.contentHeight, overflow: 'hidden', width: layout.contentWidth}}>
					<OffthreadVideo src={source} volume={0} style={{height: '100%', objectFit: 'fill', width: '100%'}} />
				</div>
			</div>
		</AbsoluteFill>
	);
};

export const terminalDurationInFrames = (props: TerminalTutorialProps) => Math.max(1, Math.round(Number(props.durationSeconds ?? 1) * props.output.fps));
