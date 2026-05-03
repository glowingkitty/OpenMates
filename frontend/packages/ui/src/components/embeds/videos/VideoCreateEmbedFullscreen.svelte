<!--
  frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedFullscreen.svelte

  Fullscreen view for AI-generated Remotion videos.
  Shows a video player synced with an interactive timeline:
  - Video playback moves the playhead on the timeline
  - Clicking/dragging the timeline seeks the video
  - Track labels, time ruler, and item details visible

  Layout (top to bottom):
  1. Top bar with close/share/download buttons
  2. Video player (16:9 aspect ratio)
  3. Custom playback controls (play/pause, time, fullscreen)
  4. Interactive timeline with tracks and playhead
  5. Video metadata (title, resolution, fps)
-->

<script lang="ts">
	import VideoTimeline from './VideoTimeline.svelte';
	import type { VideoManifest } from '../../../utils/remotionTimelineParser';

	interface Props {
		/** Parsed timeline manifest */
		manifest: VideoManifest;
		/** URL to the rendered video */
		videoUrl: string;
		/** Called when user closes fullscreen */
		onClose: () => void;
		/** Navigation props */
		hasPreviousEmbed?: boolean;
		hasNextEmbed?: boolean;
		onNavigatePrevious?: () => void;
		onNavigateNext?: () => void;
	}

	let {
		manifest,
		videoUrl,
		onClose,
		hasPreviousEmbed = false,
		hasNextEmbed = false,
		onNavigatePrevious,
		onNavigateNext,
	}: Props = $props();

	let videoEl: HTMLVideoElement | undefined = $state();
	let currentTime = $state(0);
	let _duration = $state(0);
	let isPlaying = $state(false);

	function handleTimeUpdate() {
		if (videoEl) {
			currentTime = videoEl.currentTime;
			_duration = videoEl.duration || manifest.meta.durationSeconds;
		}
	}

	function handleSeek(timeSeconds: number) {
		if (videoEl) {
			videoEl.currentTime = timeSeconds;
			currentTime = timeSeconds;
		}
	}

	function togglePlayback() {
		if (!videoEl) return;
		if (videoEl.paused) {
			videoEl.play();
			isPlaying = true;
		} else {
			videoEl.pause();
			isPlaying = false;
		}
	}

	function handlePlay() { isPlaying = true; }
	function handlePause() { isPlaying = false; }
	function handleEnded() { isPlaying = false; }

	function handleKeydown(e: KeyboardEvent) {
		if (e.code === 'Space') {
			e.preventDefault();
			togglePlayback();
		} else if (e.code === 'Escape') {
			onClose();
		} else if (e.code === 'ArrowLeft') {
			handleSeek(Math.max(0, currentTime - 2));
		} else if (e.code === 'ArrowRight') {
			handleSeek(Math.min(manifest.meta.durationSeconds, currentTime + 2));
		}
	}

	function formatTimestamp(seconds: number): string {
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return `${m}:${s.toString().padStart(2, '0')}`;
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div class="fullscreen-container" role="dialog" tabindex="0" onkeydown={handleKeydown}>
	<!-- Top bar -->
	<div class="top-bar">
		<h2 class="fs-title">{manifest.meta.title}</h2>
		<div class="top-bar-actions">
			{#if hasPreviousEmbed && onNavigatePrevious}
				<button class="nav-btn" onclick={onNavigatePrevious} title="Previous">&#9664;</button>
			{/if}
			{#if hasNextEmbed && onNavigateNext}
				<button class="nav-btn" onclick={onNavigateNext} title="Next">&#9654;</button>
			{/if}
			<button class="close-btn" onclick={onClose} title="Close">&#10005;</button>
		</div>
	</div>

	<!-- Video player -->
	<div class="video-wrapper">
		<!-- svelte-ignore a11y_media_has_caption -->
		<video
			bind:this={videoEl}
			src={videoUrl}
			ontimeupdate={handleTimeUpdate}
			onplay={handlePlay}
			onpause={handlePause}
			onended={handleEnded}
			preload="metadata"
		></video>
	</div>

	<!-- Custom controls -->
	<div class="controls-bar">
		<button class="play-btn" onclick={togglePlayback} aria-label={isPlaying ? 'Pause' : 'Play'}>
			{#if isPlaying}
				<span class="pause-icon"><span class="bar"></span><span class="bar"></span></span>
			{:else}
				<span class="play-icon"></span>
			{/if}
		</button>
		<span class="time-display">
			{formatTimestamp(currentTime)} / {formatTimestamp(manifest.meta.durationSeconds)}
		</span>

		<!-- Progress bar -->
		<div class="progress-track">
			<div
				class="progress-fill"
				style="width: {manifest.meta.durationSeconds > 0 ? (currentTime / manifest.meta.durationSeconds) * 100 : 0}%"
			></div>
		</div>

		<div class="meta-info">
			<span>{manifest.meta.fps}fps</span>
			<span>{manifest.meta.width}x{manifest.meta.height}</span>
		</div>
	</div>

	<!-- Interactive timeline -->
	<div class="timeline-section">
		<VideoTimeline
			{manifest}
			{currentTime}
			onSeek={handleSeek}
		/>
	</div>

	<!-- Metadata -->
	<div class="metadata-bar">
		<span class="meta-label">{manifest.tracks.length} track{manifest.tracks.length !== 1 ? 's' : ''}</span>
		<span class="meta-dot">·</span>
		<span class="meta-label">{manifest.meta.durationSeconds}s duration</span>
		<span class="meta-dot">·</span>
		<span class="meta-label">{manifest.meta.durationInFrames} frames</span>
	</div>
</div>

<style>
	.fullscreen-container {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--color-grey-0, #fff);
		color: var(--color-font-primary);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		overflow-y: auto;
	}

	:global(.dark) .fullscreen-container {
		background: var(--color-grey-5, #1a1a1a);
	}

	/* ─── Top bar ─── */

	.top-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 16px;
		border-bottom: 1px solid var(--color-grey-20, #e8e8e8);
		flex-shrink: 0;
	}

	.fs-title {
		font-size: 16px;
		font-weight: 600;
		margin: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.top-bar-actions {
		display: flex;
		gap: 8px;
		flex-shrink: 0;
	}

	.nav-btn,
	.close-btn {
		width: 32px;
		height: 32px;
		border: 1px solid var(--color-grey-25, #ddd);
		border-radius: 6px;
		background: var(--color-grey-10, #f4f4f4);
		color: var(--color-font-secondary, #555);
		font-size: 14px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: background 0.12s;
	}

	.nav-btn:hover,
	.close-btn:hover {
		background: var(--color-grey-20, #e0e0e0);
	}

	/* ─── Video ─── */

	.video-wrapper {
		position: relative;
		width: 100%;
		max-width: 900px;
		margin: 0 auto;
		aspect-ratio: 16 / 9;
		background: #000;
		border-radius: 8px;
		overflow: hidden;
		margin-top: 16px;
		flex-shrink: 0;
	}

	video {
		width: 100%;
		height: 100%;
		object-fit: contain;
	}

	/* ─── Controls ─── */

	.controls-bar {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 16px;
		max-width: 900px;
		margin: 0 auto;
		width: 100%;
		box-sizing: border-box;
	}

	.play-btn {
		width: 36px;
		height: 36px;
		border: none;
		border-radius: 50%;
		background: var(--color-button-primary, #5B4CDB);
		color: white;
		font-size: 14px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		transition: transform 0.1s;
	}

	.play-btn:hover {
		transform: scale(1.05);
	}

	.play-btn:active {
		transform: scale(0.97);
	}

	.play-icon {
		width: 0;
		height: 0;
		border-top: 9px solid transparent;
		border-bottom: 9px solid transparent;
		border-left: 15px solid white;
		margin-left: 3px;
	}

	.pause-icon {
		display: flex;
		gap: 4px;
		align-items: center;
		height: 18px;
	}

	.pause-icon .bar {
		width: 4px;
		height: 18px;
		background: white;
		border-radius: 2px;
	}

	.time-display {
		font-size: 12px;
		font-variant-numeric: tabular-nums;
		color: var(--color-font-secondary, #555);
		white-space: nowrap;
		flex-shrink: 0;
	}

	.progress-track {
		flex: 1;
		height: 4px;
		background: var(--color-grey-20, #e0e0e0);
		border-radius: 2px;
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		background: var(--color-button-primary, #5B4CDB);
		border-radius: 2px;
		transition: width 0.1s linear;
	}

	.meta-info {
		display: flex;
		gap: 8px;
		font-size: 11px;
		color: var(--color-font-tertiary, #888);
		flex-shrink: 0;
	}

	/* ─── Timeline section ─── */

	.timeline-section {
		padding: 8px 16px 4px;
		max-width: 900px;
		margin: 0 auto;
		width: 100%;
		box-sizing: border-box;
		border-top: 1px solid var(--color-grey-20, #e8e8e8);
	}

	/* ─── Metadata bar ─── */

	.metadata-bar {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 10px 16px 16px;
		flex-shrink: 0;
	}

	.meta-label {
		font-size: 12px;
		color: var(--color-font-tertiary, #888);
	}

	.meta-dot {
		font-size: 10px;
		color: var(--color-font-tertiary, #888);
	}
</style>
