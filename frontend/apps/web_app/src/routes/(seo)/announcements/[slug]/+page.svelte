<!--
	SEO page for a single announcement newsletter issue at /announcements/{slug}.
	Crawlers see a fully-rendered article; human browsers are redirected to the
	interactive SPA chat via onMount.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import MarkdownIt from 'markdown-it';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
	const bodyHtml = $derived(data.messageBody ? md.render(data.messageBody) : '');
	const teaserCopyLines = ['AI team mates.', 'For everyday tasks & learning.', 'With privacy & safety by design.'];

	let videoEl = $state<HTMLVideoElement | null>(null);
	let teaserBoxEl = $state<HTMLElement | null>(null);
	let isTeaserHovering = $state(false);
	let mouseX = $state(0);
	let mouseY = $state(0);

	const TILT_MAX_ANGLE = 3;
	const TILT_PERSPECTIVE = 800;
	const TILT_SCALE = 0.985;

	let teaserTiltTransform = $derived.by(() => {
		if (!isTeaserHovering) return '';
		const rotateY = mouseX * TILT_MAX_ANGLE;
		const rotateX = -mouseY * TILT_MAX_ANGLE;
		return `perspective(${TILT_PERSPECTIVE}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${TILT_SCALE})`;
	});

	function openVideo(e: MouseEvent | KeyboardEvent) {
		e.preventDefault();
		e.stopPropagation();
		if (!videoEl) return;
		videoEl.play().catch(() => {});
		videoEl.requestFullscreen?.().catch(() => {});
	}

	function handleVideoKeydown(e: KeyboardEvent) {
		if (e.key !== 'Enter' && e.key !== ' ') return;
		openVideo(e);
	}

	function handleMouseEnter(e: MouseEvent) {
		isTeaserHovering = true;
		updateMousePosition(e);
	}

	function handleMouseMove(e: MouseEvent) {
		if (!isTeaserHovering || !teaserBoxEl) return;
		updateMousePosition(e);
	}

	function handleMouseLeave() {
		isTeaserHovering = false;
		mouseX = 0;
		mouseY = 0;
	}

	function updateMousePosition(e: MouseEvent) {
		if (!teaserBoxEl) return;
		const rect = teaserBoxEl.getBoundingClientRect();
		mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
		mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
	}

	onMount(() => {
		if (data.spaUrl) {
			const { pathname, search, hash } = new URL(data.spaUrl);
			window.location.replace(pathname + search + hash);
		}
	});
</script>

<svelte:head>
	<title>{data.title} — OpenMates</title>
	<meta name="description" content={data.summary || data.title} />
	<meta name="keywords" content={data.keywords.join(', ')} />
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<meta property="og:type" content="article" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="{data.title} — OpenMates" />
	<meta property="og:description" content={data.summary || data.title} />
	<meta property="og:site_name" content="OpenMates" />
	{#if data.video.thumbnail_url}
		<meta property="og:image" content={data.video.thumbnail_url} />
	{/if}

	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:url" content={data.canonicalUrl} />
	<meta name="twitter:title" content="{data.title} — OpenMates" />
	<meta name="twitter:description" content={data.summary || data.title} />
	{#if data.video.thumbnail_url}
		<meta name="twitter:image" content={data.video.thumbnail_url} />
	{/if}

	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<main aria-label="{data.title} — OpenMates announcement">
	<article>
		{#if data.video.mp4_url}
			<header class="announcement-hero">
				<div class="hero-text">
					<h1>{data.title}</h1>
					<div class="teaser-copy" aria-label={teaserCopyLines.join(' ')}>
						{#each teaserCopyLines as line}
							<span>{line}</span>
						{/each}
					</div>
					{#if data.summary}
						<p class="summary">{data.summary}</p>
					{/if}
				</div>

				<div
					bind:this={teaserBoxEl}
					class="video-wrapper"
					class:hovering={isTeaserHovering}
					role="button"
					tabindex="0"
					aria-label="Play video"
					style={teaserTiltTransform ? `transform: ${teaserTiltTransform};` : ''}
					onclick={openVideo}
					onkeydown={handleVideoKeydown}
					onmouseenter={handleMouseEnter}
					onmousemove={handleMouseMove}
					onmouseleave={handleMouseLeave}
				>
					{#if data.video.teaser_url || data.video.teaser_mp4_url}
						<video
							class="teaser-video"
							poster={data.video.teaser_webp_url ?? data.video.thumbnail_url ?? undefined}
							autoplay
							muted
							loop
							playsinline
							preload="metadata"
						>
							{#if data.video.teaser_url}
								<source src={data.video.teaser_url} type="video/webm" />
							{/if}
							{#if data.video.teaser_mp4_url}
								<source src={data.video.teaser_mp4_url} type="video/mp4" />
							{/if}
						</video>
					{:else if data.video.teaser_webp_url || data.video.thumbnail_url}
						<img
							class="teaser-video"
							src={data.video.teaser_webp_url ?? data.video.thumbnail_url ?? ''}
							alt=""
							loading="eager"
							decoding="async"
						/>
					{/if}

					<div class="video-play-btn" aria-hidden="true">
						<div class="video-play-icon"></div>
					</div>

				<video
					bind:this={videoEl}
					class="full-video"
					controls
					preload="metadata"
					playsinline
					poster={data.video.thumbnail_url ?? undefined}
				>
					<source src={data.video.mp4_url} type="video/mp4" />
				</video>
				</div>
			</header>
		{:else}
			<header>
				<h1>{data.title}</h1>
				{#if data.summary}
					<p class="summary">{data.summary}</p>
				{/if}
			</header>
		{/if}

		<!-- eslint-disable-next-line svelte/no-at-html-tags -->
		<section class="body">{@html bodyHtml}</section>

		<footer>
			<a href={data.spaUrl}>Open this in OpenMates</a>
		</footer>
	</article>
</main>

<style>
	main {
		max-width: 1050px;
		margin: 0 auto;
		padding: 24px;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
		color: #1a1a1a;
		background: #fff;
	}
	h1 { font-size: 28px; font-weight: 700; margin: 0 0 12px; color: #000; }
	.summary { font-size: 16px; color: #555; margin: 0 0 24px; line-height: 1.6; }
	.announcement-hero {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(420px, 640px);
		gap: 36px;
		align-items: center;
		margin-bottom: 24px;
	}
	.hero-text { min-width: 0; }
	.teaser-copy {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0 0 16px;
		font-size: 20px;
		font-weight: 700;
		line-height: 1.3;
		color: #111;
	}
	.video-wrapper {
		position: relative;
		width: 100%;
		aspect-ratio: 16 / 9;
		background: #000;
		border-radius: 12px;
		overflow: hidden;
		margin: 0;
		cursor: pointer;
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
		transition: transform 160ms ease, box-shadow 160ms ease;
		transform-style: preserve-3d;
	}
	.video-wrapper.hovering {
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.08);
	}
	.video-wrapper:active {
		transform: scale(0.96) !important;
		transition: transform 50ms ease-out;
	}
	.teaser-video,
	.full-video {
		width: 100%;
		height: 100%;
		display: block;
		object-fit: cover;
	}
	.full-video {
		position: absolute;
		inset: 0;
		opacity: 0;
		pointer-events: none;
	}
	.video-play-btn {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		display: flex;
		align-items: center;
		justify-content: center;
		width: 64px;
		height: 64px;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.22);
		backdrop-filter: blur(8px);
		-webkit-backdrop-filter: blur(8px);
		border: 2px solid rgba(255, 255, 255, 0.55);
		pointer-events: none;
	}
	.video-play-icon {
		width: 0;
		height: 0;
		border-top: 12px solid transparent;
		border-bottom: 12px solid transparent;
		border-left: 20px solid rgba(255, 255, 255, 0.95);
		margin-left: 4px;
	}
	@media (max-width: 620px) {
		.announcement-hero {
			position: relative;
			display: block;
			min-height: 250px;
		}
		.hero-text,
		.video-wrapper {
			position: absolute;
			inset: 0;
			display: flex;
			flex-direction: column;
			justify-content: center;
		}
		.hero-text { animation: mobileAnnouncementTextCycle 7s 1 ease-in-out forwards; }
		.video-wrapper {
			align-self: center;
			height: auto;
			opacity: 0;
			animation: mobileAnnouncementVideoCycle 7s 1 ease-in-out forwards;
		}
		.video-wrapper.hovering { transform: none !important; }
	}
	@keyframes mobileAnnouncementTextCycle {
		0%, 45% { opacity: 1; transform: translateY(0); }
		55%, 100% { opacity: 0; transform: translateY(-8px); }
	}
	@keyframes mobileAnnouncementVideoCycle {
		0%, 45% { opacity: 0; transform: translateY(8px); }
		55%, 100% { opacity: 1; transform: translateY(0); }
	}
	@media (max-width: 620px) and (prefers-reduced-motion: reduce) {
		.announcement-hero {
			display: flex;
			flex-direction: column;
			min-height: 0;
		}
		.hero-text,
		.video-wrapper {
			position: static;
			animation: none !important;
			opacity: 1;
			width: 100%;
		}
	}
	.body :global(h2) { font-size: 22px; font-weight: 600; margin: 24px 0 8px; }
	.body :global(h3) { font-size: 18px; font-weight: 600; margin: 20px 0 6px; }
	.body :global(p) { margin: 0 0 16px; line-height: 1.6; }
	.body :global(ul), .body :global(ol) { margin: 0 0 16px 20px; line-height: 1.6; }
	.body :global(a) { color: #4867cd; text-decoration: none; }
	.body :global(a:hover) { text-decoration: underline; }
	footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
	footer a { color: #4867cd; text-decoration: none; font-size: 15px; }
	footer a:hover { text-decoration: underline; }
</style>
