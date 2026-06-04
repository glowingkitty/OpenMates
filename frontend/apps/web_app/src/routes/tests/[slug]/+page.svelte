<!--
  Playwright recording detail view.
  Shows the latest video, linked step timeline, reused screenshots, and failure
  details for one E2E spec from the generated recording manifest.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import {
		fetchTestRecording,
		formatDuration,
		formatVideoTime,
		type TestRecordingDetail,
		type TestRecordingStep
	} from '../testRecordings';

	let recording: TestRecordingDetail | null = $state(null);
	let errorMessage = $state('');
	let isLoading = $state(true);
	let videoElement: HTMLVideoElement | null = $state(null);
	let enlargedScreenshot: { url: string; title: string } | null = $state(null);

	onMount(async () => {
		try {
			const slug = $page.params.slug;
			if (!slug) throw new Error('Missing test recording slug.');
			recording = await fetchTestRecording(slug);
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : 'Failed to load test recording.';
		} finally {
			isLoading = false;
		}
	});

	function jumpToStep(step: TestRecordingStep) {
		if (!videoElement || step.video_time_seconds == null) return;
		videoElement.currentTime = Math.max(0, step.video_time_seconds);
		void videoElement.play();
	}

	function closeScreenshot() {
		enlargedScreenshot = null;
	}
</script>

<svelte:head>
	<title>{recording?.title ?? 'Test Recording'} | OpenMates</title>
	<meta name="robots" content="noindex,nofollow" />
</svelte:head>

<main class="detail-page">
	<a class="back-link" href="/tests">&larr; All recordings</a>

	{#if isLoading}
		<div class="state-card">Loading recording...</div>
	{:else if errorMessage}
		<div class="state-card error">{errorMessage}</div>
	{:else if recording}
		<header class="header">
			<div>
				<p class="eyebrow">{recording.status}</p>
				<h1>{recording.title}</h1>
				<p class="meta">
					{recording.run_id} &middot; {formatDuration(recording.duration_seconds)}
					{#if recording.git_sha}
						 &middot; {recording.git_sha.slice(0, 9)}
					{/if}
				</p>
			</div>
			<div class="links">
				{#if recording.github_run_url}
					<a href={recording.github_run_url} target="_blank" rel="noreferrer">GitHub run</a>
				{/if}
				{#if recording.assets?.report_url}
					<a href={recording.assets.report_url} target="_blank" rel="noreferrer">Markdown report</a>
				{/if}
			</div>
		</header>

		<section class="video-panel">
			{#if recording.assets?.video_url}
				<video bind:this={videoElement} controls playsinline preload="metadata" poster={recording.assets.thumbnail_url ?? undefined}>
					<source src={recording.assets.video_url} />
				</video>
			{:else}
				<div class="no-video">No video was uploaded for this spec.</div>
			{/if}
		</section>

		{#if recording.error}
			<section class="error-block">
				<h2>Failure</h2>
				<pre>{recording.error}</pre>
			</section>
		{/if}

		<section class="steps-card">
			<h2>Steps</h2>
			{#if recording.steps?.length}
				<ol class="steps">
					{#each recording.steps as step (step.index)}
						<li class:failed={step.status === 'failed' || Boolean(step.error)}>
							<button class="step-link" type="button" onclick={() => jumpToStep(step)} disabled={step.video_time_seconds == null}>
								<span class="step-time">{formatVideoTime(step.video_time_seconds)}</span>
								<span class="step-copy">
									<strong>{step.title}</strong>
									{#if step.duration_seconds != null}
										<small>{formatDuration(step.duration_seconds)}</small>
									{/if}
								</span>
							</button>
							{#if step.screenshot_url}
								<button
									class="step-thumbnail"
									type="button"
									onclick={() => (enlargedScreenshot = { url: step.screenshot_url!, title: step.title })}
									aria-label={`Open screenshot for ${step.title}`}
								>
									<img src={step.screenshot_url} alt={`Screenshot for ${step.title}`} loading="lazy" />
								</button>
							{/if}
							{#if step.error}
								<pre>{step.error}</pre>
							{/if}
						</li>
					{/each}
				</ol>
			{:else}
				<p class="muted">No structured steps were available for this spec.</p>
			{/if}
		</section>
	{/if}
</main>

{#if enlargedScreenshot}
	<button class="screenshot-lightbox" type="button" onclick={closeScreenshot} aria-label="Close screenshot preview">
		<img src={enlargedScreenshot.url} alt={enlargedScreenshot.title} />
	</button>
{/if}

<style>
	.detail-page {
		min-height: 100vh;
		padding: clamp(20px, 4vw, 52px);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		color: var(--color-font-primary);
		background: var(--color-grey-0);
	}

	.back-link,
	.links a {
		color: var(--color-button-primary);
		font-weight: 700;
		text-decoration: none;
	}

	.header {
		display: flex;
		justify-content: space-between;
		gap: 24px;
		align-items: flex-end;
		margin: 28px 0 24px;
	}

	.eyebrow {
		margin: 0 0 8px;
		font-size: 13px;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--color-font-secondary);
	}

	h1 {
		max-width: 980px;
		margin: 0;
		font-size: clamp(32px, 5vw, 62px);
		line-height: 0.98;
		letter-spacing: -0.04em;
	}

	.meta,
	.muted {
		color: var(--color-font-secondary);
	}

	.links {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
	}

	.video-panel,
	.error-block,
	.steps-card,
	.state-card {
		border: 1px solid var(--color-grey-20);
		border-radius: 28px;
		background: var(--color-grey-0);
		box-shadow: 0 18px 42px rgba(0, 0, 0, 0.09);
	}

	.video-panel {
		overflow: hidden;
		max-width: 1180px;
		margin: 0 auto;
		background: var(--color-grey-100);
	}

	video,
	.no-video {
		width: 100%;
		aspect-ratio: 16 / 9;
		display: block;
	}

	video {
		max-height: min(56vh, 620px);
		object-fit: contain;
		background: var(--color-grey-100);
	}

	.no-video {
		display: grid;
		place-items: center;
		color: white;
	}

	.error-block,
	.steps-card,
	.state-card {
		padding: 22px;
	}

	.error-block {
		margin-top: 22px;
		border-color: rgba(193, 51, 51, 0.3);
	}

	h2 {
		margin: 0 0 16px;
		font-size: 22px;
	}

	pre {
		overflow: auto;
		margin: 0;
		padding: 14px;
		border-radius: 14px;
		background: var(--color-grey-10);
		white-space: pre-wrap;
	}

	.steps-card {
		margin-top: 22px;
	}

	.steps {
		display: grid;
		gap: 14px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.steps li {
		overflow: visible;
		padding: 14px;
		border: 1px solid var(--color-grey-15);
		border-radius: 18px;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
	}

	.steps li.failed {
		border-color: rgba(193, 51, 51, 0.35);
	}

	.step-link {
		display: grid;
		grid-template-columns: 64px 1fr;
		gap: 12px;
		align-items: start;
		width: fit-content;
		max-width: 100%;
		padding: 0;
		border: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	.step-link:disabled {
		cursor: default;
	}

	.step-time {
		display: inline-grid;
		place-items: center;
		height: 32px;
		border-radius: 999px;
		background: var(--color-grey-100);
		color: var(--color-grey-0);
		font-size: 12px;
		font-weight: 800;
	}

	.step-copy strong,
	.step-copy small {
		display: block;
	}

	.step-copy small {
		margin-top: 4px;
		color: var(--color-font-secondary);
		font-size: 12px;
	}

	.step-thumbnail {
		display: block;
		width: min(260px, 100%);
		margin: 12px 0 0 76px;
		padding: 0;
		border: 1px solid var(--color-grey-20);
		border-radius: 12px;
		background: var(--color-grey-100);
		cursor: zoom-in;
		overflow: hidden;
	}

	.step-thumbnail img {
		display: block;
		width: 100%;
		aspect-ratio: 16 / 9;
		object-fit: cover;
	}

	.screenshot-lightbox {
		position: fixed;
		inset: 0;
		z-index: 1000;
		display: grid;
		place-items: center;
		padding: 32px;
		border: 0;
		background: rgba(0, 0, 0, 0.82);
		cursor: zoom-out;
	}

	.screenshot-lightbox img {
		display: block;
		max-width: min(1400px, 96vw);
		max-height: 92vh;
		object-fit: contain;
		border-radius: 16px;
		background: var(--color-grey-0);
	}

	.state-card {
		margin-top: 28px;
		text-align: center;
	}

	.state-card.error {
		color: #c13333;
	}

	@media (max-width: 920px) {
		.header {
			display: flex;
			flex-direction: column;
		}

		.step-thumbnail {
			margin-left: 0;
		}
	}
</style>
