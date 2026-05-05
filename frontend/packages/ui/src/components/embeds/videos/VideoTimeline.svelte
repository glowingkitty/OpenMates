<!--
  frontend/packages/ui/src/components/embeds/videos/VideoTimeline.svelte

  Interactive timeline visualization for Remotion-generated videos.
  Parses a VideoManifest (tracks with items) and renders colored blocks
  on a time ruler. Supports synced playback with a <video> element:
  - Clicking on the timeline seeks the video
  - Video playback updates the playhead position
  - Compact mode for embed previews, full mode for fullscreen

  Used by VideoCreateEmbedPreview (compact) and VideoCreateEmbedFullscreen (full).
-->

<script lang="ts">
	import type { VideoManifest } from '../../../utils/remotionTimelineParser';

	interface Props {
		/** Parsed timeline manifest from Remotion code */
		manifest: VideoManifest;
		/** Current playback time in seconds (synced with video) */
		currentTime?: number;
		/** Whether the timeline is in compact mode (fewer details, shorter height) */
		compact?: boolean;
		/** Called when user clicks/scrubs the timeline to seek */
		onSeek?: (timeSeconds: number) => void;
	}

	let {
		manifest,
		currentTime = 0,
		compact = false,
		onSeek,
	}: Props = $props();

	let timelineBarEl: HTMLDivElement | undefined = $state();

	const totalSeconds = $derived(manifest.meta.durationSeconds);
	const totalFrames = $derived(manifest.meta.durationInFrames);
	const fps = $derived(manifest.meta.fps);
	const playheadPct = $derived(
		totalSeconds > 0 ? Math.min((currentTime / totalSeconds) * 100, 100) : 0
	);

	function rulerMarks(): number[] {
		const step = totalSeconds <= 5 ? 1 : totalSeconds <= 15 ? 2 : 5;
		return Array.from({ length: Math.floor(totalSeconds / step) + 1 }, (_, i) => i * step);
	}

	function formatTime(frames: number): string {
		const seconds = frames / fps;
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`;
	}

	function handleTimelineClick(e: MouseEvent) {
		if (!timelineBarEl || !onSeek) return;
		const rect = timelineBarEl.getBoundingClientRect();
		const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		onSeek(pct * totalSeconds);
	}

	let isDragging = $state(false);

	function handleMouseDown(e: MouseEvent) {
		if (!onSeek) return;
		isDragging = true;
		handleTimelineClick(e);
		const onMove = (me: MouseEvent) => {
			if (isDragging) handleTimelineClick(me);
		};
		const onUp = () => {
			isDragging = false;
			window.removeEventListener('mousemove', onMove);
			window.removeEventListener('mouseup', onUp);
		};
		window.addEventListener('mousemove', onMove);
		window.addEventListener('mouseup', onUp);
	}
</script>

<div class="timeline" class:compact class:interactive={!!onSeek}>
	{#if !compact}
		<!-- Time ruler -->
		<div class="time-ruler">
			<div class="track-label-spacer"></div>
			<div class="ruler-bar">
				{#each rulerMarks() as sec}
					<span class="ruler-mark" style="left: {(sec / totalSeconds) * 100}%">
						{sec}s
					</span>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Tracks -->
	{#each manifest.tracks as track}
		<div class="track-row">
			{#if !compact}
				<div class="track-label">
					<span class="track-type-icon">
						{#if track.type === 'audio'}&#9835;{:else}&#9632;{/if}
					</span>
					{track.name}
				</div>
			{/if}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="track-items"
				bind:this={timelineBarEl}
				onmousedown={handleMouseDown}
			>
				{#each track.items as item}
					{@const leftPct = (item.from / totalFrames) * 100}
					{@const widthPct = (item.durationInFrames / totalFrames) * 100}
					<div
						class="track-item"
						style="left: {leftPct}%; width: {widthPct}%; background-color: {item.color};"
						title="{item.label} ({formatTime(item.from)} - {formatTime(item.from + item.durationInFrames)})"
					>
						{#if !compact || widthPct > 15}
							<span class="item-label">{item.label}</span>
						{/if}
						{#if !compact && widthPct > 10}
							<span class="item-duration">{formatTime(item.durationInFrames)}</span>
						{/if}
					</div>
				{/each}

				<!-- Playhead -->
				{#if currentTime > 0 || isDragging}
					<div class="playhead" style="left: {playheadPct}%"></div>
				{/if}
			</div>
		</div>
	{/each}
</div>

<style>
	.timeline {
		padding: 8px 0;
		user-select: none;
	}

	.timeline.interactive .track-items {
		cursor: pointer;
	}

	.timeline.compact .track-row {
		min-height: 20px;
		margin-bottom: 3px;
	}

	.timeline.compact .track-items {
		height: 20px;
	}

	.timeline.compact .track-item {
		height: 16px;
		top: 2px;
		border-radius: 3px;
	}

	.timeline.compact .item-label {
		font-size: 9px;
	}

	/* ─── Time ruler ─── */

	.time-ruler {
		display: flex;
		align-items: flex-end;
		margin-bottom: 6px;
		height: 18px;
	}

	.track-label-spacer {
		width: 90px;
		min-width: 90px;
	}

	.ruler-bar {
		flex: 1;
		position: relative;
		height: 18px;
		border-bottom: 1px solid var(--color-grey-30, #ccc);
	}

	.ruler-mark {
		position: absolute;
		bottom: 2px;
		transform: translateX(-50%);
		font-size: 10px;
		color: var(--color-font-tertiary, #888);
		font-variant-numeric: tabular-nums;
	}

	/* ─── Tracks ─── */

	.track-row {
		display: flex;
		align-items: stretch;
		margin-bottom: 4px;
		min-height: 28px;
	}

	.track-label {
		width: 90px;
		min-width: 90px;
		font-size: 11px;
		font-weight: 500;
		color: var(--color-font-secondary, #555);
		display: flex;
		align-items: center;
		gap: 5px;
		padding-right: 8px;
	}

	.track-type-icon {
		font-size: 9px;
		opacity: 0.5;
	}

	.track-items {
		flex: 1;
		position: relative;
		height: 28px;
		background: var(--color-grey-10, #f4f4f4);
		border-radius: 4px;
		overflow: hidden;
	}

	:global(.dark) .track-items {
		background: var(--color-grey-20, #2a2a2a);
	}

	.track-item {
		position: absolute;
		top: 2px;
		height: 24px;
		border-radius: 3px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 6px;
		box-sizing: border-box;
		overflow: hidden;
		min-width: 2px;
		transition: filter 0.12s;
	}

	.track-item:hover {
		filter: brightness(1.15);
	}

	.item-label {
		font-size: 10px;
		font-weight: 500;
		color: white;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
	}

	.item-duration {
		font-size: 9px;
		color: rgba(255, 255, 255, 0.75);
		white-space: nowrap;
		margin-left: 4px;
		flex-shrink: 0;
	}

	/* ─── Playhead ─── */

	.playhead {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 2px;
		background: var(--color-button-primary, #e74c3c);
		z-index: 2;
		pointer-events: none;
		box-shadow: 0 0 4px rgba(231, 76, 60, 0.5);
	}

	.playhead::before {
		content: '';
		position: absolute;
		top: -4px;
		left: -4px;
		width: 10px;
		height: 10px;
		background: var(--color-button-primary, #e74c3c);
		border-radius: 50%;
	}
</style>
