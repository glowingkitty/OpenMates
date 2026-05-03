<!--
  frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedPreview.svelte

  Embed preview card for AI-generated Remotion videos (Video Create skill).
  Shows a compact timeline visualization of the video structure,
  with a thumbnail overlay once the video has been rendered.

  Status lifecycle:
    'processing' → Compact timeline + "Rendering..." spinner
    'finished'   → Thumbnail + play button + duration badge
    'error'      → Error message + retry option

  The timeline is parsed from Remotion TSX code via remotionTimelineParser.
  In the preview card, it shows a compact read-only view (no track labels,
  smaller blocks). Clicking opens fullscreen with the synced video player.
-->

<script lang="ts">
	import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
	import VideoTimeline from './VideoTimeline.svelte';
	import type { VideoManifest } from '../../../utils/remotionTimelineParser';

	interface Props {
		/** Unique embed ID */
		id: string;
		/** Parsed timeline manifest */
		manifest: VideoManifest;
		/** Status of video rendering */
		status: 'processing' | 'finished' | 'error';
		/** URL to the rendered video (set when finished) */
		videoUrl?: string;
		/** URL to the video thumbnail */
		thumbnailUrl?: string;
		/** Error message if render failed */
		errorMessage?: string;
		/** Whether to use mobile layout */
		isMobile?: boolean;
		/** Called when user clicks to open fullscreen */
		onFullscreen: () => void;
	}

	let {
		id,
		manifest,
		status,
		videoUrl: _videoUrl,
		thumbnailUrl,
		errorMessage,
		isMobile = false,
		onFullscreen,
	}: Props = $props();

	const unifiedStatus = $derived(
		status === 'processing' ? 'processing' as const
		: status === 'error' ? 'error' as const
		: 'finished' as const
	);

	const durationLabel = $derived(`${manifest.meta.durationSeconds}s`);
	const resolutionLabel = $derived(`${manifest.meta.width}x${manifest.meta.height}`);
</script>

<UnifiedEmbedPreview
	{id}
	appId="videos"
	skillId="create"
	skillIconName="video"
	status={unifiedStatus}
	skillName="Video Create"
	{isMobile}
	{onFullscreen}
	customStatusText={status === 'processing' ? 'Rendering video...' : `${durationLabel} · ${resolutionLabel}`}
>
	{#snippet details({ isMobile: isMobileLayout })}
		<div class="preview-details">
			{#if status === 'finished' && thumbnailUrl}
				<div class="thumbnail-wrapper">
					<img src={thumbnailUrl} alt={manifest.meta.title} class="thumbnail" />
					<div class="play-overlay">
						<span class="play-icon">&#9654;</span>
					</div>
					<span class="duration-badge">{durationLabel}</span>
				</div>
			{:else if status === 'error'}
				<div class="error-area">
					<span class="error-icon">&#9888;</span>
					<span class="error-text">{errorMessage || 'Render failed'}</span>
				</div>
			{:else}
				<!-- Processing or no thumbnail: show compact timeline -->
				<div class="timeline-wrapper">
					<div class="title-row">
						<span class="video-title">{manifest.meta.title}</span>
						<span class="meta-badge">{durationLabel}</span>
					</div>
					<VideoTimeline {manifest} compact />
				</div>
			{/if}
		</div>
	{/snippet}
</UnifiedEmbedPreview>

<style>
	.preview-details {
		width: 100%;
		height: 100%;
		display: flex;
		flex-direction: column;
		padding: 10px 12px 4px;
		box-sizing: border-box;
		overflow: hidden;
	}

	/* ─── Thumbnail mode ─── */

	.thumbnail-wrapper {
		position: relative;
		flex: 1;
		border-radius: 6px;
		overflow: hidden;
		background: var(--color-grey-15, #eee);
	}

	.thumbnail {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.play-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(0, 0, 0, 0.25);
		opacity: 0;
		transition: opacity 0.15s;
	}

	.thumbnail-wrapper:hover .play-overlay {
		opacity: 1;
	}

	.play-icon {
		font-size: 32px;
		color: white;
		filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.4));
	}

	.duration-badge {
		position: absolute;
		bottom: 6px;
		right: 6px;
		padding: 2px 6px;
		border-radius: 4px;
		background: rgba(0, 0, 0, 0.7);
		color: white;
		font-size: 10px;
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}

	/* ─── Timeline mode ─── */

	.timeline-wrapper {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.title-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}

	.video-title {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-font-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.meta-badge {
		font-size: 10px;
		color: var(--color-font-tertiary, #888);
		flex-shrink: 0;
		font-variant-numeric: tabular-nums;
	}

	/* ─── Error mode ─── */

	.error-area {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: var(--color-font-tertiary, #888);
		font-size: 13px;
	}

	.error-icon {
		font-size: 18px;
		color: var(--color-error, #e74c3c);
	}

	.error-text {
		color: var(--color-font-secondary, #555);
	}
</style>
